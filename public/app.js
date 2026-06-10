// ============ Утилиты ============
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function initials(name) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');
}

function formatDate(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  return d && m && y ? `${d}.${m}.${y}` : iso;
}

let toastTimer;
function toast(msg, isError = false) {
  const el = $('#toast');
  el.textContent = msg;
  el.className = 'toast' + (isError ? ' error' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 3000);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || 'Ошибка сервера');
  return data;
}

const STATUS_LABELS = {
  new: 'Новая',
  in_progress: 'В работе',
  done: 'Завершена',
  cancelled: 'Отменена',
};

// ============ Роутер ============
const routes = {
  '': renderHome,
  'new-order': renderOrderWizard,
  'new-driver': renderDriverWizard,
  'board': renderBoard,
  'drivers': renderDrivers,
};

function navigate() {
  const hash = location.hash.replace(/^#\/?/, '');
  const route = routes[hash] || renderHome;
  const navKey = hash === '' ? 'home' : hash === 'new-order' || hash === 'new-driver' ? '' : hash;
  $$('.nav a').forEach((a) => a.classList.toggle('active', a.dataset.nav === navKey));
  route();
}

window.addEventListener('hashchange', navigate);
window.addEventListener('DOMContentLoaded', navigate);

function mount(tplId) {
  const app = $('#app');
  app.innerHTML = '';
  app.appendChild($(tplId).content.cloneNode(true));
  return app;
}

// ============ Главная ============
function renderHome() {
  mount('#tpl-home');
}

// ============ Мастер: создание заявки ============
function renderOrderWizard() {
  const app = mount('#tpl-wizard-order');
  const state = {
    driver: null,        // выбранный существующий водитель
    newDriver: null,     // данные нового водителя (если выбрана вкладка "Новый")
    tab: 'existing',
    drivers: [],
  };

  function showStep(n) {
    $$('.wizard-step', app).forEach((s) => s.classList.toggle('hidden', s.dataset.step !== String(n)));
    $$('[data-step-dot]', app).forEach((d) => {
      const num = Number(d.dataset.stepDot);
      const cur = n === 'done' ? 4 : Number(n);
      d.classList.toggle('active', num === cur);
      d.classList.toggle('completed', num < cur);
    });
  }
  showStep(1);

  // --- загрузка водителей ---
  const listEl = $('#driver-list', app);
  api('/api/drivers')
    .then((drivers) => { state.drivers = drivers; renderDriverList(); })
    .catch((e) => toast(e.message, true));

  function renderDriverList() {
    const q = ($('#driver-search', app).value || '').toLowerCase();
    const filtered = state.drivers.filter((d) =>
      [d.full_name, d.vehicle, d.plate, d.phone].join(' ').toLowerCase().includes(q));
    if (!filtered.length) {
      listEl.innerHTML = `<div class="empty-note">${state.drivers.length
        ? 'Никого не нашлось по запросу'
        : 'Водителей пока нет — добавьте нового на соседней вкладке'}</div>`;
      return;
    }
    listEl.innerHTML = filtered.map((d) => `
      <div class="driver-item ${state.driver?.id === d.id ? 'selected' : ''}" data-id="${d.id}">
        <div class="avatar">${esc(initials(d.full_name))}</div>
        <div>
          <div class="d-name">${esc(d.full_name)}</div>
          <div class="d-sub">${esc([d.vehicle, d.plate, d.phone].filter(Boolean).join(' · ') || 'нет данных')}</div>
        </div>
        ${d.active_orders ? `<span class="badge badge-count d-badge">${d.active_orders} акт.</span>` : '<span class="badge badge-free d-badge">свободен</span>'}
      </div>
    `).join('');
    $$('.driver-item', listEl).forEach((el) => el.addEventListener('click', () => {
      state.driver = state.drivers.find((d) => d.id === Number(el.dataset.id));
      renderDriverList();
    }));
  }

  $('#driver-search', app).addEventListener('input', renderDriverList);

  // --- табы ---
  $$('.tab', app).forEach((t) => t.addEventListener('click', () => {
    state.tab = t.dataset.tab;
    $$('.tab', app).forEach((x) => x.classList.toggle('active', x === t));
    $$('.tab-pane', app).forEach((p) => p.classList.toggle('hidden', p.dataset.pane !== state.tab));
  }));

  const val = (name) => ($(`[name="${name}"]`, app)?.value || '').trim();

  // --- шаг 1 → 2 ---
  $('[data-action="step1-next"]', app).addEventListener('click', () => {
    if (state.tab === 'existing') {
      if (!state.driver) return toast('Выберите водителя из списка', true);
      state.newDriver = null;
    } else {
      if (!val('nd_full_name')) {
        $('[name="nd_full_name"]', app).classList.add('invalid');
        return toast('Укажите ФИО нового водителя', true);
      }
      state.newDriver = {
        full_name: val('nd_full_name'),
        phone: val('nd_phone'),
        vehicle: val('nd_vehicle'),
        plate: val('nd_plate'),
      };
      state.driver = null;
    }
    showStep(2);
  });

  // --- шаг 2 ---
  $('[data-action="step2-back"]', app).addEventListener('click', () => showStep(1));
  $('[data-action="step2-next"]', app).addEventListener('click', () => {
    let ok = true;
    for (const f of ['o_origin', 'o_destination']) {
      const input = $(`[name="${f}"]`, app);
      input.classList.toggle('invalid', !input.value.trim());
      if (!input.value.trim()) ok = false;
    }
    if (!ok) return toast('Заполните пункты «Откуда» и «Куда»', true);
    renderSummary();
    showStep(3);
  });

  // --- шаг 3 ---
  function renderSummary() {
    const driverName = state.driver ? state.driver.full_name : `${state.newDriver.full_name} (новый)`;
    const rows = [
      ['Водитель', driverName],
      ['Маршрут', `${val('o_origin')} → ${val('o_destination')}`],
      ['Груз', val('o_cargo') || '—'],
      ['Дата', formatDate(val('o_date')) || '—'],
      ['Оплата', val('o_price') || '—'],
      ['Комментарий', val('o_comment') || '—'],
    ];
    $('#order-summary', app).innerHTML = rows.map(([k, v]) =>
      `<div class="summary-row"><span class="k">${k}</span><span class="v">${esc(v)}</span></div>`).join('');
  }

  $('[data-action="step3-back"]', app).addEventListener('click', () => showStep(2));
  $('[data-action="step3-submit"]', app).addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      let driverId = state.driver?.id;
      if (!driverId) {
        const created = await api('/api/drivers', { method: 'POST', body: state.newDriver });
        driverId = created.id;
      }
      await api('/api/orders', {
        method: 'POST',
        body: {
          driver_id: driverId,
          origin: val('o_origin'),
          destination: val('o_destination'),
          cargo: val('o_cargo'),
          date: val('o_date'),
          price: val('o_price'),
          comment: val('o_comment'),
        },
      });
      $('#done-text', app).textContent =
        `${val('o_origin')} → ${val('o_destination')}, водитель: ${state.driver ? state.driver.full_name : state.newDriver.full_name}`;
      showStep('done');
    } catch (err) {
      toast(err.message, true);
      btn.disabled = false;
    }
  });

  $('[data-action="restart"]', app)?.addEventListener('click', (e) => {
    e.preventDefault();
    renderOrderWizard();
  });
}

