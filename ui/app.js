'use strict';

const $ = (id) => document.getElementById(id);
const nf = (d) => new Intl.NumberFormat('fa-IR', { maximumFractionDigits: d });
const fa = (n, d = 0) => (n === null || n === undefined ? '—' : nf(d).format(n));
// A sign before Persian digits flips inside RTL text; LRI...PDI keeps it in place.
const ltr = (s) => '⁦' + s + '⁩';
const percent = (v) => fa(v) + '٪';
const ICONS = {
  handle: '<svg viewBox="0 0 24 24"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>',
  remove: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  bell: '<svg class="bell" viewBox="0 0 24 24" aria-label="هشدار دارد"><path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0"/></svg>',
};
const SPARK_EVERY = 5 * 60 * 1000;  // how often the line behind a row is fetched again
const RADIUS = 14;        // .widget border-radius, in design pixels
const DETAIL_IDLE_MS = 45000;  // a chart left alone this long goes back to the list

let api = null;
let cfg = null;
let current = null;   // last state from Python
let view = 'list';    // list | settings | detail
let hover = false;    // the mouse is over the window (Python tells us, see setHover)
let collapsed = false;
let scale = 1;
let rowIds = null;
const nodes = {};

function digitsFor(price) {
  if (price >= 1000) return 0;
  if (price >= 1) return 2;
  return 4;
}

// ---------------------------------------------------------------- price rows

function rowParts(li) {
  const part = (cls) => { const d = document.createElement('div'); d.className = cls; li.append(d); return d; };
  return { li, name: part('name'), price: part('price'), when: part('when'), change: part('change'), prev: {} };
}

function fillRow(n, row) {
  n.name.textContent = row.label;
  if (current.alerts[row.id]) n.name.insertAdjacentHTML('beforeend', ICONS.bell);
  n.li.classList.toggle('alerted', (current.alerted[row.id] ?? Infinity) < 60);
  drawSpark(n, row.id);
  const q = row.quote;
  n.li.classList.toggle('stale', !!(q && q.ok && q.stale));
  n.li.classList.toggle('quiet', !!(q && q.ok && q.stale && /:/.test(q.source_time)));
  if (!q || !q.ok) {
    n.price.innerHTML = '<span class="missing">در دسترس نیست</span>';
    n.change.textContent = '';
    n.when.textContent = q ? '' : 'در حال دریافت…';
    return;
  }
  n.price.textContent = fa(q.price, digitsFor(q.price));
  const unit = document.createElement('span');
  unit.className = 'unit';
  unit.textContent = row.unit;
  n.price.append(unit);

  const prev = n.prev[row.id];
  if (prev !== undefined && q.price !== prev) {
    // Flash green/red at once, then fade back: removing the class restores the transition.
    n.price.classList.remove('flash-up', 'flash-down');
    void n.price.offsetWidth;
    n.price.classList.add(q.price > prev ? 'flash-up' : 'flash-down');
    clearTimeout(n.timer);
    n.timer = setTimeout(() => n.price.classList.remove('flash-up', 'flash-down'), 700);
  }
  n.prev[row.id] = q.price;

  if (q.note) {  // a derived row says what its number means instead of a daily change
    n.change.className = 'change note';
    n.change.textContent = q.note;
    n.when.textContent = q.when;
    return;
  }
  const c = q.change_pct || 0;
  n.change.className = 'change' + (c > 0 ? ' up' : c < 0 ? ' down' : '');
  n.change.textContent = (c > 0 ? '▲ ' : c < 0 ? '▼ ' : '') + ltr(fa(Math.abs(c), 2) + '٪') + ' امروز';
  // tgju labels a closing price with its date and a live one with its time.
  n.when.textContent = row.source === 'nobitex' ? 'نوبیتکس، زنده'
    : (/:/.test(q.source_time) ? 'tgju، ساعت ' : 'tgju، بسته‌ی ') + q.source_time;
}

