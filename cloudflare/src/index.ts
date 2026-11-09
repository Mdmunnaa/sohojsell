/**
 * SellPunch — Cloudflare Worker
 *
 * সব রিকোয়েস্ট একটা Django কন্টেইনারে (SellPunchApp) পাঠায়।
 * - ড্যাশবোর্ডের Variables & Secrets-এ যা দেবেন (SECRET_KEY, DATABASE_URL, R2_... ইত্যাদি),
 *   সব কন্টেইনারে environment variable হিসেবে যায়।
 * - /static/ ফাইল Cloudflare-এর cache-এ রাখে, তাই সেগুলোর জন্য কন্টেইনার খাটে না।
 * - KEEP_WARM = "true" হলে প্রতি ৫ মিনিটে একবার সাড়া নেয়, তাই সার্ভার ঘুমায় না।
 */
import { Container, getContainer } from '@cloudflare/containers';

// Env টাইপ wrangler.jsonc থেকে বানানো (npm run types → worker-configuration.d.ts)

/** Worker-এর লেখা (string) মানগুলো কন্টেইনারের env; বাইন্ডিং (APP ইত্যাদি) বাদ। */
function appEnv(env: Env): Record<string, string> {
	const vars: Record<string, string> = { DEBUG: '0' };
	for (const [name, value] of Object.entries(env as unknown as Record<string, unknown>)) {
		if (typeof value === 'string') vars[name] = value;
	}
	vars.PORT = '8080';
	return vars;
}

export class SellPunchApp extends Container<Env> {
	defaultPort = 8080;
	// কোনো রিকোয়েস্ট না এলে ১৫ মিনিট পর ঘুমায় (KEEP_WARM চালু থাকলে ঘুমায় না)
	sleepAfter = '15m';
	// চালু হয়েছে কিনা এই ঠিকানায় দেখে (Django-র /healthz/, ডাটাবেস ছোঁয় না)
	pingEndpoint = 'localhost/healthz/';
	envVars = appEnv(this.env);
}

/** সব ট্রাফিক একটা কন্টেইনারে। পরে বেশি লাগলে getRandom(env.APP, N) দিয়ে ভাগ করা যাবে। */
function app(env: Env) {
	return getContainer(env.APP, 'main');
}

export default {
	async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
		const url = new URL(request.url);

		// Django যেন বোঝে রিকোয়েস্ট https আর কাস্টমারের আসল IP কোনটা
		const headers = new Headers(request.headers);
		headers.set('X-Forwarded-Proto', url.protocol.replace(':', ''));
		headers.set('X-Forwarded-Host', url.host);
		const ip = request.headers.get('CF-Connecting-IP');
		if (ip) headers.set('X-Forwarded-For', ip);
		const forwarded = new Request(request, { headers });

		// /static/ (CSS, JS, লোগো): নামেই সংস্করণ থাকে, তাই Cloudflare-এর cache থেকে দেওয়া নিরাপদ
		const cacheable = request.method === 'GET' && url.pathname.startsWith('/static/');
		if (cacheable) {
			const cached = await caches.default.match(request);
			if (cached) return cached;
		}

		const response = await app(env).fetch(forwarded);

		if (cacheable && response.status === 200) {
			ctx.waitUntil(caches.default.put(request, response.clone()));
		}
		return response;
	},

	async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
		const vars = env as unknown as Record<string, string | undefined>;
		if ((vars.KEEP_WARM ?? 'true') !== 'true') return;
		const host = vars.PRIMARY_HOST || 'localhost';
		ctx.waitUntil(
			app(env)
				.fetch(new Request(`https://${host}/healthz/`, { headers: { 'X-Forwarded-Proto': 'https' } }))
				.then((res) => res.body?.cancel()),
		);
	},
} satisfies ExportedHandler<Env>;
