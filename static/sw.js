// Offline UPI Service Worker — 100% Offline PWA Engine
const CACHE_NAME = 'offline-upi-v8';

const STATIC_PRECACHE = [
  '/',
  '/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  'https://cdn.tailwindcss.com',
  'https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js',
  'https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js',
  'https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.min.js',
  'https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js'
];

// 1. Install Event: Cache Core App Shell & Skip Waiting Immediately
self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[SW] Pre-caching offline-upi-v8 app shell');
      return Promise.allSettled(
        STATIC_PRECACHE.map((url) =>
          cache.add(url).catch((err) => console.warn(`[SW] Precache failed for ${url}:`, err))
        )
      );
    })
  );
});

// 2. Activate Event: Claim All Clients Immediately & Purge Old Stale Caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            console.log('[SW] Purging old cache version:', key);
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// 3. Fetch Event: Network-First for HTML/Navigations with 1.2s Timeout, Cache-First for Assets
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Handle API calls when offline
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(req).catch(() => {
        if (req.method === 'GET' && url.pathname === '/api/state') {
          return new Response(
            JSON.stringify({
              offline: true,
              message: "Device in Offline Mode (Local Cache Active)",
              accounts: [],
              transactions: [],
              mesh: { devices: {} }
            }),
            { headers: { 'Content-Type': 'application/json' } }
          );
        }
        return new Response(
            JSON.stringify({
            offline: true,
            success: false,
            error: "Device is offline. Handled by on-device local storage."
          }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        );
      })
    );
    return;
  }

  // Handle Navigation (HTML Page) Requests: Fast Race with 1.2s timeout against Cache
  if (req.mode === 'navigate' || req.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      new Promise((resolve) => {
        let resolved = false;

        // Fast fallback to cache after 1200ms if serverless is cold-starting
        const timer = setTimeout(async () => {
          if (!resolved) {
            const cached = await caches.match('/') || await caches.match(req);
            if (cached) {
              resolved = true;
              resolve(cached);
            }
          }
        }, 1200);

        fetch(req)
          .then((networkRes) => {
            clearTimeout(timer);
            if (networkRes && networkRes.status === 200) {
              const resClone = networkRes.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put('/', resClone));
            }
            if (!resolved) {
              resolved = true;
              resolve(networkRes);
            }
          })
          .catch(async () => {
            clearTimeout(timer);
            if (!resolved) {
              resolved = true;
              const cached = await caches.match('/') || await caches.match(req);
              resolve(cached || new Response('Offline', { status: 503 }));
            }
          });
      })
    );
    return;
  }

  // Handle Static Assets & CDNs: Cache-First with Network Fallback
  event.respondWith(
    caches.match(req).then((cachedRes) => {
      if (cachedRes) {
        return cachedRes;
      }
      return fetch(req)
        .then((networkRes) => {
          if (networkRes && networkRes.status === 200 && req.method === 'GET') {
            const resClone = networkRes.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, resClone));
          }
          return networkRes;
        })
        .catch(() => {
          return new Response('', { status: 408 });
        });
    })
  );
});