// ============ Мастер: добавление водителя ============
function renderDriverWizard() {
  const app = mount('#tpl-wizard-driver');

  function showStep(n) {
    $$('.wizard-step', app).forEach((s) => s.classList.toggle('hidden', s.dataset.step !== String(n)));
    $$('[data-step-dot]', app).forEach((d) => {
      const num = Number(d.dataset.stepDot);
      const cur = n === 'done' ? 4 : Number(n);
      d.classList.toggle('active', num === cur);
      d.classList.toggle('completed', num < cur);
    });
  }
  showStep(1);

  const val = (name) => ($(`[name="${name}"]`, app)?.value || '').trim();

  $('[data-action="d-step1-next"]', app).addEventListener('click', () => {
    if (!val('d_full_name')) {
      $('[name="d_full_name"]', app).classList.add('invalid');
      return toast('Укажите ФИО', true);
    }
    showStep(2);
  });

  $('[data-action="d-step2-back"]', app).addEventListener('click', () => showStep(1));
  $('[data-action="d-step2-next"]', app).addEventListener('click', () => {
    const rows = [
      ['ФИО', val('d_full_name')],
      ['Телефон', val('d_phone') || '—'],
      ['Машина', val('d_vehicle') || '—'],
      ['Госномер', val('d_plate') || '—'],
      ['Категории прав', val('d_license') || '—'],
      ['Заметка', val('d_note') || '—'],
    ];
    $('#driver-summary', app).innerHTML = rows.map(([k, v]) =>
      `<div class="summary-row"><span class="k">${k}</span><span class="v">${esc(v)}</span></div>`).join('');
    showStep(3);
  });

  $('[data-action="d-step3-back"]', app).addEventListener('click', () => showStep(2));
  $('[data-action="d-step3-submit"]', app).addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      await api('/api/drivers', {
        method: 'POST',
        body: {
          full_name: val('d_full_name'),
          phone: val('d_phone'),
          vehicle: val('d_vehicle'),
          plate: val('d_plate'),
          license_cat: val('d_license'),
          note: val('d_note'),
        },
      });
      $('#d-done-text', app).textContent = val('d_full_name');
      showStep('done');
    } catch (err) {
      toast(err.message, true);
      btn.disabled = false;
    }
  });
}

