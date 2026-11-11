# SellPunch — Cloudflare-এ চালানো (Render থেকে সরানো)

একই Django অ্যাপ Cloudflare Containers-এ চলে। কোড একটাই; `main`-এ push করলে নিজে থেকে নতুন কোড যায়।
ডাটাবেস (Neon) আর ছবি (R2) আগের মতোই, তাই কোনো ডাটা সরাতে হয় না।

```
কাস্টমার ──► Cloudflare Worker (src/index.ts) ──► Django কন্টেইনার (../Dockerfile, gunicorn :8080)
                 │  /static/ Cloudflare cache থেকে              │
                 │  প্রতি ৫ মিনিটে জাগিয়ে রাখে (/healthz/,       └─► Neon Postgres, R2
                 │  ডাটাবেস ছোঁয় না — Neon-এর বিল বাড়ে না)
                 └  রোজ সকাল ১০টায় বাকির অটো-তাগাদা (/internal/cron/daily/)
```

| ফাইল | কাজ |
| --- | --- |
| `../Dockerfile` | Django ইমেজ: requirements, collectstatic, gunicorn |
| `wrangler.jsonc` | Worker, কন্টেইনারের সাইজ (`standard-1`), অঞ্চল (`APAC`), ঠিকানা, cron |
| `src/index.ts` | রিকোয়েস্ট কন্টেইনারে পাঠানো, Secrets → কন্টেইনারের env, static cache, জাগিয়ে রাখা, দৈনিক কাজ |
| `build.sh` | deploy-এর আগে `migrate` (শুধু Build variables-এ `DATABASE_URL` থাকলে) |

কাজটা তিন ভাগে: **ক)** `cf.sellpunch.com`-এ চালু করা (Render-এ কোনো প্রভাব নেই) → **খ)** যাচাই →
**গ)** আসল ঠিকানা `sellpunch.com` আর সব দোকানের সাবডোমেইন Cloudflare-এ নেওয়া।

---

## ক) cf.sellpunch.com-এ চালু করা (৩০–৪০ মিনিট)

1. **Workers Paid চালু** — Cloudflare ড্যাশবোর্ড → Workers & Pages → Plans → **Workers Paid** ($৫/মাস)।
   Billing → Credits-এ Startup Program-এর ক্রেডিট দেখা যাচ্ছে কিনা মিলিয়ে নিন (খরচ সেখান থেকে যাবে)।

2. **রিপো যুক্ত করা** — Workers & Pages → **Create application** → **Import a repository** → GitHub → `Mdmunnaa/sohojsell`।
   - Project name: **`sellpunch`** (wrangler.jsonc-এর `name`-এর সাথে হুবহু মিলতে হবে)
   - Build command: **`bash build.sh`**
   - Deploy command: **`npx wrangler deploy`**
   - Advanced settings → Root directory: **`cloudflare`**
   - Build variables: **এখন কিছু দেবেন না।** (Render-ই এখন ডাটাবেস migrate করছে; দুই জায়গা থেকে একসাথে করলে গোলমাল হয়।
     ধাপ গ-তে দেবেন।)
   - **Deploy** চাপুন। প্রথমবার ৫–১০ মিনিট লাগে। পরে Settings → Build → "Builds for non-production branches" বন্ধ রাখুন।

