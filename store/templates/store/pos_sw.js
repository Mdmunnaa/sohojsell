/* SellPunch অফলাইন POS — service worker (store/views_pos.pos_sw)।
 * কাজ: নেট না থাকলেও POS-এর পাতা আর ফাইল (CSS, JS, ফন্ট, আইকন, স্ক্যানার) ডিভাইস থেকে খোলা।
 * বিক্রি জমা রাখা আর পরে পাঠানো পাতার নিজের কাজ (templates/store/pos.html) — এখানে কোনো বিক্রি বা টাকার তথ্য নেই।
 *   - POS পাতা: আগে নেট (৭ সেকেন্ড), না পেলে শেষবার নেট থাকার সময়ের কপি
 *   - /static/ ফাইল: ডিভাইসে থাকলে সেখান থেকে, নাহলে নেট থেকে এনে রেখে দেয়
 *   - অন্য সব (API, বিক্রি জমা): সরাসরি নেট — কখনো জমা রাখা হয় না
 */
const VERSION = '{{ version }}';
const PRECACHE = {{ precache|safe }};
const POS_URL = '{{ pos_url }}';
const NETWORK_FIRST = {{ network_first|yesno:'true,false' }};   // লোকালে (DEBUG) ফাইলের নামে hash নেই — তখন আগে নেট
{% verbatim %}
const PAGES = 'sp-pos-pages';                 // লগইন পাতা খুললে মুছে যায় (অন্য কেউ লগইন করলে আগের দোকানের পাতা না থাকে)
const STATIC = 'sp-pos-static-' + VERSION;
const PAGE_WAIT = 7000;

function isPosPage(res) {
  return !!res && res.ok && !res.redirected && res.type === 'basic'
    && (res.headers.get('content-type') || '').indexOf('text/html') >= 0;
}

async function savePage() {
  try {
    const res = await fetch(POS_URL, { credentials: 'include', cache: 'no-store' });
    if (isPosPage(res)) await (await caches.open(PAGES)).put(POS_URL, res);
  } catch (e) { /* নেট নেই — পরে পাতা খুললে রাখা হবে */ }
}

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(STATIC);
    await Promise.all(PRECACHE.map((url) => cache.add(url).catch(() => null)));
    await savePage();
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.indexOf('sp-pos-static-') === 0 && key !== STATIC) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

// পাতা থেকে: এখন যে ফাইলগুলো লাগছে সেগুলো রেখে দাও (প্রথমবার পাতা খোলার সময় service worker তখনো চালু ছিল না)
self.addEventListener('message', (event) => {
  const data = event.data || {};
  if (data.type === 'cache' && Array.isArray(data.urls)) {
    event.waitUntil((async () => {
      const cache = await caches.open(STATIC);
      for (const url of data.urls.slice(0, 200)) {
        let parsed;
        try { parsed = new URL(url, self.location.origin); } catch (e) { continue; }
        if (parsed.origin !== self.location.origin || parsed.pathname.indexOf('/static/') !== 0) continue;
        if (await cache.match(parsed.href)) continue;
        try {
          const res = await fetch(parsed.href, { credentials: 'same-origin' });
          if (res.ok) await cache.put(parsed.href, res);
        } catch (e) { /* পরে আবার */ }
      }
      if (data.page) await savePage();
    })());
  }
});

function timeout(ms) { return new Promise((resolve) => setTimeout(() => resolve(null), ms)); }

async function posPage(request) {
  const cache = await caches.open(PAGES);
  const network = fetch(request).then(async (res) => {
    if (isPosPage(res)) await cache.put(POS_URL, res.clone());
    return res;
  }).catch(() => null);
  const saved = await cache.match(POS_URL);
  if (!saved) return (await network) || offlinePage(false);
  const res = await Promise.race([network, timeout(PAGE_WAIT)]);
  // নেট নেই, খুব ধীর, বা সার্ভারে সমস্যা — আগের কপি থেকে POS চলুক
  if (!res || res.status >= 500) return saved;
  return res;
}

function offlinePage(hasPos) {
  const html = '<!doctype html><html lang="bn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    + '<title>নেট নেই</title><style>body{font-family:system-ui,sans-serif;background:#F8FAFC;color:#0F172A;display:flex;'
    + 'min-height:100vh;align-items:center;justify-content:center;margin:0;padding:16px}div{max-width:420px;background:#fff;'
    + 'border:1px solid #E2E8F0;border-radius:18px;padding:24px;text-align:center}a{display:inline-block;margin-top:14px;'
    + 'background:#059669;color:#fff;border-radius:12px;padding:12px 20px;font-weight:700;text-decoration:none}</style></head>'
    + '<body><div><h2>নেট নেই</h2><p>নেট ছাড়া শুধু POS চলে। '
    + (hasPos ? 'POS খুলে বিক্রি চালিয়ে যান — নেট এলে নিজে থেকে জমা হবে।' : 'POS আগে একবার নেট থাকা অবস্থায় খুলতে হয়।')
    + '</p><a href="' + POS_URL + '">POS খুলুন</a></div></body></html>';
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
    if (url.pathname === POS_URL) { event.respondWith(posPage(request)); return; }
    if (url.pathname.indexOf(POS_URL) === 0) {
      event.respondWith(fetch(request).catch(async () => offlinePage(!!(await (await caches.open(PAGES)).match(POS_URL)))));
    }
    return;
  }
  if (url.pathname.indexOf('/static/') === 0) event.respondWith(staticFile(request));
});
{% endverbatim %}