function buildRow(row) {
  const li = document.createElement('li');
  li.className = 'row';
  li.title = 'نمودار ' + row.label;
  // The list also drags the window: a press that moved the mouse is a drag, not a click.
  let down = null;
  li.addEventListener('mousedown', (e) => { down = [e.screenX, e.screenY]; });
  li.addEventListener('click', (e) => {
    if (down && Math.abs(e.screenX - down[0]) + Math.abs(e.screenY - down[1]) > 4) return;
    openDetail(row.id);
  });
  $('rows').append(li);
  return rowParts(li);
}

function render(state) {
  current = state;
  document.documentElement.style.setProperty('--font', `'${state.font}'`);
  const ids = state.rows.map((r) => r.id).join('|');
  if (ids !== rowIds) {  // rows were added, removed or reordered: rebuild the list
    rowIds = ids;
    $('rows').textContent = '';
    for (const id of Object.keys(nodes)) delete nodes[id];
    storyIndex = 0;
    $('segs').textContent = '';
  }
  for (const row of state.rows) fillRow(nodes[row.id] || (nodes[row.id] = buildRow(row)), row);
  renderStory(false);
  if (view === 'detail') renderDetailQuote();

  const fresh = state.status.nobitex.t ? state.now - state.status.nobitex.t : null;
  const stale = fresh === null || fresh > 30;
  $('live').classList.toggle('stale', stale);
  $('age').classList.toggle('stale', stale);
  $('age').textContent = fresh === null ? '' : fresh < 2 ? 'همین حالا' : fa(Math.floor(fresh)) + ' ثانیه پیش';
  const errors = Object.entries(state.status).filter(([, s]) => s.error).map(([k]) => k === 'tgju' ? 'tgju' : 'نوبیتکس');
  $('foot').textContent = errors.length ? 'اتصال به ' + errors.join(' و ') + ' برقرار نشد. VPN خاموش است؟' : '';

  $('onTop').checked = state.on_top;
  $('compact').checked = state.compact;
  $('bare').checked = !state.background;
  $('autostart').checked = state.autostart;
  $('locked').checked = state.locked;
  // pywebview drags the window by whatever carries this class; a locked widget has none.
  for (const id of ['head', 'rows']) $(id).classList.toggle('pywebview-drag-region', !state.locked);
  $('dockBtn').disabled = state.docked;
  $('dockBtn').textContent = state.docked ? 'کنار ساعت است' : 'بردن کنار ساعت';
  applyMode();
}

async function tick() {
  try {
    render(await api.state());
  } catch (err) {
    $('foot').textContent = String(err);
  }
  fitWindow();
}

// --------------------------------------------- what is on screen, and how big

// Called from Python (see Api._hover_loop) when the mouse arrives or leaves.
function setHover(on) {
  hover = !!on;
  if (!current) return;  // still starting up: the first render picks the value up
  clearTimeout(setHover.timer);
  if (!hover && view === 'detail') setHover.timer = setTimeout(closeDetail, DETAIL_IDLE_MS);
  applyMode();
  fitWindow();
}

function applyMode() {
  if (!current) return;
  const idle = !hover && view === 'list';
  const was = collapsed;
  collapsed = idle && current.compact && current.rows.length > 0;
  document.body.classList.toggle('bare', idle && !current.background);

  const show = (id, on) => { $(id).hidden = !on; };
  const list = view === 'list' && !collapsed;
  show('head', !collapsed);
  show('grip', !collapsed && !current.locked);
  show('rows', list);
  show('empty', list && current.rows.length === 0);
  show('foot', list && $('foot').textContent !== '');
  show('story', collapsed);
  show('detail', view === 'detail');
  show('settings', view === 'settings');
  for (const id of ['live', 'age', 'refreshBtn', 'settingsBtn', 'closeBtn']) show(id, view === 'list');
  show('doneBtn', view === 'settings');
  show('backBtn', view === 'detail');
  if (view !== 'detail') $('title').textContent = view === 'settings' ? 'تنظیمات' : 'قیمت لحظه‌ای';

  if (collapsed && !was) startStory();
  if (!collapsed && was) clearInterval(storyTimer);
}