3. **Secrets দেওয়া** — Worker `sellpunch` → Settings → **Variables and Secrets** → Add → Type: **Secret**।
   Render → sohojsell → Environment থেকে এগুলো **হুবহু একই নাম আর একই মানে** কপি করুন:

   | অবশ্যই | থাকলে |
   | --- | --- |
   | `SECRET_KEY` (একই মান — নাহলে সবাই লগআউট হয়ে যাবে) | `FACEBOOK_APP_SECRET`, `FACEBOOK_LOGIN_CONFIG_ID`, `FACEBOOK_WEBHOOK_VERIFY_TOKEN`, `FACEBOOK_PAGE_URL` |
   | `DATABASE_URL` | `SUPPORT_PHONE`, `SUPPORT_EMAIL`, `SUPPORT_WHATSAPP`, `ADMIN_ALERT_PHONE` |
   | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_PUBLIC_DOMAIN` | `BUSINESS_LEGAL_NAME`, `BUSINESS_ADDRESS`, `SITE_NAME`, `SITE_NAME_BN` |
   | `STORE_BASE_DOMAIN` (= `sellpunch.com`), `SITE_URL` (= `https://sellpunch.com`) | `PAYSTATION_MERCHANT_ID`, `PAYSTATION_PASSWORD`, `PAYSTATION_ENVIRONMENT`, `PAYSTATION_PAY_WITH_CHARGE`, `PAYSTATION_TEST_SHOPS`, `STOREFRONT_PAYMENT_FEE_PERCENT` |
   | `SMS_GATEWAY_CLIENT_ID`, `SMS_GATEWAY_API_KEY` | `STEADFAST_BASE_URL`, `PATHAO_BASE_URL`, `REDX_BASE_URL`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ZONE_ID`, `CUSTOM_DOMAIN_TARGET` |

   **নতুন একটা:** `CRON_SECRET` = যেকোনো ৪০ অক্ষরের এলোমেলো লেখা (পাসওয়ার্ড জেনারেটর দিয়ে বানান)। এটা দিয়ে রোজ বাকির অটো-তাগাদা চলে।

   **দেবেন না:** `DEBUG`, `PRIMARY_HOST`, `KEEP_WARM`, `PORT`, `WEB_CONCURRENCY`, `PYTHON_VERSION`, `DJANGO_SUPERUSER_*`, `RENDER…`।

   সব দেওয়ার পর Deployments → সর্বশেষটা → **Redeploy** (নতুন Secrets কন্টেইনারে যায় নতুন deploy-এ)।

4. ২–৩ মিনিট পর **https://cf.sellpunch.com** খুলুন। প্রথমবার Cloudflare সার্ভার বানাতে কয়েক মিনিট নেয়;
   "There is no Container instance available" দেখালে একটু পরে আবার দেখুন।

## খ) যাচাই (১৫–২০ মিনিট) — সব cf.sellpunch.com-এ

ডাটাবেস একই, তাই এখানে যা করবেন Render-এও দেখা যাবে (আর উল্টোটাও)।

- [ ] নিজের অ্যাকাউন্টে লগইন, ড্যাশবোর্ড খোলে
- [ ] একটা প্রোডাক্ট ছবিসহ যোগ/এডিট (ছবি R2-তে যায়)
- [ ] POS-এ একটা বিক্রি, রসিদ প্রিন্ট পাতা
- [ ] SMS প্যানেল থেকে নিজের নম্বরে **একটা টেস্ট SMS** — যায় কিনা দেখুন (SMS Gateway BD সার্ভারের IP আটকায় কিনা, এটাই একমাত্র উপায় জানার)
- [ ] রিপোর্ট, বাকির খাতা, অর্ডার লিস্ট খোলে
- [ ] পেজ খোলার গতি Render-এর চেয়ে ভালো কিনা
- লগ: Workers & Pages → sellpunch → **Logs** (Worker) আর Containers → sellpunch → **Logs** (Django)

দোকানের ওয়েবসাইট (`demo.sellpunch.com` ইত্যাদি) এই ধাপে এখনো Render থেকে আসে — ওটা ধাপ গ-এর পর যাচাই।
Facebook কানেক্ট আর PayStation পেমেন্টও ধাপ গ-এর পর (ওগুলোতে sellpunch.com ঠিকানা নিবন্ধিত)।

## গ) আসল ঠিকানায় নেওয়া (sellpunch.com + সব দোকানের সাবডোমেইন) — ১৫ মিনিট, প্রায় শূন্য ডাউনটাইম

1. **কোড (আমি করব):** `wrangler.jsonc`-এ routes আর `PRIMARY_HOST` বদল —
   ```jsonc
   "routes": [
     { "pattern": "cf.sellpunch.com", "custom_domain": true },
     { "pattern": "sellpunch.com/*", "zone_name": "sellpunch.com" },
     { "pattern": "www.sellpunch.com/*", "zone_name": "sellpunch.com" },
     { "pattern": "*.sellpunch.com/*", "zone_name": "sellpunch.com" }
   ],
   ...
   "PRIMARY_HOST": "sellpunch.com",
   ```
2. **আপনি, deploy শেষ হওয়ার আগেই:**
   - Worker sellpunch → Settings → Build → **Build variables** → `DATABASE_URL` (Encrypt চাপুন) — এখন থেকে Cloudflare migrate করবে
   - Render → sohojsell → Settings → **Auto-Deploy: Off** — Render এখন থেকে শুধু ব্যাকআপ, নতুন কোড নেবে না
3. **DNS-এ সুইচ:** Cloudflare → sellpunch.com → **DNS → Records**। `sellpunch.com`, `www`, `*` — এই তিনটা রেকর্ডের
   Proxy status **Proxied (কমলা মেঘ)** করুন। কমলা হওয়ার সাথে সাথে ট্রাফিক Cloudflare-এ যায়।
   (আগে থেকেই কমলা থাকলে কিছু করতে হবে না — deploy শেষ হলেই সুইচ হয়ে যায়।)
4. **যাচাই:** sellpunch.com, sellpunch.com/en/, demo.sellpunch.com, একটা দোকানে অর্ডার, অর্ডার ট্র্যাকিং,
   PayStation-এ ছোট একটা টেস্ট পেমেন্ট, Facebook কানেক্ট পাতা।

**কিছু গোলমাল হলে (১ মিনিটে Render-এ ফেরা):**
- রেকর্ডগুলো আগে ধূসর (DNS only) ছিল → আবার **DNS only** করে দিন।
- আগে থেকেই কমলা ছিল → Worker sellpunch → Settings → **Domains & Routes** থেকে `sellpunch.com/*`, `www…`, `*.sellpunch.com/*` মুছুন।

**৭ দিন পর** সব ঠিক থাকলে Render → sohojsell → Settings → **Suspend**।

## খরচ

`standard-1` (১/২ vCPU, 4 GiB) সারাক্ষণ চালু: মোটামুটি মাসে $৩০–৩৫ (Workers Paid-সহ), Startup ক্রেডিট থেকে কাটে।
`instance_type` `"basic"` করলে মোটামুটি $১৩, তবে ধীর। `KEEP_WARM` `"false"` করলে অলস সময়ে ঘুমায়, খরচ কমে,
কিন্তু ঘুম থেকে ওঠার সময় প্রথম কাস্টমারকে কয়েক সেকেন্ড অপেক্ষা করতে হয়।
একদিন পর Billing → Credits-এ "Credit consumed" বাড়লে বুঝবেন খরচ ক্রেডিট থেকে যাচ্ছে।

## অঞ্চল

কন্টেইনার চলে `APAC`-এ। Neon-এর DATABASE_URL-এর হোস্টে `ap-southeast-1` (সিঙ্গাপুর) থাকলে ঠিক আছে।
অন্য অঞ্চল হলে প্রতিটা পেইজ ধীর হবে — তখন Neon প্রজেক্ট সিঙ্গাপুরে নেওয়ার কথা ভাবতে হবে।

## পরে: Premium-এর নিজের ডোমেইন (www.yourshop.com)

Cloudflare for SaaS (Custom Hostnames) লাগবে — Startup Program-এ ইমেইল করে চালু করাতে হয়। তারপর Secrets-এ
`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ZONE_ID`, `CUSTOM_DOMAIN_TARGET` আর routes-এ সব হোস্টের জন্য একটা route।
এখন কোনো দোকান নিজের ডোমেইন Render-এ চালালে Render বন্ধের আগে সেটা সরাতে হবে।

## লোকালি পরীক্ষা

```bash
cd cloudflare && npm install
npm run types && npm run check     # TypeScript + wrangler dry-run (Docker লাগে না)
```
