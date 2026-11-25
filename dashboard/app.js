'use strict';
const el = id => document.getElementById(id);
const money = new Intl.NumberFormat('en-IN', {style:'currency', currency:'INR'});
const whole = new Intl.NumberFormat('en-IN', {maximumFractionDigits:0});
const rupees = n => money.format(n / 100);
const clock = n => {
  const minutes = n + 9 * 60 + 15;
  return String(Math.floor(minutes / 60)).padStart(2,'0') + ':' + String(minutes % 60).padStart(2,'0');
};
let state, selectedSource, requestId = 0, etag = '', watching = false;
const competition = {day:'2026-11-25', opening:10000000};
const write = (id, value) => { el(id).textContent = value; };
function error(message) {
  write('error', message);
  el('error').hidden = !message;
  el('loading').hidden = true;
}
function chart(points) {
  const low = Math.min(...points), high = Math.max(...points);
  const pad = Math.max(100, (high - low) * .1);
  const bottom = Math.floor(low-pad), top = Math.ceil(high+pad);
  const xy = points.map((n,i) => [(1000*i/375).toFixed(2), (160*(top-n)/(top-bottom)).toFixed(2)].join(' '));
  const d = 'M' + xy.join(' L');
  el('line').setAttribute('d',d);
  el('area').setAttribute('d', d + ' L' + (1000*(points.length-1)/375) + ' 160 L0 160 Z');
  const labels = document.querySelectorAll('.axis-y span');
  [top,(top+bottom)/2,bottom].forEach((n,i) => { labels[i].textContent = '₹' + whole.format(n/100); });
  el('plot').setAttribute('aria-label', 'Equity from ' + rupees(points[0]) + ' at 09:15 to ' +
    rupees(points.at(-1)) + ' at ' + clock(points.length-1) + ' IST.');
}
function renderFills() {
  const side = el('side').value;
  const visible = state.fills.filter(f => side === 'all' || (side === 'buy') === (f.shares > 0));
  const rows = [];
  for (const f of [...visible].reverse()) {
    const tr = document.createElement('tr');
    for (const [index,value] of [clock(f.minute),f.symbol,f.shares > 0 ? 'Buy' : 'Sell',
      Math.abs(f.shares),rupees(f.price),rupees(f.fees)].entries()) {
      const td = tr.insertCell();
      if (index === 2) {
        const badge = document.createElement('span');
        badge.className = 'badge ' + value.toLowerCase();
        badge.textContent = value;
        td.append(badge);
      } else td.textContent = value;
    }
    rows.push(tr);
  }
  el('fills').replaceChildren(...rows);
  write('table-foot',visible.length ? visible.length + ' of ' + state.fills.length + ' fills · Latest first' :
    state.fills.length ? 'No fills on this side.' : 'No executions recorded.');
}
function view(data, source) {
  if (source !== selectedSource || state?.day !== data.day) el('side').value = 'all';
  selectedSource = source; state = data;
  const minutes = data.equity.length-1, equity = data.equity.at(-1), pnl = equity-data.opening;
  const change = pnl > 0 ? '+' : '';
  const totalFees = data.fills.reduce((s,f) => s + f.fees, 0);
  const allocation = source === 'allocation';
  const date = new Intl.DateTimeFormat('en-GB',{dateStyle:'medium',timeZone:'UTC'}).format(new Date(data.day+'T00:00:00Z'));
  if (allocation) {
    write('source','Competition opening balance');
    write('date','Start date · ' + date);
    write('status','Awaiting forward journal');
  } else {
    write('source', source === 'demo' ? 'Synthetic replay' : data.mode === 'forward' ? 'Forward paper' : 'Paper replay');
    write('date',date);
    write('status', (data.complete ? 'Session closed' : minutes ? 'Partial session' : 'Awaiting first bar') + ' · ' + clock(minutes) + ' IST' + (source === 'watch' && !data.complete ? ' · Auto-refresh' : ''));
  }
  write('pnl',change + rupees(pnl)); el('pnl').className = pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : '';
  write('pct', data.opening ? change + (pnl/data.opening*100).toFixed(2)+'% after fees' : 'After fees');
  write('equity', rupees(equity)); write('opening','Opened at ' + rupees(data.opening));
  write('cash', rupees(data.cash)); write('exposure',rupees(equity-data.cash) + ' in positions');
  write('fees',rupees(totalFees)); write('fillcount',data.fills.length+' fills');
  el('no-bars').hidden = minutes > 0;
  el('plot').hidden = el('legend').hidden = minutes === 0;
  if (minutes) chart(data.equity);
  renderFills();
  write('position-count',data.positions.length);
  const holdings = el('holdings'); holdings.replaceChildren();
  if (!data.positions.length) {
    const box = document.createElement('div'); box.className = 'empty';
    const title = document.createElement('strong'); title.textContent = 'No open positions';
    const detail = document.createElement('p'); detail.textContent = allocation ? 'The opening allocation is entirely in cash.' : data.complete ? 'The account finished the session in cash.' : 'The paper account holds cash.';
    box.append(title,detail); holdings.append(box);
  }
  for (const p of data.positions) {
    const row = document.createElement('div'); row.className = 'holding';
    const name = document.createElement('div'); name.textContent = p.symbol;
    const qty = document.createElement('small'); qty.textContent = p.quantity + ' shares × ' + rupees(p.price);
    const value = document.createElement('span'); value.textContent = rupees(p.price*p.quantity);
    name.append(qty); row.append(name,value); holdings.append(row);
  }
  el('content').hidden = false; el('restore').hidden = source === 'demo';
  el('competition').hidden = allocation;
  el('loading').hidden = true; error('');
}
function showCompetition() {
  ++requestId; watching = false;
  const {day, opening} = competition;
  view({day, opening, cash:opening, equity:[opening], fills:[], positions:[]}, 'allocation');
}
async function loadDemo() {
  const ticket = ++requestId; watching = false;
  try {
    const res = await fetch('demo.json'); if (!res.ok) throw Error();
    const data = await res.json();
    if (ticket === requestId) view(data,'demo');
  } catch { if (ticket === requestId) error('Could not open the demo. Open a session journal to continue.'); }
}
async function watch() {
  if (!watching) return;
  const ticket = requestId;
  try {
    const res = await fetch('session.jsonl',{cache:'no-store',headers:etag ? {'If-None-Match':etag} : {}});
    if (ticket !== requestId) return;
    if (res.status === 304) { error(''); return; }
    if (!res.ok) throw Error('Waiting for the configured journal.');
    const text = await res.text();
    if (ticket !== requestId) return;
    const snapshot = text.slice(0,text.lastIndexOf('\n')+1);
    if (!snapshot.trim()) throw Error('Waiting for the journal header.');
    const data = readJournal(snapshot);
    view(data,'watch'); etag = res.headers.get('ETag') || '';
    if (data.complete) watching = false;
  } catch (e) { if (ticket === requestId) error('Watch paused at the last available record. ' + e.message); }
  finally { if (ticket === requestId && watching) setTimeout(watch,10000); }
}
el('side').addEventListener('change', renderFills);
el('open').onclick = () => el('file').click();
el('restore').onclick = loadDemo;
el('competition').onclick = showCompetition;
el('file').onchange = async () => {
  const file = el('file').files[0]; if (!file) return;
  try {
    const data = readJournal(await file.text());
    ++requestId; watching = false; view(data,'file');
  } catch (e) { error('Could not open this journal. ' + e.message); }
  finally { el('file').value = ''; }
};
if (new URLSearchParams(location.search).has('watch')) {
  watching = true; el('competition').hidden = false; watch();
} else showCompetition();