function setView(next) {
  view = next;
  api.set_view(view);
  applyMode();
  fitWindow();
}

// Zoom the widget to the chosen scale, less if it would not fit the screen, then make the
// window exactly that big, whatever the OS did to the size last asked for.
let fitting = false;
let fitAgain = false;
let keepRight = false;  // resizing by the left edge: the right edge must not move
let lastRadius = -1;
async function fitWindow() {
  if (fitting) { fitAgain = true; return; }
  fitting = true;
  try {
    const widget = $('widget');
    widget.style.zoom = scale;
    const room = window.screen.availHeight - 24;
    const tall = widget.getBoundingClientRect().height;
    let zoom = scale;
    if (tall > room) widget.style.zoom = zoom = Math.floor(scale * room / tall * 100) / 100;
    const box = widget.getBoundingClientRect();
    const dw = Math.ceil(box.width) - window.innerWidth;
    const dh = Math.ceil(box.height) - window.innerHeight;
    const radius = Math.round(RADIUS * zoom);
    // Too small by a pixel clips the border; too big by a pixel is invisible.
    if (dw > 0 || dw < -1 || dh > 0 || dh < -1 || radius !== lastRadius) {
      lastRadius = radius;
      await api.fit(dw, dh, radius, keepRight);
    }
  } finally {
    fitting = false;
  }
  if (fitAgain) { fitAgain = false; fitWindow(); }
}

// Resize with the mouse: drag the left edge, or Ctrl + wheel.
function clampScale(v) {
  return Math.round(Math.min(cfg.scale[1], Math.max(cfg.scale[0], v)) * 100) / 100;
}

function bindResize() {
  const grip = $('grip');
  grip.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    grip.setPointerCapture(e.pointerId);
    grip.classList.add('on');
    api.hold(true);
    keepRight = true;
    const right = window.screenX + window.innerWidth;  // stays put while the left edge moves
    const move = (ev) => { scale = clampScale((right - ev.screenX) / 300); fitWindow(); };
    const up = async () => {
      grip.removeEventListener('pointermove', move);
      grip.classList.remove('on');
      scale = await api.set_scale(scale);
      await fitWindow();
      keepRight = false;
      api.hold(false);
    };
    grip.addEventListener('pointermove', move);
    grip.addEventListener('pointerup', up, { once: true });
  });
  window.addEventListener('wheel', async (e) => {
    if (!e.ctrlKey || e.deltaY === 0 || current.locked) return;
    e.preventDefault();
    scale = await api.set_scale(clampScale(scale + (e.deltaY < 0 ? 0.05 : -0.05)));
    $('scale').value = Math.round(scale * 100);
    $('scaleOut').textContent = percent($('scale').value);
    fitWindow();
  }, { passive: false });
}

// --------------------------------------------------------------------- story

let storyIndex = 0;
let storyTimer = 0;
let storyNodes = null;

function renderStory(animate) {
  const rows = current.rows;
  if (!rows.length) return;
  storyIndex %= rows.length;
  if (!storyNodes) storyNodes = rowParts($('storyRow'));
  fillRow(storyNodes, rows[storyIndex]);
  const segs = $('segs');
  if (animate || segs.children.length !== rows.length) {
    // Rebuilt on every step so the fill animation of the current bar starts over.
    segs.textContent = '';
    rows.forEach((_, i) => {
      const seg = document.createElement('i');
      seg.className = i < storyIndex ? 'past' : i === storyIndex ? 'now' : '';
      segs.append(seg);
    });
  }
  if (animate) {
    const li = $('storyRow');
    li.classList.remove('swap');
    void li.offsetWidth;
    li.classList.add('swap');
  }
}

function startStory() {
  clearInterval(storyTimer);
  const ms = current.story_seconds * 1000;
  $('segs').style.setProperty('--story', ms + 'ms');
  renderStory(true);
  storyTimer = setInterval(() => { storyIndex += 1; renderStory(true); }, ms);
}

