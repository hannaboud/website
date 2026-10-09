(function () {
  const D = window.PMCC_DATA;
  const badge = document.getElementById('sample-badge');
  if (!D || !D.ledger || !D.ledger.length) {
    badge.textContent = 'No data baked in yet — run 06_build_site_data.py';
    return;
  }
  const { meta, metrics: M, blotter, ledger, daily } = D;
  const S = M.strategy, B = M.buy_hold;

  // ---------------- formatters ----------------
  const usd = v => (v < 0 ? '−$' : '$') + Math.abs(Math.round(v)).toLocaleString('en-US');
  const usd2 = v => v == null ? '—' : (v < 0 ? '−' : '') + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const pct = d => v => (v < 0 ? '−' : '') + Math.abs(v * 100).toFixed(d) + '%';
  const date = s => new Date(s + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  const F = { usd, pct0: pct(0), pct1: pct(1), pct2: pct(2) };

  // fill every <span data-k="path"> from the data, so text and tables cannot disagree
  document.querySelectorAll('[data-k]').forEach(el => {
    let v = el.dataset.k.split('.').reduce((o, k) => o == null ? o : o[k], D);
    if (el.dataset.f) v = F[el.dataset.f](v);
    else if (/^\d{4}-\d\d-\d\d$/.test(v)) v = date(v);
    el.textContent = v;
  });

  badge.textContent = `${meta.ticker} · ${M.weeks} weeks · ${M.trading_days} trading days · real LSEG data`;

  // ---------------- stats row ----------------
  const stats = [
    [F.pct1(S.total_return), 'PMCC return'],
    [F.pct1(B.total_return), 'buy-and-hold return'],
    [usd(M.long_call_cost), 'cost of the long call'],
    [usd(B.capital), 'cost of 100 shares'],
    [`${M.weeks_assigned} of ${M.calls_sold}`, 'short calls finished in the money'],
    [usd(M.short_leg_net), 'net from short calls'],
  ];
  document.getElementById('stats-row').innerHTML = stats.map(
    ([n, l]) => `<div class="stat"><div class="num">${n}</div><div class="lbl">${l}</div></div>`).join('');

  // ---------------- results table ----------------
  const rows = [
    ['Starting cash', usd(S.capital), usd(B.capital)],
    ['Spent on the position at the start', usd(M.long_call_cost), usd(B.capital)],
    ['Final value', usd(S.final_value), usd(B.final_value)],
    ['Profit', usd(S.pnl), usd(B.pnl)],
    ['Total return', F.pct1(S.total_return), F.pct1(B.total_return)],
    ['Volatility, annualized', F.pct1(S.volatility), F.pct1(B.volatility)],
    ['Sharpe ratio', S.sharpe.toFixed(2), B.sharpe.toFixed(2)],
    ['Max drawdown', F.pct1(S.max_drawdown), F.pct1(B.max_drawdown)],
  ];
  document.querySelector('#resultTable tbody').innerHTML = rows.map(
    r => `<tr><td>${r[0]}</td><td class="num">${r[1]}</td><td class="num">${r[2]}</td></tr>`).join('');

  // ---------------- profit breakdown ----------------
  const longPnl = S.pnl - M.short_leg_net - M.interest_earned;
  const pnlRows = [
    ['Long calls', longPnl, 'Bought at the ask; first one settled at expiry, second valued at its closing bid'],
    ['Short calls', M.short_leg_net, `${usd(M.premium_collected)} premium received, ${usd(M.assignment_cost)} paid on in-the-money expiries`],
    ['Interest on cash', M.interest_earned, `${F.pct2(meta.cash_rate)} a year on the cash balance`],
    ['Total', S.pnl, 'Equals final value minus starting cash'],
  ];
  document.querySelector('#pnlTable tbody').innerHTML = pnlRows.map(
    r => `<tr><td>${r[0]}</td><td class="num ${r[1] < 0 ? 'neg' : ''}">${usd(r[1])}</td><td>${r[2]}</td></tr>`).join('');

  // ---------------- trend split ----------------
  const split = ['up', 'down'].map(t => {
    const w = ledger.filter(r => r.trend === t);
    const prem = w.reduce((a, r) => a + r.premium, 0), cost = w.reduce((a, r) => a + r.assignment_cost, 0);
    return [t === 'up' ? 'Uptrend' : 'Downtrend', w[0] ? w[0].target_delta.toFixed(2) : '—', w.length,
      w.filter(r => r.outcome === 'ASSIGNED').length, prem, cost, prem - cost];
  });
  document.querySelector('#trendTable tbody').innerHTML = split.map(r => `<tr><td>${r[0]}</td>
    <td class="num">${r[1]}</td><td class="num">${r[2]}</td><td class="num">${r[3]}</td><td class="num">${usd(r[4])}</td>
    <td class="num">${usd(r[5])}</td><td class="num ${r[6] < 0 ? 'neg' : ''}">${usd(r[6])}</td></tr>`).join('');

  // ---------------- blotter ----------------
  document.getElementById('blotterCount').textContent = blotter.length;
  document.querySelector('#blotterTable tbody').innerHTML = blotter.map(r => `
    <tr>
      <td>${r.time}</td>
      <td>${r.instrument}</td>
      <td class="side-${r.side}">${r.side}</td>
      <td class="num">${r.qty}</td>
      <td class="num">${usd2(r.limit)}</td>
      <td class="num">${usd2(r.fill)}</td>
      <td class="num ${r.cash_delta < 0 ? 'neg' : ''}">${usd2(r.cash_delta)}</td>
      <td>${r.note}</td>
    </tr>`).join('');

  // ---------------- ledger ----------------
  document.querySelector('#ledgerTable tbody').innerHTML = ledger.map(r => `
    <tr>
      <td>${r.week_of}</td>
      <td>${r.trend}</td>
      <td class="num">${r.target_delta.toFixed(2)}</td>
      <td class="num">${r.strike != null ? r.strike : '—'}</td>
      <td class="num">${r.delta != null ? r.delta.toFixed(3) : '—'}</td>
      <td class="num">${usd2(r.premium)}</td>
      <td>${r.expiry}</td>
      <td class="num">${usd2(r.spot_expiry)}</td>
      <td class="out-${r.outcome}">${r.outcome}</td>
      <td class="num ${r.assignment_cost > 0 ? 'neg' : ''}">${usd2(-r.assignment_cost || 0)}</td>
      <td class="num">${usd2(r.cash)}</td>
      <td class="num">${usd2(r.long_call)}</td>
      <td class="num">${usd2(r.nav)}</td>
    </tr>`).join('');

  // ---------------- charts ----------------
  const INK = '#454b58', GRID = '#e2ddd2', BLUE = '#2f5fa8', GOLD = '#a6752c', RED = '#b5483f';
  Chart.defaults.font.family = "'IBM Plex Mono', monospace";
  Chart.defaults.font.size = 11;
  Chart.defaults.color = INK;
  const axis = { grid: { color: GRID }, border: { display: false } };
  const tip = { backgroundColor: '#14171c', titleColor: '#f5f1ea', bodyColor: '#f5f1ea', padding: 10, boxPadding: 4 };

  new Chart(document.getElementById('navChart'), {
    type: 'line',
    data: {
      labels: daily.map(r => r.date),
      datasets: [
        { label: 'PMCC', data: daily.map(r => r.nav), borderColor: BLUE, backgroundColor: BLUE, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0 },
        { label: 'Buy and hold 100 shares', data: daily.map(r => r.buy_hold), borderColor: GOLD, backgroundColor: GOLD, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0 },
      ],
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { ...tip, callbacks: { title: i => date(i[0].label), label: c => ` ${c.dataset.label}: ${usd(c.parsed.y)}` } },
      },
      scales: {
        x: { ...axis, grid: { display: false }, ticks: { maxTicksLimit: 9, maxRotation: 0, callback(v) { return date(this.getLabelForValue(v)).slice(0, -5); } } },
        y: { ...axis, ticks: { callback: v => '$' + (v / 1000) + 'k' } },
      },
    },
  });

  new Chart(document.getElementById('weekChart'), {
    type: 'bar',
    data: {
      labels: ledger.map(r => r.week_of),
      datasets: [{
        label: 'Net', data: ledger.map(r => r.premium - r.assignment_cost),
        backgroundColor: ledger.map(r => r.outcome === 'ASSIGNED' ? RED : BLUE), borderRadius: 2,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: { ...tip, callbacks: {
          title: i => 'Week of ' + date(i[0].label),
          label: c => { const r = ledger[c.dataIndex]; return [` Strike ${r.strike}, delta ${r.delta.toFixed(2)}`,
            ` Premium ${usd(r.premium)}`, ` Cost ${usd(r.assignment_cost)}`, ` Net ${usd(c.parsed.y)}`]; } } },
      },
      scales: {
        x: { ...axis, grid: { display: false }, ticks: { maxTicksLimit: 9, maxRotation: 0, callback(v) { return date(this.getLabelForValue(v)).slice(0, -5); } } },
        y: { ...axis, ticks: { callback: v => usd(v) } },
      },
    },
  });
})();
