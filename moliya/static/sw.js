/* Mfaktor Moliya — service worker.
   Strategiya:
   • Sahifalar (HTML): network-first — moliya ma'lumoti doim yangi bo'lishi shart;
     tarmoq yo'q bo'lsa keshdagi oxirgi nusxa, u ham bo'lmasa offline sahifa.
   • Statika (ikonka, shrift): cache-first — tez ochilish.
   POST so'rovlar keshlan MAYDI. */
const VER = "mf-v2";
const STATIC_CACHE = VER + "-static";
const PAGE_CACHE = VER + "-pages";
const OFFLINE_URL = "/static/offline.html";
const PRECACHE = [
  OFFLINE_URL,
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(STATIC_CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => !k.startsWith(VER)).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;               // POST/DELETE — faqat tarmoq
  const url = new URL(req.url);

  // Sahifa navigatsiyasi: network-first
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(PAGE_CACHE).then((c) => c.put(req, copy));
          return res;
        })
        .catch(() =>
          caches.match(req).then((hit) => hit || caches.match(OFFLINE_URL))
        )
    );
    return;
  }

  // Statika va shriftlar: cache-first
  if (url.pathname.startsWith("/static/") ||
      url.hostname.endsWith("gstatic.com") ||
      url.hostname.endsWith("googleapis.com")) {
    e.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(STATIC_CACHE).then((c) => c.put(req, copy));
            }
            return res;
          })
      )
    );
  }
});
