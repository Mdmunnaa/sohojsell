/**
 * কন্টেইনারের সাথে সংযোগ হঠাৎ কেটে গেলে ("Container suddenly disconnected, try again") যা হয়।
 *
 * কন্টেইনার নতুন করে চালু হওয়ার মুহূর্তে (নতুন deploy, Secret বদল, Cloudflare নিজে সার্ভার বদলালে) যে রিকোয়েস্ট
 * মাঝপথে থাকে, সেটা এই ভুল পায়। আগে কাস্টমার/সেলার একটা সাদা পাতায় ইংরেজি লেখা দেখতেন, রিফ্রেশ দিলে ঠিক হতো।
 * এখন:
 *   - পাতা খোলা/দেখা (GET, HEAD): Worker নিজেই কয়েকবার আবার চেষ্টা করে — মানুষ টেরই পান না
 *   - ফর্ম পাঠানো (POST ইত্যাদি): আবার পাঠানো নিরাপদ না (অর্ডার/সেভ দুবার হতে পারে), তাই বাংলায় বুঝিয়ে বলা পাতা
 *   - পেছনের অনুরোধ (POS-এর বিক্রি জমা ইত্যাদি, JSON চায়): {"success": false} আর 503 — POS এটাকে "নেট নেই"-এর
 *     মতো ধরে বিক্রি ফোনে রেখে দেয়, পরে নিজে পাঠায় (pos_ref থাকায় দুবার হয় না)
 * প্রতিটা ঘটনা লগে যায় (Cloudflare → Workers → sellpunch → Observability), কোন ঠিকানায় কতবার হলো দেখা যায়।
 */

/** @cloudflare/containers নিজে যে লেখা দিয়ে ভুল ফেরত দেয় — Django-র নিজের পাতা না */
const CONTAINER_ERRORS = [
	'Container suddenly disconnected',
	'Error proxying request to container',
	'Failed to start container',
	'There is no Container instance available',
];

/** আবার চেষ্টার আগে কতক্ষণ থামা (মিলিসেকেন্ড) — মোট ৩ বার আবার, প্রায় ৪ সেকেন্ড */
export const RETRY_WAITS = [300, 1000, 2500];

/**
 * কন্টেইনার একেবারে নতুন করে চালু হলে (Cloudflare সার্ভার বদলালে) প্রতিবার চেষ্টায় ২০–৩০ সেকেন্ড অপেক্ষা হতে পারে —
 * মোট এর বেশি হয়ে গেলে আর আবার না পাঠিয়ে বুঝিয়ে বলা পাতা (সেটা নিজে কয়েক সেকেন্ড পর আবার খোলে)। মানুষ যেন
 * এক মিনিটের বেশি সাদা পাতার দিকে তাকিয়ে না থাকেন।
 */
export const RETRY_BUDGET_MS = 40_000;

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

/** কন্টেইনারের সংযোগের সাময়িক সমস্যা কিনা (Django-র ৫০০ পাতা হলে না — সেটা আবার চেষ্টায় ঠিক হয় না) */
export async function containerProblem(res: Response): Promise<string | null> {
	if (res.status !== 500 && res.status !== 503 && res.status !== 429) return null;
	if (!(res.headers.get('content-type') || '').startsWith('text/plain')) return null;
	const text = await res.clone().text();
	if (CONTAINER_ERRORS.some((start) => text.startsWith(start))) return text.slice(0, 200);
	return res.status === 429 ? text.slice(0, 200) : null;
}

