(function () {
  const data = window.MULTI_STOCK_DATA;
  if (!data || !data.stocks || !data.stocks.length) {
    const el = document.getElementById('regime-narrative');
    if (el) el.textContent = 'Multi-stock data not baked in yet.';
    return;
  }

  const { stocks, correlation, buckets } = data;
  document.getElementById('regime-n').textContent = stocks.length;

  const worstGap = stocks.reduce((a, b) => (a.gap_pct < b.gap_pct ? a : b));
  const bestGap = stocks.reduce((a, b) => (a.gap_pct > b.gap_pct ? a : b));
  const stats = [
    [stocks.length, 'stocks tested'],
    [correlation.toFixed(2), 'correlation (buy-hold vs gap)'],
    [`${worstGap.ticker} ${worstGap.gap_pct.toFixed(1)}%`, 'worst gap'],
    [`${bestGap.ticker} +${bestGap.gap_pct.toFixed(1)}%`, 'best gap'],
  ];
  document.getElementById('regime-stats').innerHTML = stats.map(
    ([num, lbl]) => `<div class="stat"><div class="num">${num}</div><div class="lbl">${lbl}</div></div>`
  ).join('');

  const bucketBody = document.querySelector('#bucketTable tbody');
  bucketBody.innerHTML = buckets.map(b => `
    <tr>
      <td>${b.label}</td>
      <td>${b.n}</td>
      <td>${b.avg_buy_hold >= 0 ? '+' : ''}${b.avg_buy_hold.toFixed(2)}%</td>
      <td class="${b.avg_gap < 0 ? 'neg' : ''}">${b.avg_gap >= 0 ? '+' : ''}${b.avg_gap.toFixed(2)}%</td>
      <td>${b.tickers.join(', ')}</td>
    </tr>`).join('');

  const stockBody = document.querySelector('#multiStockTable tbody');
  stockBody.innerHTML = stocks.map(s => `
    <tr>
      <td>${s.ticker}</td>
      <td class="${s.buy_hold_pct < 0 ? 'neg' : ''}">${s.buy_hold_pct >= 0 ? '+' : ''}${s.buy_hold_pct.toFixed(2)}%</td>
      <td class="${s.strategy_pct < 0 ? 'neg' : ''}">${s.strategy_pct >= 0 ? '+' : ''}${s.strategy_pct.toFixed(2)}%</td>
      <td class="${s.gap_pct < 0 ? 'neg' : ''}">${s.gap_pct >= 0 ? '+' : ''}${s.gap_pct.toFixed(2)}%</td>
      <td>${s.assigned}</td>
      <td>${s.expired}</td>
      <td>${s.skipped}</td>
    </tr>`).join('');

  document.getElementById('regime-narrative').textContent =
    `Across ${stocks.length} stocks, the correlation between a stock's own return and how ` +
    `much the strategy gave up relative to it was ${correlation.toFixed(2)} — the more a ` +
    `stock rallied, the more the covered call tended to lag it; the more it fell, the more ` +
    `the strategy tended to help. See the write-up below for the two notable exceptions.`;

  const pts = stocks.map(s => ({ x: s.buy_hold_pct, y: s.gap_pct }));
  const xs = pts.map(p => p.x);
  const minX = Math.min(...xs), maxX = Math.max(...xs);

  const n = pts.length;
  const sumX = xs.reduce((a, b) => a + b, 0);
  const ys = pts.map(p => p.y);

cat > covered-call-multi-render.js << 'PYEOF'
(function () {
  const data = window.MULTI_STOCK_DATA;
  if (!data || !data.stocks || !data.stocks.length) {
    const el = document.getElementById('regime-narrative');
    if (el) el.textContent = 'Multi-stock data not baked in yet.';
    return;
  }

  const { stocks, correlation, buckets } = data;
  document.getElementById('regime-n').textContent = stocks.length;

  const worstGap = stocks.reduce((a, b) => (a.gap_pct < b.gap_pct ? a : b));
  const bestGap = stocks.reduce((a, b) => (a.gap_pct > b.gap_pct ? a : b));
  const stats = [
    [stocks.length, 'stocks tested'],
    [correlation.toFixed(2), 'correlation (buy-hold vs gap)'],
    [`${worstGap.ticker} ${worstGap.gap_pct.toFixed(1)}%`, 'worst gap'],
    [`${bestGap.ticker} +${bestGap.gap_pct.toFixed(1)}%`, 'best gap'],
  ];
  document.getElementById('regime-stats').innerHTML = stats.map(
    ([num, lbl]) => `<div class="stat"><div class="num">${num}</div><div class="lbl">${lbl}</div></div>`
  ).join('');

  const bucketBody = document.querySelector('#bucketTable tbody');
  bucketBody.innerHTML = buckets.map(b => `
    <tr>
      <td>${b.label}</td>
      <td>${b.n}</td>
      <td>${b.avg_buy_hold >= 0 ? '+' : ''}${b.avg_buy_hold.toFixed(2)}%</td>
      <td class="${b.avg_gap < 0 ? 'neg' : ''}">${b.avg_gap >= 0 ? '+' : ''}${b.avg_gap.toFixed(2)}%</td>
      <td>${b.tickers.join(', ')}</td>
    </tr>`).join('');

  const stockBody = document.querySelector('#multiStockTable tbody');
  stockBody.innerHTML = stocks.map(s => `
    <tr>
      <td>${s.ticker}</td>
      <td class="${s.buy_hold_pct < 0 ? 'neg' : ''}">${s.buy_hold_pct >= 0 ? '+' : ''}${s.buy_hold_pct.toFixed(2)}%</td>
      <td class="${s.strategy_pct < 0 ? 'neg' : ''}">${s.strategy_pct >= 0 ? '+' : ''}${s.strategy_pct.toFixed(2)}%</td>
      <td class="${s.gap_pct < 0 ? 'neg' : ''}">${s.gap_pct >= 0 ? '+' : ''}${s.gap_pct.toFixed(2)}%</td>
      <td>${s.assigned}</td>
      <td>${s.expired}</td>
      <td>${s.skipped}</td>
    </tr>`).join('');

  document.getElementById('regime-narrative').textContent =
    `Across ${stocks.length} stocks, the correlation between a stock's own return and how ` +
    `much the strategy gave up relative to it was ${correlation.toFixed(2)} — the more a ` +
    `stock rallied, the more the covered call tended to lag it; the more it fell, the more ` +
    `the strategy tended to help. See the write-up below for the two notable exceptions.`;

  const pts = stocks.map(s => ({ x: s.buy_hold_pct, y: s.gap_pct }));
  const xs = pts.map(p => p.x);
  const minX = Math.min(...xs), maxX = Math.max(...xs);

  const n = pts.length;
  const sumX = xs.reduce((a, b) => a + b, 0);
  const ys = pts.map(p => p.y);
  const sumY = ys.reduce((a, b) => a + b, 0);
  const sumXY = pts.reduce((a, p) => a + p.x * p.y, 0);
  const sumXX = xs.reduce((a, x) => a + x * x, 0);
  const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
  const intercept = (sumY - slope * sumX) / n;
  const fitLine = [
    { x: minX, y: slope * minX + intercept },
    { x: maxX, y: slope * maxX + intercept },
  ];

  new Chart(document.getElementById('regimeChart'), {
    data: {
      datasets: [
        {
          type: 'scatter', label: 'Stock',
          data: pts.map((p, i) => ({ x: p.x, y: p.y, ticker: stocks[i].ticker })),
          backgroundColor: '#1a3a6e', pointRadius: 5,
        },
        {
          type: 'line', label: `Trend (r = ${correlation.toFixed(2)})`,
          data: fitLine, borderColor: '#9a3b3b', borderWidth: 2, pointRadius: 0, fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { position: 'top', labels: { font: { family: 'IBM Plex Mono', size: 11 } } },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const raw = ctx.raw;
              if (raw.ticker) return `${raw.ticker}: buy-hold ${raw.x.toFixed(1)}%, gap ${raw.y.toFixed(1)}%`;
              return ctx.dataset.label;
            },
          },
        },
      },
      scales: {
        x: { title: { display: true, text: "Stock's own buy-and-hold return (%)" } },
        y: { title: { display: true, text: 'Strategy gap vs. buy-and-hold (%)' } },
      },
    },
  });
})();
