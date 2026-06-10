// Лёгкий сервер без внешних зависимостей: встроенный http + node:sqlite (Node.js 22+)
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { DatabaseSync } = require('node:sqlite');

const PORT = process.env.PORT || 3000;
const DB_PATH = process.env.DB_PATH || path.join(__dirname, 'lenya.db');
const PUBLIC_DIR = path.join(__dirname, 'public');

// ---------- База данных ----------
const db = new DatabaseSync(DB_PATH);
db.exec(`
  PRAGMA journal_mode = WAL;

  CREATE TABLE IF NOT EXISTS drivers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name   TEXT NOT NULL,
    phone       TEXT NOT NULL DEFAULT '',
    vehicle     TEXT NOT NULL DEFAULT '',
    plate       TEXT NOT NULL DEFAULT '',
    license_cat TEXT NOT NULL DEFAULT '',
    note        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
  );

  CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id   INTEGER NOT NULL REFERENCES drivers(id),
    origin      TEXT NOT NULL,
    destination TEXT NOT NULL,
    cargo       TEXT NOT NULL DEFAULT '',
    date        TEXT NOT NULL DEFAULT '',
    price       TEXT NOT NULL DEFAULT '',
    comment     TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'new', -- new | in_progress | done | cancelled
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
  );
`);

// ---------- Помощники ----------
function json(res, code, data) {
  const body = JSON.stringify(data);
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => {
      data += c;
      if (data.length > 1e6) { reject(new Error('Body too large')); req.destroy(); }
    });
    req.on('end', () => {
      try { resolve(data ? JSON.parse(data) : {}); }
      catch { reject(new Error('Invalid JSON')); }
    });
    req.on('error', reject);
  });
}

const ORDER_STATUSES = ['new', 'in_progress', 'done', 'cancelled'];