function sleep(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

export type Send = (request: Request) => Promise<Response>;

/**
 * কন্টেইনারে পাঠানো; সংযোগ কেটে গেলে GET/HEAD আবার পাঠায়। শেষ পর্যন্ত না হলে বুঝিয়ে বলা 503।
 * waits আর budgetMs বদলানো যায় শুধু পরীক্ষার জন্য।
 */
export async function sendWithRetry(
	send: Send, request: Request, waits: number[] = RETRY_WAITS, budgetMs: number = RETRY_BUDGET_MS,
): Promise<Response> {
	const started = Date.now();
	const url = new URL(request.url);
	const safe = SAFE_METHODS.has(request.method);
	let problem = '';
	for (let attempt = 0; ; attempt++) {
		try {
			// GET/HEAD-এর body নেই, তাই একই রিকোয়েস্ট থেকে নতুন কপি বানিয়ে আবার পাঠানো যায়
			const res = await send(attempt === 0 ? request : new Request(request));
			const found = await containerProblem(res);
			if (found === null) {
				if (attempt > 0) console.log(JSON.stringify({ event: 'container_retry_ok', attempt, method: request.method, path: url.pathname }));
				return res;
			}
			problem = found;
			await res.body?.cancel();
		} catch (e) {
			problem = e instanceof Error ? e.message : String(e);
		}
		const waited = Date.now() - started;
		const retry = safe && attempt < waits.length && waited < budgetMs;
		console.error(
			JSON.stringify({ event: 'container_disconnected', attempt, retry, waited, method: request.method, host: url.host, path: url.pathname, problem }),
		);
		if (!retry) return unavailable(request);
		await sleep(waits[attempt]);
	}
}

/** ব্রাউজারে পাতা খোলা (লিংক, ঠিকানা লেখা, ফর্ম পাঠানো) — নাকি পেছনের fetch/JSON অনুরোধ */
function isPage(request: Request): boolean {
	const mode = request.headers.get('Sec-Fetch-Mode');
	if (mode) return mode === 'navigate';
	return (request.headers.get('Accept') || '').includes('text/html');
}

const HEADERS = { 'Cache-Control': 'no-store', 'Retry-After': '5', 'X-Robots-Tag': 'noindex' };

export function unavailable(request: Request): Response {
	if (!isPage(request)) {
		const body = JSON.stringify({
			success: false,
			error: 'সার্ভারের সাথে সংযোগ এক মুহূর্তের জন্য কেটে গেছে। কয়েক সেকেন্ড পর আবার চেষ্টা করুন।',
		});
		return new Response(body, { status: 503, headers: { ...HEADERS, 'Content-Type': 'application/json; charset=utf-8' } });
	}
	const url = new URL(request.url);
	const again = url.pathname + url.search;
	const safe = SAFE_METHODS.has(request.method);
	const text = safe
		? '<p>সার্ভার এই মুহূর্তে নতুন করে চালু হচ্ছে। কয়েক সেকেন্ডের মধ্যে পাতাটা নিজে থেকে আবার খুলবে।</p>'
			+ '<p class="en">Connection lost for a moment. This page will reload by itself in a few seconds.</p>'
			+ '<div class="row"><button type="button" onclick="location.reload()">এখনই আবার চেষ্টা করুন</button></div>'
			+ '<p class="note" id="count"></p>'
		: '<p>আপনি যা পাঠিয়েছিলেন (সেভ, অর্ডার, পেমেন্ট ইত্যাদি) সেটা হয়েছে কিনা নিশ্চিত না। পাতাটা আবার খুলে দেখে নিন, '
			+ 'না হয়ে থাকলে তারপর আবার করুন — দুবার চাপবেন না।</p>'
			+ '<p class="en">Connection lost for a moment. Please reopen the page and check whether your last action was saved before trying again.</p>'
			+ `<div class="row"><a href="${escapeHtml(again)}">পাতাটা আবার খুলুন</a></div>`;
	const script = safe
		// ৫, ১০, ২০, ৩০ সেকেন্ড পরপর — ২ মিনিট আগের গোনা বাদ (পরের কোনো দিনের ঘটনায় আবার ৫ থেকে)
		? '<script>(function(){var n=0,now=Date.now();try{var s=JSON.parse(sessionStorage.getItem("sp_retry")||"{}");'
			+ 'if(now-(s.t||0)<120000)n=s.n||0}catch(e){}'
			+ 'var wait=Math.min(5*Math.pow(2,n),30);try{sessionStorage.setItem("sp_retry",JSON.stringify({n:n+1,t:now}))}catch(e){}'
			+ 'var el=document.getElementById("count");(function tick(){if(wait<=0){location.reload();return}'
			+ 'el.textContent=String(wait).replace(/\\d/g,function(d){return "০১২৩৪৫৬৭৮৯"[d]})+" সেকেন্ড পর আবার চেষ্টা করবে";wait--;setTimeout(tick,1000)})()})()</script>'
		: '';
	const html = '<!doctype html><html lang="bn"><head><meta charset="utf-8">'
		+ '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
		+ '<title>এক মুহূর্ত</title><style>'
		+ 'body{font-family:"Hind Siliguri",system-ui,-apple-system,"Segoe UI",sans-serif;background:#F0F2F6;color:#0F172A;margin:0;'
		+ 'min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box}'
		+ '.box{max-width:440px;width:100%;background:#fff;border:1px solid #E2E8F0;border-radius:20px;padding:28px 22px;text-align:center}'
		+ 'h1{font-size:20px;margin:0 0 10px;line-height:1.4}p{color:#475569;line-height:1.7;margin:0 0 8px;font-size:15px}'
		+ '.en{font-size:13px;color:#94A3B8}.note{font-size:13px;color:#64748B;margin-top:10px}.row{margin-top:16px}'
		+ 'button,a{display:inline-block;font:inherit;font-weight:700;border:0;border-radius:12px;padding:12px 20px;cursor:pointer;'
		+ 'background:#0F172A;color:#fff;text-decoration:none}</style></head><body><main class="box">'
		+ '<h1>সংযোগ এক মুহূর্তের জন্য কেটে গিয়েছিল</h1>' + text + '</main>' + script + '</body></html>';
	return new Response(html, { status: 503, headers: { ...HEADERS, 'Content-Type': 'text/html; charset=utf-8' } });
}

function escapeHtml(value: string): string {
	return value.replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch] as string);
}
