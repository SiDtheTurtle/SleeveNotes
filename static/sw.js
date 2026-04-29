const CACHE = 'sn-v1';
const SHELL = ['/', '/manifest.json', '/icon.svg', '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Health endpoint must always hit the network — it's used for reachability detection
  if (url.pathname === '/api/health') return;

  // Cache read-only data endpoints (network-first, cache fallback)
  const CACHED_DATA = ['/api/records', '/api/wishlist', '/api/settings', '/api/masters/', '/api/release/'];
  if (e.request.method === 'GET' && CACHED_DATA.some(p => url.pathname.startsWith(p))) {
    e.respondWith(
      fetch(e.request).then(resp => {
        if (resp.ok) { const clone = resp.clone(); caches.open(CACHE).then(c => c.put(e.request, clone)); }
        return resp;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // Never cache other API calls (mutations, Discogs fetches, etc.)
  if (url.pathname.startsWith('/api/')) return;

  // Cache-first for images served by the backend
  if (url.pathname.startsWith('/images/')) {
    e.respondWith(
      caches.open(CACHE).then(async cache => {
        const cached = await cache.match(e.request);
        if (cached) return cached;
        const resp = await fetch(e.request);
        if (resp.ok) cache.put(e.request, resp.clone());
        return resp;
      })
    );
    return;
  }

  // Network-first for everything else (app shell) with cache fallback
  e.respondWith(
    fetch(e.request)
      .then(resp => {
        if (resp.ok) { const clone = resp.clone(); caches.open(CACHE).then(c => c.put(e.request, clone)); }
        return resp;
      })
      .catch(() => caches.match(e.request))
  );
});

// Background Sync — flush offline wishlist queue (Android Chrome only)
self.addEventListener('sync', e => {
  if (e.tag === 'wishlist-sync') e.waitUntil(flushOfflineQueue());
});

function openSwDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('sn_offline', 3);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains('wishlist_queue'))
        db.createObjectStore('wishlist_queue', { keyPath: 'idb_key', autoIncrement: true });
      if (!db.objectStoreNames.contains('wishlist_updates'))
        db.createObjectStore('wishlist_updates', { keyPath: 'wishlist_id' });
      if (!db.objectStoreNames.contains('version_queue'))
        db.createObjectStore('version_queue', { keyPath: 'idb_key', autoIncrement: true });
      if (!db.objectStoreNames.contains('version_removes'))
        db.createObjectStore('version_removes', { keyPath: 'record_id' });
      if (!db.objectStoreNames.contains('version_fulfillments'))
        db.createObjectStore('version_fulfillments', { keyPath: 'record_id' });
    };
    req.onsuccess = e => resolve(e.target.result);
    req.onerror = reject;
  });
}

function swGetAll(db, store) {
  return new Promise((resolve, reject) => {
    const req = db.transaction(store, 'readonly').objectStore(store).getAll();
    req.onsuccess = e => resolve(e.target.result);
    req.onerror = reject;
  });
}

function swDelete(db, store, key) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite');
    tx.objectStore(store).delete(key);
    tx.oncomplete = resolve;
    tx.onerror = reject;
  });
}

async function flushOfflineQueue() {
  try {
    const db = await openSwDB();

    for (const item of await swGetAll(db, 'wishlist_queue')) {
      try {
        const r = await fetch('/api/wishlist', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ master_id: item.master_id, notes: item.notes || '' }),
        });
        if (r.ok || r.status === 409) await swDelete(db, 'wishlist_queue', item.idb_key);
      } catch { /* retry on next sync */ }
    }

    for (const upd of await swGetAll(db, 'wishlist_updates')) {
      try {
        const r = await fetch(`/api/wishlist/${upd.wishlist_id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ notes: upd.notes, fulfilled: upd.fulfilled }),
        });
        if (r.ok) await swDelete(db, 'wishlist_updates', upd.wishlist_id);
      } catch { /* retry on next sync */ }
    }

    // Version adds must run before removes/fulfillments
    for (const item of await swGetAll(db, 'version_queue')) {
      try {
        const r = await fetch(`/api/wishlist/${item.wishlist_id}/versions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ discogs_id: item.discogs_id }),
        });
        if (r.ok || r.status === 409) await swDelete(db, 'version_queue', item.idb_key);
      } catch { /* retry on next sync */ }
    }

    for (const item of await swGetAll(db, 'version_removes')) {
      try {
        const r = await fetch(`/api/wishlist/versions/${item.record_id}`, { method: 'DELETE' });
        if (r.ok) await swDelete(db, 'version_removes', item.record_id);
      } catch { /* retry on next sync */ }
    }

    for (const item of await swGetAll(db, 'version_fulfillments')) {
      try {
        const fr = await fetch(`/api/wishlist/versions/${item.record_id}/fulfill`, { method: 'POST' });
        if (!fr.ok) continue;
        if (item.details && Object.keys(item.details).length) {
          await fetch(`/api/records/${item.record_id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(item.details),
          });
        }
        await swDelete(db, 'version_fulfillments', item.record_id);
      } catch { /* retry on next sync */ }
    }
  } catch { /* IDB unavailable */ }
}