// ------------------------------------------------------------------ sparkline

const sparks = {};  // row id -> {at, values}
let sparkQueue = Promise.resolve();

function drawSpark(n, id) {
  const s = sparks[id];
  if (!s || Date.now() - s.at > SPARK_EVERY) {
    if (!s || !s.loading) loadSpark(id);
  }
  if (!s || !s.values) {  // nothing (yet) for this row; the story row may still show another's
    if (n.spark) { n.spark.remove(); n.spark = null; n.sparkFor = null; }
    return;
  }
  if (n.sparkFor === s) return;
  n.sparkFor = s;  // drawn once per fetch, not on every tick
  const v = s.values, lo = Math.min(...v), hi = Math.max(...v);
  const x = (i) => (i / (v.length - 1) * 100).toFixed(2);
  const y = (val) => (hi === lo ? 50 : 4 + (hi - val) / (hi - lo) * 92).toFixed(2);
  const line = v.map((val, i) => (i ? 'L' : 'M') + x(i) + ' ' + y(val)).join('');
  if (!n.spark) {
    n.spark = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    n.spark.setAttribute('viewBox', '0 0 100 100');
    n.spark.setAttribute('preserveAspectRatio', 'none');
    n.spark.setAttribute('aria-hidden', 'true');
    n.li.prepend(n.spark);
  }
  n.spark.setAttribute('class', 'spark ' + (v[v.length - 1] >= v[0] ? 'up' : 'down'));
  n.spark.innerHTML = `<path class="a" d="${line}L100 100L0 100Z"/><path class="l" d="${line}"/>`;
}

// One at a time: each tgju line is a whole series download the first time.
function loadSpark(id) {
  const row = current.rows.find((r) => r.id === id);
  if (!row || !row.ranges.length) { sparks[id] = { at: Date.now() }; return; }
  sparks[id] = Object.assign(sparks[id] || {}, { loading: true });
  sparkQueue = sparkQueue.then(async () => {
    let answer = {};
    try { answer = await api.spark(row.source, row.key); } catch (err) { /* no line then */ }
    sparks[id] = { at: Date.now(), values: answer.values };
  });
}

// --------------------------------------------------------------------- chart

let detailId = null;
let detailRange = null;
let detailPoints = null;
let detailToken = 0;
const dateFormat = (options) => new Intl.DateTimeFormat('fa-IR', options);

function detailRow() {
  return current.rows.find((r) => r.id === detailId) || null;
}

function renderDetailQuote() {
  const row = detailRow();
  if (!row) { closeDetail(); return; }
  const q = row.quote;
  $('title').textContent = row.label;
  $('dPrice').textContent = q && q.ok ? fa(q.price, digitsFor(q.price)) : '—';
  $('dUnit').textContent = row.unit;
}

function openDetail(id) {
  detailId = id;
  const row = detailRow();
  if (!row) return;
  const ids = row.ranges.map((r) => r[0]);
  if (!ids.includes(detailRange)) detailRange = ids.includes('1d') ? '1d' : ids[0];
  $('chartBox').hidden = !ids.length;
  $('noChart').hidden = !!ids.length;
  showAlert(row);
  const tabs = $('dTabs');
  tabs.textContent = '';
  for (const [rid, name] of row.ranges) {
    const b = document.createElement('button');
    b.setAttribute('role', 'tab');
    b.dataset.range = rid;
    b.textContent = name;
    b.addEventListener('click', () => { detailRange = rid; loadChart(); });
    tabs.append(b);
  }
  renderDetailQuote();
  setView('detail');
  if (ids.length) loadChart();
}

function closeDetail() {
  if (view !== 'detail') return;
  detailToken += 1;
  setView('list');
}

function chartNote(text, retry) {
  $('chartNote').hidden = !text;
  $('chartText').textContent = text || '';
  $('retryBtn').hidden = !retry;
}

