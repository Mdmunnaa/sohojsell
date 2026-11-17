/* SellPunch অ্যাপ — service worker (store/views_app.service_worker, ঠিকানা /sw.js — পুরো সাইট এর আওতায়)।
 * কাজ:
 *   - POS পাতা: আগে নেট (৭ সেকেন্ড), না পেলে শেষবার নেট থাকার সময়ের কপি — নেট ছাড়াও বিক্রি চলে
 *   - /app/ (হোম স্ক্রিনের আইকন): নেট না থাকলে সোজা POS-এ
 *   - অন্য পাতা: সবসময় নেট থেকে; নেট না থাকলে "নেট নেই" পাতা, সাথে POS খোলার বোতাম
 *   - /static/-এর CSS, JS, ফন্ট আর লোগো: ডিভাইসে থাকলে সেখান থেকে, নাহলে নেট থেকে এনে রেখে দেয় (ছবি রাখে না)
 *   - API, বিক্রি জমা, ফর্ম পাঠানো (POST): কখনো ধরা বা জমা রাখা হয় না, সরাসরি নেট
 * বিক্রি জমা রাখা আর পরে পাঠানো POS পাতার নিজের কাজ (templates/store/pos.html) — এখানে কোনো বিক্রি বা টাকার তথ্য নেই।
 */
const VERSION = '{{ version }}';
const PRECACHE = {{ precache|safe }};
const POS_URL = '{{ pos_url }}';
const APP_URL = '{{ app_url }}';
const MARK = {{ mark|safe }};
const NETWORK_FIRST = {{ network_first|yesno:'true,false' }};   // লোকালে (DEBUG) ফাইলের নামে hash নেই — তখন আগে নেট
{% verbatim %}
const PAGES = 'sp-pos-pages';                 // লগইন পাতা খুললে মুছে যায় (অন্য কেউ লগইন করলে আগের দোকানের পাতা না থাকে)
const STATIC = 'sp-app-static-' + VERSION;
const PAGE_WAIT = 7000;
const KEEP = /\.(css|js|woff2?|ttf|svg|png|ico)$/i;   // ডিভাইসে রাখার মতো ফাইল (ছবি/স্ক্রিনশট না)

function isPosPage(res) {
  return !!res && res.ok && !res.redirected && res.type === 'basic'
    && (res.headers.get('content-type') || '').indexOf('text/html') >= 0;
}

function sameStatic(url) {
  let parsed;
  try { parsed = new URL(url, self.location.origin); } catch (e) { return null; }
  if (parsed.origin !== self.location.origin || parsed.pathname.indexOf('/static/') !== 0) return null;
  return parsed;
}

async function keepFiles(urls) {
  const cache = await caches.open(STATIC);
  for (const url of urls.slice(0, 200)) {
    const parsed = sameStatic(url);
    if (!parsed || !KEEP.test(parsed.pathname) || await cache.match(parsed.href)) continue;
    try {
      const res = await fetch(parsed.href, { credentials: 'same-origin' });
      if (res.ok) await cache.put(parsed.href, res);
    } catch (e) { /* পরে আবার */ }
  }
}

// POS পাতা রাখার সময় তার CSS/JS-ও রাখা — নেট ছাড়া খুললে যেন পুরো পাতা ঠিকঠাক আসে
async function keepPage(res) {
  const copy = res.clone();
  await (await caches.open(PAGES)).put(POS_URL, res);
  const html = await copy.text();
  const found = [];
  const re = /(?:href|src)="(\/static\/[^"#?]+)"/g;
  let m;
  while ((m = re.exec(html)) !== null) found.push(m[1]);
  await keepFiles(found);
}

async function savePage() {
  try {
    const res = await fetch(POS_URL, { credentials: 'include', cache: 'no-store' });
    if (isPosPage(res)) await keepPage(res);
  } catch (e) { /* নেট নেই — পরে পাতা খুললে রাখা হবে */ }
}

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(STATIC);
    await Promise.all(PRECACHE.map((url) => cache.add(url).catch(() => null)));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.indexOf('sp-app-static-') === 0 && key !== STATIC) await caches.delete(key);
    }
    // পাতা খোলার অনুরোধ আর service worker চালু হওয়া একসাথে — অ্যাপ ধীর হয় না
    if (self.registration.navigationPreload) await self.registration.navigationPreload.enable().catch(() => null);
    await self.clients.claim();
  })());
});

// POS পাতা থেকে: এখন যে ফাইলগুলো লাগছে সেগুলো রেখে দাও (প্রথমবার পাতা খোলার সময় service worker তখনো চালু ছিল না)
self.addEventListener('message', (event) => {
  const data = event.data || {};
  if (data.type === 'cache' && Array.isArray(data.urls)) {
    event.waitUntil((async () => {
      await keepFiles(data.urls);
      if (data.page) await savePage();
    })());
  }
});

