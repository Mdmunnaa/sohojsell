/**
 * SellPunch — Cloudflare Worker
 *
 * সব রিকোয়েস্ট একটা Django কন্টেইনারে (SellPunchApp) পাঠায়।
 * - ড্যাশবোর্ডের Variables & Secrets-এ যা দেবেন (SECRET_KEY, DATABASE_URL, R2_... ইত্যাদি),
 *   সব কন্টেইনারে environment variable হিসেবে যায়।
 * - /static/ ফাইল Cloudflare-এর cache-এ রাখে, তাই সেগুলোর জন্য কন্টেইনার খাটে না।
 * - KEEP_WARM = "true" হলে প্রতি ৫ মিনিটে একবার সাড়া নেয়, তাই সার্ভার ঘুমায় না।
 * - দিনে একবার (সকাল ১০টা, বাংলাদেশ) /internal/cron/daily/ — বাকির অটো-তাগাদা। Secrets-এ CRON_SECRET লাগে।
 * - *.sellpunch.com-এর সব ঠিকানা এই Worker-এ আসে; ছবির ডোমেইন (R2_PUBLIC_DOMAIN) আর PASS_THROUGH_HOSTS-এর
 *   ঠিকানাগুলো Django-তে না পাঠিয়ে সরাসরি নিজের জায়গায় যায়।
 * - মূল ঠিকানা একটাই (PRIMARY_HOST): www.sellpunch.com আর cf.sellpunch.com সেখানে পাঠিয়ে দেয় (Google-এ দুই কপি না)।
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

/** সরাসরি Cloudflare-এ ঢোকার ঠিকানা — মূল ঠিকানা অন্য হলে সেখানে পাঠিয়ে দেয় */
const DIRECT_HOST = 'cf.sellpunch.com';

function hostOf(value: string): string {
	return value.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/[/:].*$/, '');
}

/** যেসব ঠিকানা Django-র না (যেমন R2-এর ছবির ডোমেইন media.sellpunch.com) — Secrets থেকে */
function passThroughHosts(vars: Record<string, unknown>): Set<string> {
	const hosts = new Set<string>();
	for (const value of [vars.R2_PUBLIC_DOMAIN, vars.PASS_THROUGH_HOSTS]) {
		if (typeof value !== 'string') continue;
		for (const part of value.split(',')) {
			const host = hostOf(part);
			if (host) hosts.add(host);
		}
	}
	return hosts;
}

// wrangler.jsonc-এর triggers.crons-এর সাথে হুবহু মিলতে হবে
const DAILY_CRON = '0 4 * * *'; // ০৪:০০ UTC = সকাল ১০টা বাংলাদেশ

/** সব ট্রাফিক একটা কন্টেইনারে। পরে বেশি লাগলে getRandom(env.APP, N) দিয়ে ভাগ করা যাবে। */
function app(env: Env) {
	return getContainer(env.APP, 'main');
}

export default {
	async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
		const url = new URL(request.url);
		const vars = env as unknown as Record<string, unknown>;
		const host = url.hostname.toLowerCase();

		// ছবির ডোমেইন ইত্যাদি: Worker থেকে একই zone-এর ঠিকানায় fetch সরাসরি আসল জায়গায় যায় (এই Worker-এ ফেরে না)
		if (passThroughHosts(vars).has(host)) return fetch(request);

		// www.sellpunch.com আর (পুরোপুরি সরানোর পর) cf.sellpunch.com → sellpunch.com
		const primary = typeof vars.PRIMARY_HOST === 'string' ? hostOf(vars.PRIMARY_HOST) : '';
		if (primary && host !== primary && (host === `www.${primary}` || host === DIRECT_HOST)) {
			const target = `https://${primary}${url.pathname}${url.search}`;
			return Response.redirect(target, request.method === 'GET' || request.method === 'HEAD' ? 301 : 308);
		}

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

	async scheduled(controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
		const vars = env as unknown as Record<string, string | undefined>;
		const host = vars.PRIMARY_HOST || 'localhost';

		if (controller.cron === DAILY_CRON) {
			const secret = vars.CRON_SECRET;
			if (!secret) {
				console.log('daily cron: Secrets-এ CRON_SECRET নেই, তাই বাদ');
				return;
			}
			ctx.waitUntil(
				app(env)
					.fetch(
						new Request(`https://${host}/internal/cron/daily/`, {
							method: 'POST',
							headers: { 'X-Forwarded-Proto': 'https', 'X-Cron-Secret': secret },
						}),
					)
					.then(async (res) => console.log('daily cron', res.status, await res.text())),
			);
			return;
		}

		if ((vars.KEEP_WARM ?? 'true') !== 'true') return;
		ctx.waitUntil(
			app(env)
				.fetch(new Request(`https://${host}/healthz/`, { headers: { 'X-Forwarded-Proto': 'https' } }))
				.then((res) => res.body?.cancel()),
		);
	},
} satisfies ExportedHandler<Env>;