async function loadChart() {
  const row = detailRow();
  if (!row) return;
  const token = ++detailToken;
  for (const b of $('dTabs').children) b.setAttribute('aria-selected', b.dataset.range === detailRange);
  detailPoints = null;
  $('tip').hidden = true;
  $('chart').className = 'chart loading';
  $('dDelta').textContent = '';
  $('dDelta').className = 'delta';
  for (const id of ['dLow', 'dHigh']) $(id).textContent = '—';
  for (const id of ['dFrom', 'dTo']) $(id).textContent = '';
  chartNote('در حال دریافت نمودار…', false);
  let answer;
  try {
    answer = await api.history(row.source, row.key, detailRange);
  } catch (err) {
    answer = { error: 'connection' };
  }
  if (token !== detailToken) return;  // another range or row was chosen meanwhile
  $('chart').className = 'chart';
  if (answer.error) {
    $('plot').textContent = '';
    chartNote(answer.error === 'empty' ? 'برای این بازه داده‌ای نیست. بازه‌ی دیگری را امتحان کن.'
      : 'نمودار دریافت نشد. VPN خاموش است؟', answer.error !== 'empty');
    return;
  }
  chartNote('', false);
  drawChart(answer.points, row);
}

const W = 276, H = 140, TOP = 8, BOTTOM = 8;

function drawChart(points, row) {
  detailPoints = points;
  const values = points.map((p) => p[1]);
  const lo = Math.min(...values), hi = Math.max(...values);
  const t0 = points[0][0], t1 = points[points.length - 1][0];
  const x = (t) => (t1 === t0 ? W / 2 : (t - t0) / (t1 - t0) * W);
  const y = (v) => (hi === lo ? H / 2 : TOP + (hi - v) / (hi - lo) * (H - TOP - BOTTOM));
  const path = points.map((p, i) => (i ? 'L' : 'M') + x(p[0]).toFixed(1) + ' ' + y(p[1]).toFixed(1)).join('');
  const first = values[0], lastValue = values[values.length - 1];
  const rising = lastValue >= first;
  $('chart').classList.add(rising ? 'up' : 'down');
  $('plot').innerHTML =
    '<defs><linearGradient id="shade" x1="0" y1="0" x2="0" y2="1">' +
    '<stop offset="0" stop-color="currentColor" stop-opacity=".28"/>' +
    '<stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>' +
    `<line class="guide" x1="0" x2="${W}" y1="${y(hi)}" y2="${y(hi)}"/>` +
    `<line class="guide" x1="0" x2="${W}" y1="${y(lo)}" y2="${y(lo)}"/>` +
    `<path fill="url(#shade)" d="${path}L${W} ${H}L0 ${H}Z"/>` +
    `<path class="line" d="${path}"/>` +
    '<line class="cross" id="cross" y1="0" y2="' + H + '" visibility="hidden"/>';

  const digits = digitsFor(hi);
  $('dLow').textContent = fa(lo, digits);
  $('dHigh').textContent = fa(hi, digits);
  const pct = first ? (lastValue - first) / first * 100 : 0;
  const name = row.ranges.find((r) => r[0] === detailRange)[1];
  $('dDelta').className = 'delta' + (pct > 0 ? ' up' : pct < 0 ? ' down' : '');
  $('dDelta').textContent = (pct > 0 ? '▲ ' : pct < 0 ? '▼ ' : '') + ltr(fa(Math.abs(pct), 2) + '٪') +
    ' (' + ltr((lastValue > first ? '+' : lastValue < first ? '−' : '') + fa(Math.abs(lastValue - first), digits)) + ' ' + row.unit + ') در ' + name;
  const stamp = stampFor(t1 - t0);
  $('dFrom').textContent = stamp.format(t0 * 1000);
  $('dTo').textContent = stamp.format(t1 * 1000);
  drawChart.scale = { x, y, digits, stamp, unit: row.unit };
}