function timeout(ms) { return new Promise((resolve) => setTimeout(() => resolve(null), ms)); }

async function fromNetwork(event) {
  const pre = await event.preloadResponse;
  return pre || fetch(event.request);
}

async function hasPos() {
  return !!(await (await caches.open(PAGES)).match(POS_URL));
}

function posPage(event) {
  let saving = Promise.resolve();
  const network = fromNetwork(event).then((res) => {
    if (isPosPage(res)) saving = keepPage(res.clone()).catch(() => null);
    return res;
  }).catch(() => null);
  event.waitUntil(network.then(() => saving));
  return (async () => {
    const saved = await (await caches.open(PAGES)).match(POS_URL);
    if (!saved) return (await network) || offlinePage(false);
    const res = await Promise.race([network, timeout(PAGE_WAIT)]);
    // নেট নেই, খুব ধীর, বা সার্ভারে সমস্যা — আগের কপি থেকে POS চলুক
    if (!res || res.status >= 500) return saved;
    return res;
  })();
}

// হোম স্ক্রিনের আইকন: নেট থাকলে সার্ভার ঠিক করে কোথায় যাবে; না থাকলে POS (নেট ছাড়া শুধু ওটাই চলে)
async function appStart(event) {
  const pos = await hasPos();
  try {
    const res = await Promise.race([fromNetwork(event), timeout(pos ? PAGE_WAIT : 60000)]);
    if (res && res.status < 500) return res;
  } catch (e) { /* নেট নেই */ }
  return pos ? Response.redirect(POS_URL, 302) : offlinePage(false);
}

async function otherPage(event) {
  try {
    return await fromNetwork(event);
  } catch (e) {
    return offlinePage(await hasPos());
  }
}

function offlinePage(pos) {
  const html = '<!doctype html><html lang="bn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    + '<meta name="theme-color" content="#F0F2F6"><title>নেট নেই</title><style>'
    + 'body{font-family:"Hind Siliguri",system-ui,sans-serif;background:#F0F2F6;color:#0F172A;display:flex;min-height:100vh;'
    + 'align-items:center;justify-content:center;margin:0;padding:16px;box-sizing:border-box}'
    + '.box{max-width:420px;width:100%;background:#fff;border:1px solid #E2E8F0;border-radius:20px;padding:28px 22px;text-align:center}'
    + 'img{width:52px;height:52px;margin-bottom:10px}h1{font-size:21px;margin:0 0 8px}p{color:#475569;line-height:1.7;margin:0}'
    + '.row{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:18px}'
    + 'a,button{font:inherit;font-weight:700;border-radius:12px;padding:12px 20px;text-decoration:none;cursor:pointer;border:0}'
    + '.go{background:#059669;color:#fff}.again{background:#F1F5F9;color:#0F172A;border:1px solid #E2E8F0}</style></head>'
    + '<body><div class="box"><img src="' + MARK + '" alt=""><h1>নেট নেই</h1><p>এই পাতা খুলতে নেট লাগবে। নেট ছাড়া শুধু POS চলে — '
    + (pos ? 'POS-এ বিক্রি চালিয়ে যান, নেট এলে নিজে থেকে জমা হবে।' : 'তার জন্য POS আগে একবার নেট থাকা অবস্থায় খুলতে হয়।')
    + '</p><div class="row">' + (pos ? '<a class="go" href="' + POS_URL + '">POS খুলুন</a>' : '')
    + '<button class="again" type="button" onclick="location.reload()">আবার চেষ্টা করুন</button></div></div></body></html>';
  return new Response(html, { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
}

async function staticFile(request) {
  const cache = await caches.open(STATIC);
  const hit = await cache.match(request, { ignoreVary: true });
  if (hit && !NETWORK_FIRST) return hit;          // নামে hash আছে, তাই ফাইল বদলালে নামও বদলায়
  try {
    const res = await fetch(request);
    if (res.ok && res.type === 'basic') await cache.put(request, res.clone());
    return res;
  } catch (e) {
    return hit || new Response('', { status: 504 });
  }
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    if (url.pathname === POS_URL) event.respondWith(posPage(event));
    else if (url.pathname === APP_URL) event.respondWith(appStart(event));
    else event.respondWith(otherPage(event));
    return;
  }
  if (url.pathname.indexOf('/static/') === 0 && KEEP.test(url.pathname)) event.respondWith(staticFile(request));
});
{% endverbatim %}
