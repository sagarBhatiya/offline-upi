// UPI Lite Service Worker — 100% Offline PWA Engine
const CACHE_NAME = 'upi-lite-offline-v2';

const STATIC_PRECACHE = [
  '/',
  '/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  'https://cdn.tailwindcss.com',
  'https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js',
  'https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.min.js',
  'https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js'
];

// 1. Install Event: Cache Core App Shell
self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[SW] Pre-caching offline app shell');
      // Cache files individually with catch so failures on external CDNs don't abort entire install
      return Promise.allSettled(
        STATIC_PRECACHE.map((url) =>
          cache.add(url).catch((err) => console.warn(`[SW] Precache failed for ${url}:`, err))
        )
      );
    })
  );
});

// 2. Activate Event: Claim Clients & Purge Stale Caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            console.log('[SW] Deleting stale cache:', key);
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// 3. Fetch Event: Cache-First for Assets, Network-First for App Shell, Offline Fallbacks for API
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Handle API calls when completely offline
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(req).catch(() => {
        console.warn(`[SW] Network offline, providing fallback for ${url.pathname}`);
        if (req.method === 'GET' && url.pathname === '/api/state') {
          // Return simulated offline state from cache or empty fallback
          return new Response(
            JSON.stringify({
              offline: true,
              message: "Device in 100% Offline Mode (Local Cache Active)",
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

  // Handle Navigation (HTML Page) Requests: Stale-While-Revalidate with Cache Fallback
  if (req.mode === 'navigate' || req.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      fetch(req)
        .then((networkRes) => {
          if (networkRes && networkRes.status === 200) {
            const resClone = networkRes.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put('/', resClone));
          }
          return networkRes;
        })
        .catch(() => {
          return caches.match('/') || caches.match(req);
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
          console.warn(`[SW] Asset fetch failed while offline: ${req.url}`);
          return new Response('', { status: 408 });
        });
    })
  );
});
