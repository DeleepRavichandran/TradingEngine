/* Translate solo.py's append-only journal into the fundamental account shown on screen. */
function readJournal(input) {
  const lines = input.trim().split(/\r?\n/);
  const header = JSON.parse(lines.shift());
  const amount = value => {
    if (!Number.isSafeInteger(value) || value < 0) throw new Error('Invalid amount in journal.');
    return value;
  };
  if (header.type !== 'session' || !['forward', 'replay'].includes(header.mode) ||
      !/^\d{4}-\d{2}-\d{2}$/.test(header.day) || !Array.isArray(header.symbols) ||
      !header.symbols.length || !header.symbols.every(s => typeof s === 'string' && s.length)) {
    throw new Error('Choose a session journal created by solo.py.');
  }
  const opening = amount(header.opening_cash_paise === undefined ? 10000000 : header.opening_cash_paise.fundamental);
  const state = {day: header.day, mode: header.mode, opening, cash: opening, complete: false,
    equity: [opening], fills: [], positions: [], symbols: header.symbols};
  const allowed = new Set(header.symbols);
  let fees = 0;
  for (const line of lines) {
    const row = JSON.parse(line);
    if (state.complete) throw new Error('Unexpected records after the session close.');
    const minute = state.equity.length;
    if (row.type === 'complete') {
      const account = row.accounts?.fundamental;
      if (minute !== 376 || row.day !== state.day || row.mode !== state.mode ||
          row.session_id !== header.session_id || !account || account.fills !== state.fills.length ||
          account.fees_paise !== fees || account.closing_cash_paise !== state.cash ||
          state.equity.at(-1) !== state.cash || state.positions.length) {
        throw new Error('Session summary does not match its minute records.');
      }
      state.complete = true;
      continue;
    }
    const account = row.fundamental;
    const close = Date.parse(header.day + 'T09:15:00+05:30') + minute * 60000;
    if (row.type !== 'minute' || row.minute !== minute || minute > 375 || Date.parse(row.close) !== close ||
        !account || !Array.isArray(account.fills) || !account.positions || typeof account.positions !== 'object') {
      throw new Error('Missing or invalid minute record.');
    }
    state.equity.push(amount(account.equity));
    state.cash = amount(account.cash);
    state.positions = Object.entries(account.positions).map(([symbol, quantity]) => {
      if (!allowed.has(symbol) || amount(quantity) === 0) throw new Error('Invalid position.');
      const price = amount(row.bars?.[symbol]?.[3]);
      return {symbol, quantity, price};
    });
    for (const fill of account.fills) {
      if (!allowed.has(fill.symbol) || !Number.isSafeInteger(fill.shares) || fill.shares === 0) {
        throw new Error('Invalid fill.');
      }
      fees += amount(fill.fees);
      state.fills.push({minute: minute - 1, symbol: fill.symbol, shares: fill.shares,
        price: amount(fill.price), fees: fill.fees});
    }
  }
  return state;
}
if (typeof module !== 'undefined') module.exports = {readJournal};
