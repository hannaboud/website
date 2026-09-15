(function () {
  const data = window.BOOK_DATA;
  const badge = document.getElementById('sample-badge');

  if (!data || !data.ledger || !data.ledger.length) {
    badge.textContent = 'No data baked in yet — run build_site_data.py, then generate_book_js.py';
    return;
  }

  const { blotter, ledger, scatter, meta } = data;
  badge.textContent = `${meta && meta.equity ? meta.equity : 'AAPL'} · ${ledger.length} weeks · real LSEG data`;

  // ---------------- stats row ----------------
  const assigned = blotter.filter(r => r.side === 'ASSIGN').length;
  const expired = blotter.filter(r => r.side === 'EXPIRE').length;
  const skipped = blotter.filter(r => r.side === 'SKIP').length;
  const finalNav = ledger[ledger.length - 1].nav;
  const startingCash = meta && meta.starting_cash != null ? meta.starting_cash : 10000;
  const firstSpot = ledger[0].stock_mark;
  const lastSpot = ledger[ledger.length - 1].stock_mark;
  const buyHoldPct = ((lastSpot - firstSpot) / firstSpot) * 100;
  const stratPnl = finalNav - startingCash;
  const stratPct = (stratPnl / (100 * firstSpot)) * 100;

  const stats = [
    [ledger.length, 'weeks in book'],
    [assigned, 'assigned'],
    [expired, 'expired OTM'],
    [skipped, 'no call written'],
    [`$${finalNav.toFixed(0)}`, 'final NAV'],
    [`${stratPct >= 0 ? '+' : ''}${stratPct.toFixed(1)}%`, 'strategy return'],
    [`${buyHoldPct >= 0 ? '+' : ''}${buyHoldPct.toFixed(1)}%`, 'AAPL buy-and-hold'],
  ];
  document.getElementById('stats-row').innerHTML = stats.map(
    ([num, lbl]) => `<div class="stat"><div class="num">${num}</div><div class="lbl">${lbl}</div></div>`
  ).join('');

  // ---------------- blotter table ----------------
  const blotterBody = document.querySelector('#blotterTable tbody');
  blotterBody.innerHTML = blotter.map(r => `
    <tr>
      <td>${r.time}</td>
      <td>${r.instrument}</td>
      <td class="side-${r.side}">${r.side}</td>
      <td>${r.qty}</td>
      <td>${r.fill != null ? Number(r.fill).toFixed(2) : '—'}</td>
      <td class="${r.cash_delta < 0 ? 'neg' : ''}">${r.cash_delta != null ? r.cash_delta.toFixed(2) : '—'}</td>
      <td>${r.note}</td>
    </tr>`).join('');

  // ---------------- ledger table ----------------
  const ledgerBody = document.querySelector('#ledgerTable tbody');
  ledgerBody.innerHTML = ledger.map(r => `
    <tr>
      <td>${r.week_of}</td>
      <td>${r.shares}</td>
      <td>${r.stock_mark.toFixed(2)}</td>
      <td class="${r.cash < 0 ? 'neg' : ''}">${r.cash.toFixed(2)}</td>
      <td>${r.lmv.toFixed(2)}</td>
      <td>${r.nav.toFixed(2)}</td>
      <td>${r.initial_margin.toFixed(2)}</td>
      <td>${r.maintenance_margin.toFixed(2)}</td>
      <td class="${r.available_funds < 0 ? 'neg' : ''}">${r.available_funds.toFixed(2)}</td>
    </tr>`).join('');

  // ---------------- NAV chart ----------------
  new Chart(document.getElementById('navChart'), {
    type: 'line',
    data: {
      labels: ledger.map(r => r.week_of),
      datasets: [
        { label: 'NAV', data: ledger.map(r => r.nav), borderColor: '#1a3a6e', backgroundColor: '#1a3a6e', tension: .15, pointRadius: 3 },
        { label: 'Initial margin', data: ledger.map(r => r.initial_margin), borderColor: '#9a3b3b', backgroundColor: '#9a3b3b', borderDash: [4, 3], tension: .15, pointRadius: 2 },
        { label: 'Maintenance margin', data: ledger.map(r => r.maintenance_margin), borderColor: '#a6752c', backgroundColor: '#a6752c', borderDash: [1, 3], tension: .15, pointRadius: 2 },
      ],
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: false } },
      scales: {
        y: { ticks: { callback: v => '$' + v.toLocaleString() } },
      },
    },
  });

  // ---------------- scatter chart ----------------
  if (scatter && scatter.points && scatter.points.length >= 2) {
    const pts = scatter.points.map(p => ({ x: p.mid, y: p.trdprc_1 }));
    const xs = pts.map(p => p.x);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const fitLine = (scatter.slope != null) ? [
      { x: minX, y: scatter.slope * minX + scatter.intercept },
      { x: maxX, y: scatter.slope * maxX + scatter.intercept },
    ] : [];

    new Chart(document.getElementById('scatterChart'), {
      data: {
        datasets: [
          { type: 'scatter', label: 'Near-the-money calls', data: pts, backgroundColor: '#1a3a6e88' },
          { type: 'line', label: `Fit (R² = ${scatter.r2 != null ? scatter.r2.toFixed(4) : 'n/a'})`,
            data: fitLine, borderColor: '#9a3b3b', borderWidth: 2, pointRadius: 0, fill: false },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { position: 'top', labels: { font: { family: 'IBM Plex Mono', size: 11 } } } },
        scales: {
          x: { title: { display: true, text: 'Mid = (BID+ASK)/2' } },
          y: { title: { display: true, text: 'TRDPRC_1 (last trade)' } },
        },
      },
    });
  } else {
    document.getElementById('scatterChart').replaceWith(
      Object.assign(document.createElement('p'), { textContent: 'No scatter data baked in yet.' })
    );
  }
})();