function stampFor(span) {
  if (span <= 2 * 86400) return dateFormat({ hour: '2-digit', minute: '2-digit' });
  if (span <= 45 * 86400) return dateFormat({ month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  return dateFormat({ year: 'numeric', month: 'short', day: 'numeric' });
}

function bindChart() {
  const chart = $('chart');
  const dot = document.createElement('div');
  dot.className = 'dot';
  dot.hidden = true;
  chart.append(dot);
  const leave = () => {
    $('tip').hidden = dot.hidden = true;
    const cross = $('cross');
    if (cross) cross.setAttribute('visibility', 'hidden');
  };
  chart.addEventListener('pointerleave', leave);
  chart.addEventListener('pointermove', (e) => {
    if (!detailPoints) return;
    const box = $('plot').getBoundingClientRect();
    const s = drawChart.scale;
    const at = (e.clientX - box.left) / box.width * W;
    // The nearest point in time to the mouse, not an interpolated value.
    let best = detailPoints[0];
    for (const p of detailPoints) if (Math.abs(s.x(p[0]) - at) < Math.abs(s.x(best[0]) - at)) best = p;
    const px = s.x(best[0]) / W * 100, py = s.y(best[1]) / H * 100;
    const cross = $('cross');
    cross.setAttribute('x1', s.x(best[0]));
    cross.setAttribute('x2', s.x(best[0]));
    cross.setAttribute('visibility', 'visible');
    dot.hidden = false;
    dot.style.left = px + '%';
    dot.style.top = py + '%';
    const tip = $('tip');
    tip.hidden = false;
    tip.innerHTML = '';
    const value = document.createElement('b');
    value.textContent = fa(best[1], s.digits) + ' ' + s.unit;
    const when = document.createElement('span');
    when.textContent = s.stamp.format(best[0] * 1000);
    tip.append(value, when);
    // Beside the point, flipped to the other side near the right edge, never off the plot.
    const width = tip.offsetWidth, room = chart.clientWidth;
    const left = px / 100 * room;
    tip.style.left = Math.max(0, Math.min(room - width, left > room / 2 ? left - width - 10 : left + 10)) + 'px';
    tip.style.top = (py > 50 ? 0 : chart.clientHeight - tip.offsetHeight) + 'px';
  });
  $('retryBtn').addEventListener('click', loadChart);
  $('alertSave').addEventListener('click', saveAlert);
  for (const id of ['alertAbove', 'alertBelow']) {
    $(id).addEventListener('keydown', (e) => { if (e.key === 'Enter') saveAlert(); });
  }
  $('backBtn').addEventListener('click', closeDetail);
}

// --------------------------------------------------------------------- alerts

// "۲٬۵۸۵٬۰۰۰" or "2,585,000" or "2585000" -> 2585000; empty -> null; nonsense -> NaN.
function parseNumber(text) {
  const plain = text.trim().replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d))
    .replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d)).replace(/[٬,\s]/g, '').replace('٫', '.');
  return plain === '' ? null : /^\d+(\.\d+)?$/.test(plain) ? Number(plain) : NaN;
}

function showAlert(row) {
  const rule = current.alerts[row.id] || {};
  const digits = row.quote && row.quote.ok ? digitsFor(row.quote.price) : 0;
  for (const [id, side] of [['alertAbove', 'above'], ['alertBelow', 'below']]) {
    $(id).value = rule[side] ? fa(rule[side], digits) : '';
    $(id).placeholder = row.quote && row.quote.ok ? fa(row.quote.price, digits) : '';
  }
  const set = Object.keys(rule).length;
  $('alertNote').textContent = set
    ? 'هشدار روشن است. وقتی قیمت به این عدد برسد اعلان ویندوز می‌آید و هشدار برداشته می‌شود.'
    : 'یک یا هر دو عدد را بنویس. خالی یعنی بدون هشدار.';
}

