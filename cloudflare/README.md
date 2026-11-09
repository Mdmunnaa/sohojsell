# SellPunch — Cloudflare Containers-এ চালানো

একই Django অ্যাপ Cloudflare-এ চলে, Render-এর পাশাপাশি। কোড একটাই; `main`-এ push করলে
Render আর Cloudflare দুটোই নিজে থেকে নতুন কোড নেয়। ডাটাবেস (Neon) আর ছবি (R2) দুই জায়গাতেই এক।

```
কাস্টমার ──► Cloudflare Worker (src/index.ts) ──► Django কন্টেইনার (../Dockerfile, gunicorn :8080)
                 │  /static/ Cloudflare cache থেকে              │
                 │  প্রতি ৫ মিনিটে জাগিয়ে রাখে (KEEP_WARM)       └─► Neon Postgres, R2
```

| ফাইল | কাজ |
| --- | --- |
| `../Dockerfile` | Django ইমেজ: requirements, collectstatic, gunicorn |
| `wrangler.jsonc` | Worker, কন্টেইনারের সাইজ (`standard-1`), অঞ্চল (`APAC`), ঠিকানা (`cf.sellpunch.com`), cron |
| `src/index.ts` | রিকোয়েস্ট কন্টেইনারে পাঠানো, Secrets → কন্টেইনারের env, static cache, জাগিয়ে রাখা |
| `build.sh` | প্রতি deploy-এর আগে `migrate` (Build variables-এ `DATABASE_URL` লাগে) |

## প্রথমবার সেটআপ (Cloudflare ড্যাশবোর্ডে)

1. **Workers Paid চালু করুন** — Workers & Pages → Plans → Workers Paid ($৫/মাস, Startup ক্রেডিট থেকে যায়)।
2. **রিপো যুক্ত করুন** — Workers & Pages → Create application → GitHub → `Mdmunnaa/sohojsell` বেছে নিন।
   - Project name: `sellpunch` (wrangler.jsonc-এর `name`-এর সাথে মিলতে হবে)
   - Build command: `bash build.sh`
   - Deploy command: `npx wrangler deploy`
   - Root directory (Advanced settings): `cloudflare`
   - Build variables: `DATABASE_URL` = Render-এর DATABASE_URL (Encrypt চাপুন)
   - তারপর Deploy। প্রথম build-এ ৫–১০ মিনিট লাগতে পারে।
3. **Secrets দিন** — Worker `sellpunch` → Settings → Variables and Secrets → Add।
   Render → Environment-এ যত Key আছে (SECRET_KEY, DATABASE_URL, R2_…, PAYSTATION_…, FACEBOOK_…, SITE_URL ইত্যাদি)
   সবগুলো একই নাম আর মানে **Type: Secret** দিয়ে বসান। `DEBUG`, `PRIMARY_HOST`, `KEEP_WARM` দেবেন না।
   এখানে দেওয়া সব লেখা কন্টেইনারে environment variable হয়ে যায়।
4. ২–৩ মিনিট পর **https://cf.sellpunch.com** খুলুন। প্রথমবার Cloudflare সার্ভার বানাতে কয়েক মিনিট নেয়;
   "There is no Container instance available" দেখালে একটু পরে আবার দেখুন।

## যাচাই

- লগইন, ড্যাশবোর্ড, দোকানের সাইট (`/shop/<নাম>/`), প্রোডাক্ট যোগ (ছবিসহ) — সব Render-এর মতো চলবে।
  ডাটাবেস একই, তাই এখানে যা করবেন Render-এও দেখা যাবে।
- **ক্রেডিট:** একদিন পর Billing → Credits-এ "Credit consumed" বাড়লে বুঝবেন খরচ ক্রেডিট থেকে যাচ্ছে।
  Billable usage-এ Containers-এর লাইন দেখা যাবে।
- **অঞ্চল:** Neon-এর DATABASE_URL-এর হোস্টে `ap-southeast-1` (সিঙ্গাপুর) থাকলে ঠিক আছে।
  অন্য অঞ্চল হলে wrangler.jsonc-এর `constraints.regions` বদলাতে হবে, নাহলে প্রতিটা পেইজ ধীর হবে।
- লগ: Workers & Pages → Containers → sellpunch → Logs।

## খরচ (ক্রেডিট শেষ হলে যা লাগবে)

`standard-1` (১/২ vCPU, 4 GiB) সারাক্ষণ চালু: Cloudflare-এর রেটে মোটামুটি মাসে $৩০–৩৫ (Workers Paid-সহ)।
`instance_type` `"basic"` করলে মোটামুটি $১৩, তবে ধীর। `KEEP_WARM` `"false"` করলে অলস সময়ে ঘুমায়, খরচ কমে,
কিন্তু ঘুম থেকে ওঠার সময় প্রথম কাস্টমারকে কয়েক সেকেন্ড অপেক্ষা করতে হয়।

## পরে: আসল ডোমেইনে নেওয়া (sellpunch.com আর দোকানের সাবডোমেইন)

টেস্ট ঠিক থাকলে: `routes`-এ `sellpunch.com`, `www.sellpunch.com` (custom domain) আর `*.sellpunch.com/*` (zone route),
`PRIMARY_HOST` = `sellpunch.com`, Secrets-এ `STORE_BASE_DOMAIN` = `sellpunch.com`, তারপর DNS Render থেকে সরানো।
Premium-এর নিজের ডোমেইনের জন্য Cloudflare "SSL for SaaS" (Startup Program-এ ইমেইল করে চালু করতে হয়)।

## লোকালি পরীক্ষা

```bash
cd cloudflare && npm install
npm run types && npm run check     # TypeScript + wrangler dry-run (Docker লাগে না)
```
