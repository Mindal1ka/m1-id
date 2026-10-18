/**
 * M1 ID — production static server (zero deps).
 * Віддає build/ (adapter-static output) з правильними кеш-заголовками:
 *   /version.json, /sw.js  -> no-store (система оновлень має бачити істину)
 *   /_app/immutable/*      -> immutable 1y
 *   усе інше               -> no-cache (перевалідація)
 * SPA-фолбек: невідомий шлях без розширення -> app.html (PWA-роути).
 *   index.html — пререндерений лендінг '/': його віддаємо лише на '/',
 *   усе інше без розширення — SPA-шелл app.html.
 * /api/v1/files/* (короткі посилання M1 Provider) проксюється на бекенд
 * 127.0.0.1:4174. Решта /api/* не проксюється: фронт ходить на
 * mapi.<домен> (VITE_API_URL у .env).
 * Запуск: node scripts/serve.mjs [порт=4173]
 */
import http from 'node:http';
import { createReadStream, existsSync, statSync } from 'node:fs';
import { extname, join, normalize, resolve, sep } from 'node:path';

const PORT = Number(process.argv[2] || process.env.M1ID_FRONT_PORT || 4173);
const DOMAIN = process.env.M1ID_DOMAIN || 'm1id.xyz';
const ROOT = resolve(process.cwd(), 'build');
const API_HOST = '127.0.0.1';
const API_PORT = Number(process.env.M1ID_BACKEND_PORT || 4174);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.mjs': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.webmanifest': 'application/manifest+json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.txt': 'text/plain',
  '.xml': 'application/xml',
  '.map': 'application/json',
  '.wasm': 'application/wasm'
};

const server = http.createServer((req, res) => {
  let url;
  try {
    url = new URL(req.url, 'http://x');
  } catch {
    res.writeHead(400);
    return res.end('bad request');
  }

  // --- ЛИШЕ /api/v1/files/* → бекенд (4174): короткі посилання M1 Provider.
  // (mapi не переписує filename ДЗ, якщо шлях схожий на його файловий
  // патерн — але хост у нас m1id.xyz, тому шлях обслуговуємо ми).
  // Решта /api/* фронт сюди НЕ шле: він стукає на mapi.<домен>.
  if (url.pathname.startsWith('/api/v1/files/')) {
    const upstream = http.request(
      {
        host: API_HOST,
        port: API_PORT,
        path: url.pathname + url.search,
        method: req.method,
        headers: { ...req.headers, host: `${API_HOST}:${API_PORT}` }
      },
      (up) => {
        res.writeHead(up.statusCode, up.headers);
        up.pipe(res);
      }
    );
    upstream.on('error', () => {
      if (!res.headersSent) {
        res.writeHead(502, { 'content-type': 'application/json; charset=utf-8' });
      }
      res.end(JSON.stringify({ ok: false, data: null, meta: null, error: [{ code: 'backend_unreachable', message: 'backend is not reachable', field: '__all__' }] }));
    });
    req.pipe(upstream);
    return;
  }

  // --- статика з build/ ---
  const rel = normalize(decodeURIComponent(url.pathname)).replace(/^([/\\])+/, '');
  const filePath = resolve(join(ROOT, rel));
  // ROOT + sep: голий prefix-чек «startsWith(ROOT)» пропускав би
  // сусідній каталог виду C:\...\build2 (..-трюк через resolve)
  if (filePath !== ROOT && !filePath.startsWith(ROOT + sep)) {
    res.writeHead(403);
    return res.end('forbidden');
  }

  let file = filePath;
  try {
    if (existsSync(file) && statSync(file).isDirectory()) file = join(file, 'index.html');
    if (!existsSync(file) || !statSync(file).isFile()) {
      // SPA fallback: шлях без розширення -> app.html (SPA-шелл).
      // index.html НЕ використовуємо: це пререндерений лендінг '/',
      // гідратація лендінгу на чужому шляху ламає роутер.
      if (!extname(rel)) file = join(ROOT, 'app.html');
      else {
        res.writeHead(404);
        return res.end('not found');
      }
    }
  } catch {
    res.writeHead(404);
    return res.end('not found');
  }

  const ext = extname(file).toLowerCase();
  const headers = { 'Content-Type': MIME[ext] || 'application/octet-stream' };
  const normRel = rel.split('\\').join('/');
  if (rel === 'version.json' || rel === 'sw.js') {
    headers['Cache-Control'] = 'no-store'; // система оновлень мусить бачити істину
  } else if (rel.includes(`_app${sep}`) && rel.includes(`${sep}immutable${sep}`)) {
    headers['Cache-Control'] = 'public, max-age=31536000, immutable';
  } else {
    headers['Cache-Control'] = 'no-cache';
  }
  res.writeHead(200, headers);
  createReadStream(file).pipe(res);
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[M1 ID] static server on https://${DOMAIN}  ->  http://0.0.0.0:${PORT}  root=${ROOT}`);
});