async function saveAlert() {
  const row = detailRow();
  if (!row) return;
  const above = parseNumber($('alertAbove').value), below = parseNumber($('alertBelow').value);
  if (Number.isNaN(above) || Number.isNaN(below)) {
    $('alertNote').textContent = 'فقط عدد بنویس، مثلاً ۲۶۰۰۰۰ یا ۲۶۰٬۰۰۰.';
    return;
  }
  current.alerts[row.id] = await api.set_alert(row.id, above, below);
  if (!Object.keys(current.alerts[row.id]).length) delete current.alerts[row.id];
  showAlert(row);
  $('alertNote').textContent = current.alerts[row.id] ? 'ذخیره شد. ' + $('alertNote').textContent : 'هشدار این ردیف برداشته شد.';
}

// ------------------------------------------------------------------ settings

function renderSettings() {
  const rows = current.rows;
  const full = rows.length >= cfg.max_items;
  $('itemsTitle').textContent = 'ردیف‌ها (' + fa(rows.length) + ' از ' + fa(cfg.max_items) + ')، برای جابه‌جایی بکش';

  const list = $('items');
  list.textContent = '';
  rows.forEach((row, i) => {
    const li = document.createElement('li');
    const handle = document.createElement('span');
    handle.className = 'handle';
    handle.innerHTML = ICONS.handle;
    const label = document.createElement('span');
    label.className = 'label';
    label.textContent = row.label;
    const remove = document.createElement('button');
    remove.className = 'icon remove';
    remove.title = 'حذف';
    remove.setAttribute('aria-label', 'حذف ' + row.label);
    remove.innerHTML = ICONS.remove;
    remove.addEventListener('click', async () => changed(await api.remove_item(i)));
    li.append(handle, label, remove);
    li.addEventListener('pointerdown', (e) => { if (!e.target.closest('button')) dragRow(e, li, i); });
    list.append(li);
  });
  if (!rows.length) {
    const li = document.createElement('li');
    li.className = 'none';
    li.textContent = 'ردیفی نیست';
    list.append(li);
  }

  // Only what is not on the widget yet, grouped the way the catalog groups it.
  const select = $('addSelect');
  const shown = new Set(rows.map((r) => r.id));
  select.textContent = '';
  let group = null;
  cfg.catalog.forEach((item, i) => {
    if (shown.has(item.source + ':' + item.key)) return;
    if (!group || group.label !== item.group) {
      group = document.createElement('optgroup');
      group.label = item.group;
      select.append(group);
    }
    const option = document.createElement('option');
    option.value = i;
    option.textContent = item.label;
    group.append(option);
  });
  select.disabled = $('addBtn').disabled = full || !select.options.length;
  $('addBtn').title = full ? 'حداکثر ' + fa(cfg.max_items) + ' ردیف جا می‌شود' : '';
}

// Reorder by dragging: the row follows the mouse through the list, and its place when the
// button is released is what gets saved.
function dragRow(e, li, from) {
  e.preventDefault();
  const list = $('items');
  // Captured by the list, not the row: moving the row in the DOM would drop its capture.
  list.setPointerCapture(e.pointerId);
  li.classList.add('dragging');
  const move = (ev) => {
    const others = [...list.children].filter((el) => el !== li);
    const before = others.find((el) => {
      const box = el.getBoundingClientRect();
      return ev.clientY < box.top + box.height / 2;
    });
    if (before !== li.nextElementSibling) list.insertBefore(li, before || null);
  };
  const up = async () => {
    list.removeEventListener('pointermove', move);
    list.removeEventListener('pointerup', up);
    list.removeEventListener('pointercancel', up);
    li.classList.remove('dragging');
    const to = [...list.children].indexOf(li);
    if (to !== from) changed(await api.move_item(from, to));
  };
  list.addEventListener('pointermove', move);
  list.addEventListener('pointerup', up);
  list.addEventListener('pointercancel', up);
}

function changed(state) {
  render(state);
  renderSettings();
  fitWindow();
}