// ---------- API ----------
async function handleApi(req, res, url) {
  const parts = url.pathname.split('/').filter(Boolean); // ['api', ...]

  // GET /api/drivers — список водителей (+ количество активных заявок)
  if (req.method === 'GET' && url.pathname === '/api/drivers') {
    const rows = db.prepare(`
      SELECT d.*,
        (SELECT COUNT(*) FROM orders o WHERE o.driver_id = d.id AND o.status IN ('new','in_progress')) AS active_orders
      FROM drivers d ORDER BY d.full_name COLLATE NOCASE
    `).all();
    return json(res, 200, rows);
  }

  // POST /api/drivers — добавить водителя
  if (req.method === 'POST' && url.pathname === '/api/drivers') {
    const b = await readBody(req);
    if (!b.full_name || !String(b.full_name).trim()) {
      return json(res, 400, { error: 'Укажите ФИО водителя' });
    }
    const r = db.prepare(`
      INSERT INTO drivers (full_name, phone, vehicle, plate, license_cat, note)
      VALUES (?, ?, ?, ?, ?, ?)
    `).run(
      String(b.full_name).trim(),
      String(b.phone || '').trim(),
      String(b.vehicle || '').trim(),
      String(b.plate || '').trim(),
      String(b.license_cat || '').trim(),
      String(b.note || '').trim()
    );
    const driver = db.prepare('SELECT * FROM drivers WHERE id = ?').get(r.lastInsertRowid);
    return json(res, 201, driver);
  }

  // PUT /api/drivers/:id — редактировать водителя
  if (req.method === 'PUT' && parts[1] === 'drivers' && parts[2]) {
    const id = Number(parts[2]);
    const existing = db.prepare('SELECT * FROM drivers WHERE id = ?').get(id);
    if (!existing) return json(res, 404, { error: 'Водитель не найден' });
    const b = await readBody(req);
    db.prepare(`
      UPDATE drivers SET full_name=?, phone=?, vehicle=?, plate=?, license_cat=?, note=? WHERE id=?
    `).run(
      String(b.full_name ?? existing.full_name).trim(),
      String(b.phone ?? existing.phone).trim(),
      String(b.vehicle ?? existing.vehicle).trim(),
      String(b.plate ?? existing.plate).trim(),
      String(b.license_cat ?? existing.license_cat).trim(),
      String(b.note ?? existing.note).trim(),
      id
    );
    return json(res, 200, db.prepare('SELECT * FROM drivers WHERE id = ?').get(id));
  }

  // DELETE /api/drivers/:id — удалить водителя (если нет заявок)
  if (req.method === 'DELETE' && parts[1] === 'drivers' && parts[2]) {
    const id = Number(parts[2]);
    const cnt = db.prepare('SELECT COUNT(*) AS c FROM orders WHERE driver_id = ?').get(id);
    if (cnt.c > 0) return json(res, 409, { error: 'У водителя есть заявки — сначала удалите или завершите их' });
    db.prepare('DELETE FROM drivers WHERE id = ?').run(id);
    return json(res, 200, { ok: true });
  }

  // GET /api/orders — список заявок с данными водителя
  if (req.method === 'GET' && url.pathname === '/api/orders') {
    const rows = db.prepare(`
      SELECT o.*, d.full_name AS driver_name, d.phone AS driver_phone,
             d.vehicle AS driver_vehicle, d.plate AS driver_plate
      FROM orders o JOIN drivers d ON d.id = o.driver_id
      ORDER BY o.created_at DESC
    `).all();
    return json(res, 200, rows);
  }

  // POST /api/orders — создать заявку
  if (req.method === 'POST' && url.pathname === '/api/orders') {
    const b = await readBody(req);
    const driver = db.prepare('SELECT * FROM drivers WHERE id = ?').get(Number(b.driver_id));
    if (!driver) return json(res, 400, { error: 'Выберите водителя' });
    if (!b.origin || !b.destination) return json(res, 400, { error: 'Укажите пункты отправления и назначения' });
    const r = db.prepare(`
      INSERT INTO orders (driver_id, origin, destination, cargo, date, price, comment)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(
      driver.id,
      String(b.origin).trim(),
      String(b.destination).trim(),
      String(b.cargo || '').trim(),
      String(b.date || '').trim(),
      String(b.price || '').trim(),
      String(b.comment || '').trim()
    );
    const order = db.prepare('SELECT * FROM orders WHERE id = ?').get(r.lastInsertRowid);
    return json(res, 201, order);
  }

  // PATCH /api/orders/:id/status — сменить статус заявки
  if (req.method === 'PATCH' && parts[1] === 'orders' && parts[2] && parts[3] === 'status') {
    const id = Number(parts[2]);
    const b = await readBody(req);
    if (!ORDER_STATUSES.includes(b.status)) return json(res, 400, { error: 'Неизвестный статус' });
    const r = db.prepare('UPDATE orders SET status = ? WHERE id = ?').run(b.status, id);
    if (r.changes === 0) return json(res, 404, { error: 'Заявка не найдена' });
    return json(res, 200, db.prepare('SELECT * FROM orders WHERE id = ?').get(id));
  }

  // DELETE /api/orders/:id — удалить заявку
  if (req.method === 'DELETE' && parts[1] === 'orders' && parts[2]) {
    const r = db.prepare('DELETE FROM orders WHERE id = ?').run(Number(parts[2]));
    if (r.changes === 0) return json(res, 404, { error: 'Заявка не найдена' });
    return json(res, 200, { ok: true });
  }

  return json(res, 404, { error: 'Не найдено' });
}

// ---------- Статика ----------
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

function serveStatic(req, res, url) {
  let filePath = url.pathname === '/' ? '/index.html' : url.pathname;
  filePath = path.normalize(filePath).replace(/^(\.\.[/\\])+/, '');
  const full = path.join(PUBLIC_DIR, filePath);
  if (!full.startsWith(PUBLIC_DIR)) { res.writeHead(403); return res.end(); }
  fs.readFile(full, (err, data) => {
    if (err) {
      // SPA: всё неизвестное отдаём index.html
      fs.readFile(path.join(PUBLIC_DIR, 'index.html'), (e2, html) => {
        if (e2) { res.writeHead(404); return res.end('Not found'); }
        res.writeHead(200, { 'Content-Type': MIME['.html'] });
        res.end(html);
      });
      return;
    }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(full)] || 'application/octet-stream' });
    res.end(data);
  });
}

// ---------- Сервер ----------
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  try {
    if (url.pathname.startsWith('/api/')) return await handleApi(req, res, url);
    return serveStatic(req, res, url);
  } catch (err) {
    return json(res, 500, { error: err.message });
  }
});

server.listen(PORT, () => {
  console.log(`Lenya запущена: http://localhost:${PORT}`);
  console.log(`База данных: ${DB_PATH}`);
});
