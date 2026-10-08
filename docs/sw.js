// BEWON app shell: নেটওয়ার্ক আগে, না পেলে সেভ করা কপি
const CACHE = "bewon-v24";
self.addEventListener("install", e => { self.skipWaiting(); e.waitUntil(caches.open(CACHE).then(c => c.addAll(["./", "./index.html"]))); });
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || /\.(mp4|pdf)$/.test(u.pathname)) return;
  e.respondWith(fetch(e.request).then(r => { if (r.ok && !u.pathname.includes("/data/")) { const c = r.clone(); caches.open(CACHE).then(x => x.put(e.request, c)); } return r; })
    .catch(() => caches.match(e.request).then(r => r || caches.match("./index.html"))));
});