// Also called from Python, by the tray menu.
function openSettings() {
  if (view === 'settings' || !current) return;
  $('scale').value = Math.round(current.scale * 100);
  $('opacity').value = Math.round(current.opacity * 100);
  $('scaleOut').textContent = percent($('scale').value);
  $('opacityOut').textContent = percent($('opacity').value);
  $('storySeconds').value = current.story_seconds;
  $('storyOut').textContent = fa(current.story_seconds) + ' ثانیه';
  $('fontSelect').value = current.font;
  renderSettings();
  setView('settings');
}

function closeSettings() {
  if (view === 'settings') setView('list');
}

function bindSettings() {
  for (const [id, lo, hi] of [['scale', ...cfg.scale], ['opacity', ...cfg.opacity]]) {
    $(id).min = Math.round(lo * 100);
    $(id).max = Math.round(hi * 100);
  }
  $('storySeconds').min = cfg.story_seconds[0];
  $('storySeconds').max = cfg.story_seconds[1];
  for (const [family, name] of cfg.fonts) {
    const option = document.createElement('option');
    option.value = family;
    option.textContent = name;
    option.style.fontFamily = `'${family}'`;
    $('fontSelect').append(option);
  }
  $('settingsBtn').addEventListener('click', openSettings);
  $('doneBtn').addEventListener('click', closeSettings);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeSettings(); closeDetail(); }
  });

  // The window resizes under the mouse when the scale changes, so apply it on release.
  $('scale').addEventListener('input', () => { $('scaleOut').textContent = percent($('scale').value); });
  $('scale').addEventListener('change', async () => {
    scale = await api.set_scale($('scale').value / 100);
    fitWindow();
  });
  $('opacity').addEventListener('input', () => {
    $('opacityOut').textContent = percent($('opacity').value);
    api.set_opacity($('opacity').value / 100, false);
  });
  $('opacity').addEventListener('change', () => api.set_opacity($('opacity').value / 100, true));
  $('onTop').addEventListener('change', () => api.set_on_top($('onTop').checked));
  $('storySeconds').addEventListener('input', () => { $('storyOut').textContent = fa($('storySeconds').value) + ' ثانیه'; });
  $('storySeconds').addEventListener('change', async () => {
    current.story_seconds = await api.set_story_seconds(Number($('storySeconds').value));
    if (collapsed) startStory();
  });
  $('fontSelect').addEventListener('change', async () => {
    current.font = await api.set_font($('fontSelect').value);
    document.documentElement.style.setProperty('--font', `'${current.font}'`);
    fitWindow();
  });
  $('compact').addEventListener('change', async () => { await api.set_option('compact', $('compact').checked); tick(); });
  $('bare').addEventListener('change', async () => { await api.set_option('background', !$('bare').checked); tick(); });
  $('locked').addEventListener('change', async () => { await api.set_option('locked', $('locked').checked); tick(); });
  if (cfg.can_autostart) {
    $('autostart').addEventListener('change', async () => {
      $('autostart').checked = await api.set_autostart($('autostart').checked);
    });
  } else {  // running from source: there is no exe to register
    $('autostart').disabled = true;
    $('autostartRow').classList.add('off');
    $('autostartRow').title = 'فقط در نسخه‌ی exe کار می‌کند';
  }
  $('addBtn').addEventListener('click', async () => {
    const item = cfg.catalog[$('addSelect').value];
    if (item) changed(await api.add_item(item.source, item.key));
  });
  $('dockBtn').addEventListener('click', async () => { await api.dock(); tick(); });
}

async function init() {
  api = window.pywebview.api;
  cfg = await api.config();
  $('refreshBtn').addEventListener('click', async () => {
    const b = $('refreshBtn');
    b.classList.add('spin');
    await api.refresh();
    setTimeout(() => { b.classList.remove('spin'); tick(); }, 1200);
  });
  $('closeBtn').addEventListener('click', () => api.hide());
  bindSettings();
  bindResize();
  bindChart();
  const state = await api.state();
  scale = state.scale;
  render(state);
  await fitWindow();
  api.ready();
  setInterval(tick, 1000);
}

if (window.pywebview && window.pywebview.api) init();
else window.addEventListener('pywebviewready', init, { once: true });