// ============ Доска ============
function renderBoard() {
  const app = mount('#tpl-board');
  let filter = 'active';

  $$('.chip', app).forEach((c) => c.addEventListener('click', () => {
    filter = c.dataset.filter;
    $$('.chip', app).forEach((x) => x.classList.toggle('active', x === c));
    load();
  }));

  async function load() {
    try {
      const [drivers, orders] = await Promise.all([api('/api/drivers'), api('/api/orders')]);
      draw(drivers, orders);
    } catch (e) {
      toast(e.message, true);
    }
  }

  function draw(drivers, orders) {
    const boardEl = $('#board', app);
    if (!drivers.length) {
      boardEl.innerHTML = `<div class="empty-note">Пока пусто. <a href="#/new-driver">Добавьте первого водителя</a></div>`;
      return;
    }
    boardEl.innerHTML = drivers.map((d) => {
      let dOrders = orders.filter((o) => o.driver_id === d.id);
      if (filter === 'active') dOrders = dOrders.filter((o) => o.status === 'new' || o.status === 'in_progress');
      const activeCount = orders.filter((o) => o.driver_id === d.id && (o.status === 'new' || o.status === 'in_progress')).length;
      return `
        <div class="driver-card">
          <div class="driver-card-head">
            <div class="avatar">${esc(initials(d.full_name))}</div>
            <div>
              <div class="d-name">${esc(d.full_name)}</div>
              <div class="d-sub">${esc([d.vehicle, d.plate].filter(Boolean).join(' · ') || 'машина не указана')}</div>
            </div>
            ${activeCount
              ? `<span class="badge badge-count">${activeCount} акт.</span>`
              : '<span class="badge badge-free">свободен</span>'}
          </div>
          <div class="order-cards">
            ${dOrders.length ? dOrders.map(orderCard).join('') : '<div class="no-orders">Нет заявок</div>'}
          </div>
        </div>`;
    }).join('');

    // смена статуса
    $$('.status-select', boardEl).forEach((sel) => sel.addEventListener('change', async () => {
      try {
        await api(`/api/orders/${sel.dataset.id}/status`, { method: 'PATCH', body: { status: sel.value } });
        toast(`Статус: ${STATUS_LABELS[sel.value]}`);
        load();
      } catch (e) { toast(e.message, true); }
    }));

    // удаление заявки
    $$('[data-del-order]', boardEl).forEach((btn) => btn.addEventListener('click', async () => {
      if (!confirm('Удалить заявку?')) return;
      try {
        await api(`/api/orders/${btn.dataset.delOrder}`, { method: 'DELETE' });
        toast('Заявка удалена');
        load();
      } catch (e) { toast(e.message, true); }
    }));
  }

  function orderCard(o) {
    const meta = [o.cargo, formatDate(o.date), o.price].filter(Boolean).join(' · ');
    return `
      <div class="order-card status-${o.status}">
        <div class="order-route">${esc(o.origin)} → ${esc(o.destination)}</div>
        ${meta ? `<div class="order-meta">${esc(meta)}</div>` : ''}
        ${o.comment ? `<div class="order-meta">💬 ${esc(o.comment)}</div>` : ''}
        <div class="order-foot">
          <span class="status-pill pill-${o.status}">${STATUS_LABELS[o.status]}</span>
          <select class="status-select" data-id="${o.id}">
            ${Object.entries(STATUS_LABELS).map(([v, l]) =>
              `<option value="${v}" ${v === o.status ? 'selected' : ''}>${l}</option>`).join('')}
          </select>
          <button class="icon-btn" data-del-order="${o.id}" title="Удалить заявку">🗑</button>
        </div>
      </div>`;
  }

  load();
}

// ============ Список водителей ============
function renderDrivers() {
  const app = mount('#tpl-drivers');

  async function load() {
    try {
      const drivers = await api('/api/drivers');
      draw(drivers);
    } catch (e) {
      toast(e.message, true);
    }
  }

  function draw(drivers) {
    const el = $('#drivers-table', app);
    if (!drivers.length) {
      el.innerHTML = `<div class="empty-note">Водителей пока нет. <a href="#/new-driver">Добавить первого</a></div>`;
      return;
    }
    el.innerHTML = drivers.map((d) => `
      <div class="driver-row">
        <div class="avatar">${esc(initials(d.full_name))}</div>
        <div class="d-info">
          <div class="d-name">${esc(d.full_name)}</div>
          <div class="d-sub">${esc([d.phone, d.vehicle, d.plate, d.license_cat && `права: ${d.license_cat}`]
            .filter(Boolean).join(' · ') || 'нет данных')}</div>
          ${d.note ? `<div class="d-sub">📝 ${esc(d.note)}</div>` : ''}
        </div>
        ${d.active_orders
          ? `<span class="badge badge-count">${d.active_orders} акт.</span>`
          : '<span class="badge badge-free">свободен</span>'}
        <div class="d-actions">
          <button class="btn btn-ghost btn-sm" data-del="${d.id}">Удалить</button>
        </div>
      </div>
    `).join('');

    $$('[data-del]', el).forEach((btn) => btn.addEventListener('click', async () => {
      if (!confirm('Удалить водителя?')) return;
      try {
        await api(`/api/drivers/${btn.dataset.del}`, { method: 'DELETE' });
        toast('Водитель удалён');
        load();
      } catch (e) { toast(e.message, true); }
    }));
  }

  load();
}
