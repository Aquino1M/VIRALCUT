const CACHE='viralclip-shell-v55';
const SHELL=['/static/style.css','/static/shell.js','/static/editor.js','/static/manifest.webmanifest'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL).catch(()=>{}))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener('fetch',event=>{if(event.request.method!=='GET')return;const url=new URL(event.request.url);if(url.origin!==location.origin)return;if(url.pathname.startsWith('/static/'))event.respondWith(fetch(event.request).then(resp=>{const copy=resp.clone();caches.open(CACHE).then(c=>c.put(event.request,copy));return resp}).catch(()=>caches.match(event.request)));});
