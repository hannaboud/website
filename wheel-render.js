(function () {
  const D = window.WHEEL_DATA;
  const badge = document.getElementById('badge');
  if (!D || !D.ledger || !D.ledger.length) { badge.textContent = 'No data baked in yet: run 04_build_site_data.py'; return; }
  const { meta, metrics: M, fill: F, blotter, ledger, weekly, greeks: G, attribution_cum: AC } = D;
  // colour carries meaning: blue = put phase (cash), pink = call phase (shares)
  const T = { ink: '#e7ecf6', ink2: '#a6b0c6', ink3: '#7d89a4', line: '#1e2942', grid: 'rgba(148, 163, 196, 0.09)', bg: '#0a1020',
    put: '#3d8be0', call: '#d4609f', theta: '#1fa58c', gamma: '#d4692f', vega: '#9579e8', neutral: '#7d89a4', dim: '#4f5b78' };
  const RAMP = { P: ['#24456f', '#2f66a8', '#3d8be0', '#93c1f2'], C: ['#5c2b48', '#93437a', '#d4609f', '#efa6cc'] };
  const REDUCE = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  Chart.defaults.font.family = "'Geist', ui-sans-serif, system-ui, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = T.ink3;
  Chart.defaults.borderColor = T.grid;
  Chart.defaults.animation.duration = 0;   // no animation by default (keeps the defaults that per-chart animations inherit)
  Chart.defaults.elements.line.borderWidth = 2;
  Chart.defaults.elements.point.radius = 0;
  Chart.defaults.elements.point.hoverRadius = 4;
  Object.assign(Chart.defaults.plugins.legend.labels, { color: T.ink2, usePointStyle: true, pointStyle: 'rectRounded', boxWidth: 8, boxHeight: 8, padding: 14 });
  Object.assign(Chart.defaults.plugins.tooltip, { backgroundColor: 'rgba(8, 13, 26, 0.96)', borderColor: '#2b3857', borderWidth: 1, titleColor: T.ink,
    bodyColor: T.ink2, padding: 10, cornerRadius: 10, boxPadding: 4, usePointStyle: true });
  Object.assign(Chart.defaults.plugins.title, { color: T.ink, align: 'start', font: { size: 13, weight: '600' }, padding: { top: 2, bottom: 12 } });
  // legend swatches take each line's colour
  Chart.register({ id: 'lineSwatch', beforeInit(chart) {
    chart.data.datasets.forEach(d => { if (d.backgroundColor === undefined && typeof d.borderColor === 'string') d.backgroundColor = d.borderColor; });
  } });
  // soft glow under the lines that matter most (dataset option `glow: <colour>`)
  Chart.register({ id: 'glow',
    beforeDatasetDraw(chart, args) { const g = chart.data.datasets[args.index].glow; if (!g) return; chart.ctx.save(); chart.ctx.shadowColor = g; chart.ctx.shadowBlur = 14; },
    afterDatasetDraw(chart, args) { if (chart.data.datasets[args.index].glow) chart.ctx.restore(); } });
  // charts further down are built when they scroll into view...
  const lazy = (id, make) => {
    const el = document.getElementById(id);
    if (!('IntersectionObserver' in window)) return make();
    const io = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { io.disconnect(); make(); } }, { rootMargin: '0px 0px -10% 0px' });
    io.observe(el);
  };
  // ...and time series draw themselves in, left to right, once
  function drawIn(n, ms = 1500) {   // spread into a chart's options: { ...drawIn(points) }
    if (REDUCE) return { animation: false };
    const d = ms / Math.max(n, 1);
    const prevY = ctx => {
      const prev = ctx.index > 0 && ctx.chart.getDatasetMeta(ctx.datasetIndex).data[ctx.index - 1];
      return prev ? prev.getProps(['y'], true).y : ctx.chart.scales.y.getPixelForValue(ctx.chart.data.datasets[ctx.datasetIndex].data.find(v => v != null) ?? 0);
    };
    const step = key => ({ type: 'number', easing: 'linear', duration: d, from: key === 'x' ? NaN : prevY,
      delay: ctx => { if (ctx.type !== 'data' || ctx[key + 'Started']) return 0; ctx[key + 'Started'] = true; return ctx.index * d; } });
    return { animation: { duration: ms }, animations: { x: step('x'), y: step('y') } };
  }
  // numbers count up to their final value once (every number in the element's text is animated, format and markup kept)
  function countUp(el, ms = 1100) {
    if (REDUCE || !/\d/.test(el.textContent)) return;
    const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), jobs = [];
    while (walk.nextNode()) {
      const node = walk.currentNode, final = node.nodeValue;
      if (/\d/.test(final)) jobs.push({ node, final, toks: [...final.matchAll(/\d[\d,]*(?:\.(\d+))?/g)] });
    }
    const t0 = performance.now();
    const frame = now => {
      const p = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - p, 3);
      jobs.forEach(({ node, final, toks }) => {
        if (p >= 1) { node.nodeValue = final; return; }
        let out = '', last = 0;
        toks.forEach(m => {
          const raw = m[0], dec = m[1] ? m[1].length : 0, v = parseFloat(raw.replace(/,/g, '')) * e;
          out += final.slice(last, m.index) + (raw.includes(',') ? v.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec }) : v.toFixed(dec));
          last = m.index + raw.length;
        });
        node.nodeValue = out + final.slice(last);
      });
      if (p < 1) requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }

  // ---------------------------------------------------------------- formatting
  const isNum = v => v !== null && v !== undefined && v !== '' && !Number.isNaN(Number(v));
  const sign = v => (v < 0 ? '−' : '');
  const fmt = {
    usd0: v => `${sign(v)}$${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 0 })}`,
    usd2: v => `${sign(v)}$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
    pct1: v => `${sign(v)}${Math.abs(v * 100).toFixed(1)}%`,
    pct2: v => `${sign(v)}${Math.abs(v * 100).toFixed(2)}%`,
    spct: v => `${v > 0 ? '+' : sign(v)}${Math.abs(v * 100).toFixed(2)}%`,
    dec0: v => Math.round(v).toString(), dec1: v => Number(v).toFixed(1), dec2: v => Number(v).toFixed(2),
    dec3: v => Number(v).toFixed(3), dec4: v => Number(v).toFixed(4),
    int: v => Math.round(v).toLocaleString('en-US'),
    cents: v => `${(v * 100).toFixed(Math.abs(v * 100 % 1) > 1e-9 ? 1 : 0)}¢`,
    px: v => Number(v).toFixed(2),
  };
  const f = (v, k) => (isNum(v) ? fmt[k](Number(v)) : '—');
  const get = path => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), D);
  document.querySelectorAll('[data-k]').forEach(el => {
    const v = get(el.dataset.k);
    el.textContent = el.dataset.f ? f(v, el.dataset.f) : (v ?? '—');
  });
  const cls = v => (isNum(v) && v < 0 ? 'neg' : '');
  const $ = id => document.getElementById(id);
  const money = { ticks: { callback: v => (v < 0 ? '−$' : '$') + Math.abs(v).toLocaleString() } };

  // ---------------------------------------------------------------- Black-Scholes (same model as greeks_lib.py)
  const erf = x => {
    const t = 1 / (1 + 0.3275911 * Math.abs(x));
    const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
    return x >= 0 ? y : -y;
  };
  const N = x => 0.5 * (1 + erf(x / Math.SQRT2));
  const npdf = x => Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);
  function bs(S, K, T, r, q, v, right) {
    if (T <= 0) return right === 'C' ? Math.max(S - K, 0) : Math.max(K - S, 0);
    const sq = v * Math.sqrt(T), d1 = (Math.log(S / K) + (r - q + 0.5 * v * v) * T) / sq, d2 = d1 - sq;
    return right === 'C' ? S * Math.exp(-q * T) * N(d1) - K * Math.exp(-r * T) * N(d2)
      : K * Math.exp(-r * T) * N(-d2) - S * Math.exp(-q * T) * N(-d1);
  }
  function bsg(S, K, T, r, q, v, right) {
    const sq = v * Math.sqrt(T), d1 = (Math.log(S / K) + (r - q + 0.5 * v * v) * T) / sq, d2 = d1 - sq;
    const eq = Math.exp(-q * T), er = Math.exp(-r * T), p = npdf(d1), common = -S * eq * p * v / (2 * Math.sqrt(T));
    const g = { gamma: eq * p / (S * sq), vega: S * eq * p * Math.sqrt(T) / 100 };
    if (right === 'C') { g.delta = eq * N(d1); g.theta = (common - r * K * er * N(d2) + q * S * eq * N(d1)) / 365; }
    else { g.delta = -eq * N(-d1); g.theta = (common + r * K * er * N(-d2) - q * S * eq * N(-d1)) / 365; }
    return g;
  }
  const R = meta.option_rate ?? M.risk_free, Q = meta.dividend_yield;   // market rate for Black-Scholes
  const days = (a, b) => Math.round((new Date(b) - new Date(a)) / 864e5);

  // ---------------------------------------------------------------- badge + stats
  const noQuote = blotter.filter(r => r.side === 'SKIP' && /quote/.test(r.note || '')).length;
  badge.textContent = `${meta.ticker} · ${M.weeks} weeks · ${ledger.length} trading days · real LSEG quotes` +
    (noQuote ? ` · ${noQuote} week${noQuote > 1 ? 's' : ''} with nothing sold for missing data (see blotter)` : '') + ` · built ${meta.built}`;
  const S = M.strategy, B = M.bh100, A = M.bh_all, AT = G.attribution, VR = G.vrp;
  $('stats-row').innerHTML = [
    [f(S.final_value, 'usd0'), 'final NAV'], [f(S.total_return, 'spct'), 'wheel return'],
    [f(B.total_return, 'spct'), 'SPY 100 sh + cash'], [`${f(S.sharpe, 'dec2')} vs ${f(B.sharpe, 'dec2')}`, 'Sharpe, wheel vs SPY'],
    [f(S.max_drawdown, 'pct1'), 'max drawdown'], [`${f(AT.theta, 'usd0')} / ${f(AT.gamma, 'usd0')}`, 'theta earned / gamma paid'],
    [`${M.puts_assigned} / ${M.called_away}`, 'puts assigned / called away'],
  ].map(([n, l]) => `<div class="stat"><div class="num">${String(n).split(/( \/ | vs )/).map(t => (/^ (\/|vs) $/.test(t) ? t : `<span class="nw">${t}</span>`)).join('')}</div><div class="lbl">${l}</div></div>`).join('');
  if (!REDUCE && 'IntersectionObserver' in window) {
    const sio = new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) { sio.disconnect(); $('stats-row').querySelectorAll('.num').forEach(n => countUp(n)); } }, { threshold: 0.4 });
    sio.observe($('stats-row'));
  }

  // ---------- hero: the year as a wheel (one bar per week; length = premium, colour = phase) ----------
  (function ring() {
    const svg = $('ring'), tip = $('ringTip'), NS = 'http://www.w3.org/2000/svg';
    const n = weekly.length, R0 = 128, LMIN = 8, LMAX = 94, GAP = 0.018, step = 2 * Math.PI / n;
    const maxPrem = Math.max(...weekly.map(w => w.premium || 0));
    const pt = (r, a) => [r * Math.cos(a), r * Math.sin(a)];
    const sector = (r0, r1, a0, a1) => {
      const [x0, y0] = pt(r1, a0), [x1, y1] = pt(r1, a1), [x2, y2] = pt(r0, a1), [x3, y3] = pt(r0, a0);
      return `M${x0} ${y0}A${r1} ${r1} 0 0 1 ${x1} ${y1}L${x2} ${y2}A${r0} ${r0} 0 0 0 ${x3} ${y3}Z`;
    };
    const el = (tag, attrs) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); svg.appendChild(e); return e; };
    el('circle', { cx: 0, cy: 0, r: R0, fill: 'none', stroke: T.line, 'stroke-width': 1 });
    el('circle', { cx: 0, cy: 0, r: R0 + LMAX + 6, fill: 'none', stroke: 'rgba(148, 163, 196, 0.08)', 'stroke-width': 1, 'stroke-dasharray': '2 6' });
    let lastMonth = weekly[0].week_of.slice(0, 7), lastLabel = -99;   // label each month where it starts, never two labels within 3 weeks
    weekly.forEach((w, i) => {
      const a0 = -Math.PI / 2 + i * step + GAP / 2, a1 = a0 + step - GAP, mid = (a0 + a1) / 2, skipped = w.outcome === 'SKIPPED';
      const len = skipped ? LMIN : LMIN + (LMAX - LMIN) * (w.premium || 0) / maxPrem;
      el('path', { d: sector(R0 + 3, R0 + 3 + len, a0, a1), class: 'seg', 'data-i': i, style: `--i:${i}`,
        fill: skipped ? 'none' : (w.phase === 'CALL' ? T.call : T.put), stroke: skipped ? T.ink3 : 'none', 'stroke-dasharray': skipped ? '2 2' : 'none' });
      if (w.outcome === 'ASSIGNED' || /CALLED|EARLY/.test(w.outcome)) {
        const [mx, my] = pt(R0 - 12, mid);
        el('circle', { cx: mx, cy: my, r: 4, class: 'mark', style: `--i:${i}`, 'pointer-events': 'none',
          fill: w.outcome === 'ASSIGNED' ? T.ink : T.bg, stroke: T.ink, 'stroke-width': 1.5 });
      }
      const month = w.week_of.slice(0, 7);
      if (month !== lastMonth && i - lastLabel >= 3) {
        lastMonth = month; lastLabel = i;
        const [tx, ty] = pt(R0 - 31, a0 + step / 2);
        const t = el('text', { x: tx, y: ty, class: 'month', 'text-anchor': 'middle', 'dominant-baseline': 'middle' });
        t.textContent = new Date(w.week_of + 'T12:00:00').toLocaleString('en-US', { month: 'short' });
      }
    });
    const txt = (y, c, s) => { const t = el('text', { x: 0, y, class: c, 'text-anchor': 'middle' }); t.textContent = s; return t; };
    txt(-30, 'center-label', 'Final value');
    const big = txt(4, 'center-big', f(S.final_value, 'usd0'));
    txt(30, 'center-small', `${f(S.total_return, 'spct')} return`);
    txt(50, 'center-small', `Sharpe ${f(S.sharpe, 'dec2')}`);
    // hover a week to see its trade
    const segs = [...svg.querySelectorAll('.seg')], fig = svg.parentElement;
    const row = (k, v) => `<div class="row"><span>${k}</span><span>${v}</span></div>`;
    const showTip = (e, i) => {
      const w = weekly[i];
      segs.forEach((s2, j) => s2.classList.toggle('dim', j !== i));
      tip.innerHTML = `<b>Week of ${w.week_of}</b>` + (w.outcome === 'SKIPPED' ? row('Nothing sold', '—')
        : row(w.phase === 'PUT' ? 'Sold put' : 'Sold call', w.strike) + row('Premium', f(w.premium, 'usd2')) +
          row('Outcome', w.outcome.toLowerCase()) + row('Option P&L', f(w.seller_pnl, 'usd0')));
      tip.hidden = false;
      const b = fig.getBoundingClientRect();
      let x = e.clientX - b.left + 16, y = e.clientY - b.top + 16;
      if (x + 250 > b.width) x = e.clientX - b.left - 262;
      tip.style.left = `${x}px`; tip.style.top = `${y}px`;
    };
    const hide = () => { tip.hidden = true; segs.forEach(s2 => s2.classList.remove('dim')); };
    segs.forEach(s2 => { s2.addEventListener('pointermove', e => showTip(e, +s2.dataset.i)); s2.addEventListener('pointerleave', hide); });
    if (!REDUCE) { svg.classList.add('animate'); countUp(big, 1400); }
  })();

  // ================================================================= PART 1: LESSON
  // ---------- payoff diagram ----------
  const sold = weekly.filter(w => w.outcome !== 'SKIPPED' && isNum(w.iv_calendar));
  const pfWeek = $('pfWeek'), pfDays = $('pfDays'), pfParity = $('pfParity');
  pfWeek.innerHTML = sold.map((w, i) => `<option value="${i}">${w.week_of} · ${w.phase === 'PUT' ? 'put' : 'call'} ${w.strike} · ${w.outcome.toLowerCase()}</option>`).join('');
  pfWeek.value = String(Math.max(0, sold.findIndex(w => w.outcome === 'ASSIGNED')));
  let payoffChart;
  function drawPayoff() {
    const w = sold[+pfWeek.value];
    const right = w.phase === 'PUT' ? 'P' : 'C', K = w.strike, S0 = w.spot_entry, prem = w.fill, v = w.iv_calendar;
    const own = right === 'P' ? T.put : T.call, oth = right === 'P' ? T.call : T.put;
    const T0 = days(w.week_of, w.expiry);
    pfDays.max = T0;
    if (+pfDays.value > T0) pfDays.value = T0;
    const tl = +pfDays.value;
    $('pfDaysV').textContent = `${tl} of ${T0}`;
    const pnl = (s, tau, rt, p) => rt === 'P' ? 100 * (p - bs(s, K, tau / 365, R, Q, v, 'P'))
      : 100 * ((s - S0) + p - bs(s, K, tau / 365, R, Q, v, 'C'));
    const xs = Array.from({ length: 161 }, (_, i) => S0 * (0.94 + 0.12 * i / 160));
    const ds = [
      { label: `${right === 'P' ? 'Cash-secured put' : 'Covered call'} at expiry`, data: xs.map(s => ({ x: s, y: pnl(s, 0, right, prem) })), borderColor: own, borderWidth: 2.5, pointRadius: 0, glow: own },
      { label: `With ${tl} day${tl === 1 ? '' : 's'} left`, data: xs.map(s => ({ x: s, y: pnl(s, tl, right, prem) })), borderColor: own, borderDash: [5, 4], borderWidth: 1.6, pointRadius: 0 },
    ];
    let parityGap = null;
    if (pfParity.checked) {
      // the other leg at the same strike, priced with the same model; compare both at model prices
      const other = right === 'P' ? 'C' : 'P';
      const pOwn = bs(S0, K, T0 / 365, R, Q, v, right), pOther = bs(S0, K, T0 / 365, R, Q, v, other);
      ds.push({ label: `${other === 'P' ? 'Cash-secured put' : 'Covered call'}, same strike, at expiry`, data: xs.map(s => ({ x: s, y: pnl(s, 0, other, pOther) })),
        borderColor: oth, borderWidth: 2, borderDash: [2, 3], pointRadius: 0 });
      parityGap = pnl(S0, 0, right, pOwn) - pnl(S0, 0, other, pOther);
    }
    const ST = w.spot_expiry;
    const actual = right === 'P' ? 100 * (prem - Math.max(K - ST, 0)) : 100 * ((ST - S0) + prem - Math.max(ST - K, 0));
    const ys = ds.flatMap(d => d.data.map(p => p.y)), lo = Math.min(...ys), hi = Math.max(...ys);
    ds.push({ label: 'Strike', data: [{ x: K, y: lo }, { x: K, y: hi }], borderColor: T.ink3, borderWidth: 1, borderDash: [1, 3], pointRadius: 0 });
    ds.push({ type: 'scatter', label: `Actual: SPY ${f(ST, 'px')} → ${f(actual, 'usd0')}`, data: [{ x: ST, y: actual }], backgroundColor: T.ink, borderColor: T.bg, borderWidth: 2, pointRadius: 6, pointHoverRadius: 7, pointStyle: 'circle' });
    if (payoffChart) payoffChart.destroy();
    payoffChart = new Chart($('payoffChart'), { type: 'line', data: { datasets: ds }, options: { responsive: true,
      interaction: { mode: 'nearest', intersect: false },
      plugins: { legend: { align: 'start', labels: { filter: it => it.text !== 'Strike' } },
        tooltip: { callbacks: { title: it => `SPY ${f(it[0].parsed.x, 'px')}`, label: c => `${c.dataset.label}: ${f(c.parsed.y, 'usd0')}` } } },
      scales: { x: { type: 'linear', min: xs[0], max: xs[xs.length - 1], grid: { display: false }, title: { display: true, text: 'SPY price' }, ticks: { callback: v => Math.round(v) } },
        y: { title: { display: true, text: 'Position P&L per contract' }, ...money } } } });
    const be = right === 'P' ? K - prem : S0 - prem;
    const c = (k, val) => `<div class="pv-cell"><div class="k">${k}</div><div class="v">${val}</div></div>`;
    $('pfFacts').innerHTML = [
      c('Sold', `${w.week_of}, SPY ${f(S0, 'px')}`), c('Strike', K), c('Premium', `${f(prem, 'px')} · ${f(100 * prem, 'usd0')}`),
      c('Breakeven at expiry', f(be, 'px')), c('Most it can make', right === 'P' ? f(100 * prem, 'usd0') : f(100 * (K - S0 + prem), 'usd0')),
      c('Implied vol at sale', f(v, 'pct1')), c('Calendar days to expiry', T0), c('SPY at expiry', `${f(ST, 'px')} · ${w.outcome.toLowerCase()}`),
      c('Week P&L, this position', `<span class="${cls(actual)}">${f(actual, 'usd0')}</span>`),
    ].concat(parityGap === null ? [] : [c('Gap between the two lines', `${f(parityGap, 'usd2')}: interest on the cash minus the dividend, over the week`)]).join('');
  }
  [pfWeek, pfDays, pfParity].forEach(el => el.addEventListener('input', drawPayoff));
  drawPayoff();

  // ---------- Greek curves ----------
  const puts = sold.filter(w => w.phase === 'PUT');
  const med = a => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
  const gS = Math.round(med(puts.map(w => w.spot_entry))), gV = med(puts.map(w => w.iv_calendar));
  const TD = meta.target_delta, T7 = 7;                              // strike with put delta -target at 7 days (one week, as traded)
  let lo = 0.85 * gS, hi = gS;
  for (let i = 0; i < 60; i++) { const m = (lo + hi) / 2; (bsg(gS, m, T7 / 365, R, Q, gV, 'P').delta < -TD) ? (hi = m) : (lo = m); }
  const gK = Math.round((lo + hi) / 2);
  $('glS').textContent = `$${gS}`; $('glV').textContent = f(gV, 'pct1'); $('glK').textContent = `$${gK}`;
  const taus = [[7, '7 days'], [3, '3 days'], [1, '1 day'], [0.25, '6 hours']];
  const gx = Array.from({ length: 121 }, (_, i) => gK * (0.965 + 0.07 * i / 120));
  const gCharts = {};
  const gTitles = { delta: 'Delta: shares of SPY exposure', gamma: 'Gamma: change in delta per $1', theta: 'Theta: $ earned per day', vega: 'Vega: $ per 1-point rise in vol' };
  const gIds = { delta: 'gDelta', gamma: 'gGamma', theta: 'gTheta', vega: 'gVega' };
  function drawGreeks() {
    const cc = $('glCC').checked;
    Object.keys(gIds).forEach(k => {
      const series = taus.map(([t]) => gx.map(s => {
        const g = bsg(s, gK, t / 365, R, Q, gV, cc ? 'C' : 'P');
        const y = k === 'delta' ? (cc ? 100 - 100 * g.delta : -100 * g.delta) : -100 * g[k];
        return { x: s, y };
      }));
      const all = series.flat().map(p => p.y);
      if (gCharts[k]) gCharts[k].destroy();
      gCharts[k] = new Chart($(gIds[k]), { type: 'line', data: { datasets: taus.map(([, lab], i) => ({ label: lab, data: series[i], borderColor: RAMP[cc ? 'C' : 'P'][i], borderWidth: 1.8, pointRadius: 0 }))
        .concat([{ label: 'Strike', data: [{ x: gK, y: Math.min(...all) }, { x: gK, y: Math.max(...all) }], borderColor: T.ink3, borderDash: [1, 3], borderWidth: 1, pointRadius: 0 }]) },
        options: { responsive: true, interaction: { mode: 'nearest', intersect: false },
          plugins: { title: { display: true, text: `${gTitles[k]} · ${cc ? 'covered call' : 'short put'}` },
            legend: { align: 'start', labels: { font: { size: 11 }, padding: 10, filter: it => it.text !== 'Strike' } },
            tooltip: { callbacks: { title: it => `SPY ${f(it[0].parsed.x, 'px')}`, label: c => `${c.dataset.label}: ${f(c.parsed.y, 'dec2')}` } } },
          scales: { x: { type: 'linear', min: gx[0], max: gx[gx.length - 1], grid: { display: false }, ticks: { callback: v => Math.round(v), maxTicksLimit: 6 } } } } });
    });
  }
  $('glCC').addEventListener('change', drawGreeks);
  drawGreeks();

  // ---------- one full turn of the wheel ----------
  (function () {
    const i0 = weekly.findIndex(w => w.outcome === 'ASSIGNED');
    if (i0 < 0) { $('cycle').innerHTML = '<p>No put was assigned in this sample.</p>'; return; }
    const steps = [weekly[i0]];
    for (let i = i0 + 1; i < weekly.length; i++) { steps.push(weekly[i]); if (/CALLED|EARLY/.test(weekly[i].outcome)) break; }
    const last = steps[steps.length - 1], done = /CALLED|EARLY/.test(last.outcome), Kp = steps[0].strike;
    const prems = steps.reduce((a, w) => a + (w.premium || 0), 0);
    const items = steps.map((w, i) => {
      if (i === 0) return `<li><b>${w.week_of}</b>SPY at ${f(w.spot_entry, 'px')}. Sold the ${w.strike} put for ${f(w.fill, 'px')} (${f(w.premium, 'usd2')} after commission). SPY closed the week at ${f(w.spot_expiry, 'px')}, below the strike: <strong>assigned</strong>, bought 100 shares at ${w.strike}. Cost basis = ${w.strike} − ${f(w.fill, 'px')} = ${f(w.strike - w.fill, 'px')}.</li>`;
      if (w.outcome === 'SKIPPED') return `<li><b>${w.week_of}</b>No call with a bid cleared the cost-basis floor: nothing sold.</li>`;
      const end = w.outcome === 'EXPIRED' ? `SPY closed at ${f(w.spot_expiry, 'px')}, below the strike: expired worthless, kept the shares and the premium.`
        : `SPY closed at ${f(w.spot_expiry, 'px')}, above the strike: <strong>called away</strong>, sold the 100 shares at ${w.strike}.`;
      return `<li><b>${w.week_of}</b>SPY at ${f(w.spot_entry, 'px')}. Sold the ${w.strike} call (delta ${f(w.delta, 'dec2')}, floor ${f(w.floor, 'px')}) for ${f(w.fill, 'px')}. ${end}</li>`;
    });
    const sharePnl = 100 * (last.strike - Kp);
    $('cycle').innerHTML = `<p>The first time the wheel went all the way round in this backtest:</p><ol class="cycle-steps">${items.join('')}</ol>` +
      (done ? `<p>One turn took ${steps.length} weeks. Premiums collected: ${f(prems, 'usd2')}. Shares bought at ${Kp} and sold at ${last.strike}: ${f(sharePnl, 'usd0')}. Net for the turn: <strong>${f(prems + sharePnl, 'usd0')}</strong>, before interest on the cash. The account is back in State A and sells a put the following week.</p>` : '');
  })();

  // ================================================================= PART 2: RESULTS
  const cols = [['Wheel', S], ['SPY 100 sh + cash', B], ['SPY all-in', A]];
  const rows = [['Final value', 'final_value', 'usd0', true], ['Total return', 'total_return', 'spct'], ['Annualized return', 'annualized_return', 'pct2'],
    ['Annualized volatility', 'volatility', 'pct2'], ['Sharpe ratio', 'sharpe', 'dec2'], ['Max drawdown', 'max_drawdown', 'pct2'], ['Worst day', 'worst_day', 'pct2']];
  $('cmpTable').querySelector('thead').innerHTML = `<tr><th></th>${cols.map(c => `<th>${c[0]}</th>`).join('')}</tr>`;
  $('cmpTable').querySelector('tbody').innerHTML = rows.map(([lbl, key, k, dollars]) =>
    `<tr class="${key === 'sharpe' ? 'hl' : ''}"><td>${lbl}</td>${cols.map(c => `<td class="${cls(c[1][key])}">${f(c[1][key], k)}</td>`).join('')}</tr>`).join('') +
    `<tr><td>Beta to SPY (daily returns)</td>${cols.map((c, n) => `<td>${n === 0 ? f(M.beta_to_spy, 'dec2') : n === 1 ? f(M.beta_bh100, 'dec2') : n === 2 ? '1.00' : '—'}</td>`).join('')}</tr>`;

  const better = S.sharpe > B.sharpe, lowerVol = S.volatility < B.volatility, optNet = M.option_leg_net;
  $('verdict').innerHTML = `
    <p><strong>Sharpe:</strong> ${f(S.sharpe, 'dec2')} for the wheel against ${f(B.sharpe, 'dec2')} for SPY with the same share count
    (${f(A.sharpe, 'dec2')} all-in). ${better ? 'Higher, as the thesis predicted.' : 'Lower: the thesis fails on its main test this year.'}</p>
    <p><strong>Volatility:</strong> ${f(S.volatility, 'pct1')} against ${f(B.volatility, 'pct1')}. ${lowerVol ? 'Lower, as predicted.' : 'Not lower, against the prediction.'}
    <strong>Return:</strong> ${f(S.total_return, 'spct')} against ${f(B.total_return, 'spct')} (${f(A.total_return, 'spct')} all-in).
    ${S.total_return < A.total_return ? 'Below SPY all-in, as expected in a rising year.' : 'Above SPY all-in.'}</p>
    <p><strong>Did the options pay?</strong> Implied vol at sale ${f(VR.pooled_implied_vol, 'pct1')} against ${f(VR.pooled_realized_vol, 'pct1')} realized over the
    same days (implied above realized in ${VR.weeks_implied_above} of ${VR.n} weeks). Theta earned ${f(AT.theta, 'usd0')}; gamma paid ${f(-AT.gamma, 'usd0')}.
    The option leg ${optNet >= 0 ? 'made' : 'lost'} ${f(Math.abs(optNet), 'usd0')} net.</p>`;

  const dc = M.decomposition;
  $('decompTable').querySelector('tbody').innerHTML = [
    ['Premium received (after commissions)', M.premium_collected], ['Paid out at expiry / assignment', -M.option_payoff],
    ['<strong>Option leg net</strong>', dc.option_leg_net], ['Stock, while shares were held', dc.stock_pnl],
    ['Dividends', dc.dividends], ['Interest on cash', dc.interest], ['<strong>Total P&amp;L</strong>', S.pnl],
  ].map(([l, v]) => `<tr><td>${l}</td><td class="${cls(v)}">${f(v, 'usd0')}</td></tr>`).join('');
  const bp = VR.by_phase || {};
  $('vrpTable').querySelector('tbody').innerHTML = [
    ['Puts sold / calls sold', `${M.puts_sold} / ${M.calls_sold}`], ['Expired worthless', M.expired_worthless],
    ['Puts assigned', M.puts_assigned], ['Shares called away (early)', `${M.called_away} (${M.early_assignments})`],
    ['Weeks with nothing sold', M.weeks_skipped], ['Days holding shares', `${M.days_holding_shares} of ${ledger.length}`],
    ['Implied vol at sale (pooled)', f(VR.pooled_implied_vol, 'pct1')], ['Realized vol, same days', f(VR.pooled_realized_vol, 'pct1')],
    ['Put weeks: implied / realized', bp.PUT ? `${f(bp.PUT.implied, 'pct1')} / ${f(bp.PUT.realized, 'pct1')}` : '—'],
    ['Call weeks: implied / realized', bp.CALL ? `${f(bp.CALL.implied, 'pct1')} / ${f(bp.CALL.realized, 'pct1')}` : '—'],
  ].map(([l, v]) => `<tr><td>${l}</td><td>${v}</td></tr>`).join('');

  const labels = ledger.map(r => r.date);
  const events = {};
  blotter.forEach(r => { if (r.side === 'ASSIGN') events[r.time] = /^Put/.test(r.note) ? 'assigned' : 'away'; });
  const phaseCol = i => (ledger[i] && ledger[i].shares > 0 ? T.call : T.put);
  const initDs = { label: 'Reg T initial', data: ledger.map(r => r.regt_initial), borderColor: T.gamma, borderDash: [4, 3], borderWidth: 1.2, hidden: true };
  const maintDs = { label: 'Reg T maintenance', data: ledger.map(r => r.regt_maint), borderColor: T.vega, borderDash: [1, 3], borderWidth: 1.2, hidden: true };
  let navChart = null;
  lazy('navChart', () => {
    navChart = new Chart($('navChart'), { type: 'line', data: { labels, datasets: [
      { label: 'Wheel NAV', data: ledger.map(r => r.nav), borderColor: T.put, borderWidth: 2.4, glow: 'rgba(61, 139, 224, 0.5)',
        segment: { borderColor: c => phaseCol(c.p1DataIndex) },
        pointRadius: labels.map(d => (events[d] ? 4.5 : 0)), pointHoverRadius: 5, pointBorderColor: T.ink, pointBorderWidth: 1.5,
        pointBackgroundColor: labels.map(d => (events[d] === 'assigned' ? T.ink : T.bg)) },
      { label: 'SPY 100 sh + cash', data: ledger.map(r => r.bh100), borderColor: T.ink3, borderWidth: 1.4 },
      { label: 'SPY all-in', data: ledger.map(r => r.bh_all), borderColor: T.ink3, borderDash: [5, 4], borderWidth: 1.4 }, initDs, maintDs] },
      options: { responsive: true, ...drawIn(labels.length), interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `${c.dataset.label}: ${f(c.parsed.y, 'usd0')}` } } },
        scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8, maxRotation: 0 } }, y: money } } });
  });
  const toggle = (id, ds) => $(id).addEventListener('change', e => { ds.hidden = !e.target.checked; if (navChart) navChart.update('none'); });
  toggle('showInit', initDs); toggle('showMaint', maintDs);

  // ================================================================= PART 3: GREEKS
  const callPh = ledger.map(r => r.shares > 0);
  const xTime = n => ({ grid: { display: false }, ticks: { maxTicksLimit: n, maxRotation: 0 } });
  const fixW = { afterFit: s => { s.width = 64; } };   // same y-axis width, so the SPY strip lines up with the chart below it
  lazy('posDelta', () => {
    new Chart($('spyMini'), { type: 'line', data: { labels, datasets: [{ label: 'SPY close', data: ledger.map(r => r.close), borderColor: T.ink3, borderWidth: 1.3 }] },
      options: { responsive: true, ...drawIn(labels.length), interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `SPY close: ${f(c.parsed.y, 'px')}` } } },
        scales: { x: { display: false }, y: { ...fixW, ticks: { maxTicksLimit: 3 }, title: { display: true, text: 'SPY' } } } } });
    new Chart($('posDelta'), { type: 'line', data: { labels, datasets: [
      { label: 'Position delta, put phase', data: ledger.map((r, i) => (!callPh[i] ? r.pos_delta : null)), borderColor: T.put, borderWidth: 2, spanGaps: false },
      { label: 'Position delta, call phase', data: ledger.map((r, i) => (callPh[i] ? r.pos_delta : null)), borderColor: T.call, borderWidth: 2, spanGaps: false }] },
      options: { responsive: true, ...drawIn(labels.length), interaction: { mode: 'index', intersect: false },
        plugins: { legend: { align: 'start' }, tooltip: { callbacks: { label: c => `${c.dataset.label}: ${f(c.parsed.y, 'dec1')}` } } },
        scales: { x: xTime(10), y: { ...fixW, min: 0, max: 110, title: { display: true, text: 'shares of SPY' } } } } });
  });
  lazy('posTV', () => new Chart($('posTV'), { type: 'line', data: { labels, datasets: [
    { label: 'Theta ($ per day)', data: ledger.map(r => r.pos_theta), borderColor: T.theta, borderWidth: 1.5 },
    { label: 'Vega ($ per vol point)', data: ledger.map(r => r.pos_vega), borderColor: T.vega, borderWidth: 1.5 }] },
    options: { responsive: true, ...drawIn(labels.length), interaction: { mode: 'index', intersect: false },
      plugins: { title: { display: true, text: 'Theta and vega of the position' }, legend: { align: 'start' } },
      scales: { x: xTime(4), y: money } } }));
  lazy('posGamma', () => new Chart($('posGamma'), { type: 'line', data: { labels, datasets: [
    { label: 'Gamma (change in delta per $1 in SPY)', data: ledger.map(r => r.pos_gamma), borderColor: T.gamma, borderWidth: 1.5 }] },
    options: { responsive: true, ...drawIn(labels.length), interaction: { mode: 'index', intersect: false },
      plugins: { title: { display: true, text: 'Gamma of the position' }, legend: { align: 'start' } },
      scales: { x: xTime(4) } } }));

  const attrDs = [['theta', 'Theta: time decay', T.theta, 2], ['gamma', 'Gamma: curvature of spot moves', T.gamma, 2],
    ['delta', 'Delta: straight-line spot moves', '#b3bccf', 1.5], ['vega', 'Vega: implied vol changes', T.vega, 1.5],
    ['costs', 'Commissions', '#66728f', 1.3], ['residual', 'Residual', '#46516b', 1.3]];
  lazy('attrChart', () => new Chart($('attrChart'), { type: 'line', data: { labels: AC.map(r => r.date), datasets: attrDs.map(([k, lab, col, w]) => ({ label: lab,
    data: AC.map(r => (k === 'costs' ? r.spread + r.commission : r[k])), borderColor: col, borderWidth: w,
    borderDash: k === 'costs' ? [4, 3] : k === 'residual' ? [1, 3] : [] }))
    .concat([{ label: 'Option leg, actual', data: AC.map(r => r.actual), borderColor: T.ink, borderWidth: 2.8, glow: 'rgba(231, 236, 246, 0.35)' }]) },
    options: { responsive: true, ...drawIn(AC.length), interaction: { mode: 'index', intersect: false },
      plugins: { title: { display: true, text: 'Cumulative P&L of the short options, by source' }, legend: { align: 'start' },
        tooltip: { callbacks: { label: c => `${c.dataset.label}: ${f(c.parsed.y, 'usd0')}` } } },
      scales: { x: xTime(8), y: money } } }));
  $('attrTable').querySelector('tbody').innerHTML = [
    ['Theta: time decay', AT.theta], ['Gamma: curvature of spot moves', AT.gamma], ['Delta: straight-line spot moves', AT.delta],
    ['Vega: implied vol changes', AT.vega], ['Commissions', AT.commission], ['Residual', AT.residual],
    ['<strong>Option leg, actual</strong>', AT.actual],
  ].map(([l, v]) => `<tr><td>${l}</td><td class="${cls(v)}">${f(v, 'usd0')}</td></tr>`).join('');
  const tg = AT.theta + AT.gamma, usd = v => f(Math.abs(v), 'usd0');
  $('attrText').innerHTML = `<p>Over the year, the passing of time earned the short options <strong>${usd(AT.theta)}</strong>
    (theta). SPY's moves cost them <strong>${usd(AT.gamma)}</strong> (gamma). ${tg < 0
      ? `That is more than time earned, so on these two alone the options lost ${usd(tg)}.`
      : `So on these two alone the options kept ${usd(tg)}.`}</p>
    <p>The other two pieces: implied volatility ${AT.vega >= 0
      ? `fell while the options were open, which made them cheaper to buy back, a gain of ${usd(AT.vega)} for the seller (vega)`
      : `rose while the options were open, which made them more expensive to buy back, a loss of ${usd(AT.vega)} for the seller (vega)`},
    and SPY's overall direction ${AT.delta >= 0 ? 'added' : 'cost'} ${usd(AT.delta)} (delta). After ${usd(AT.commission)} of commissions${Math.abs(AT.residual) >= 1 ? `, and ${usd(AT.residual)} the model could not split` : ''},
    the options finished ${AT.actual >= 0 ? 'up' : 'down'} <strong>${usd(AT.actual)}</strong> for the year.</p>`;


  // ================================================================= PORTFOLIO VIEWER
  const byDate = {};
  blotter.forEach(r => (byDate[r.time] = byDate[r.time] || []).push(r));
  const range = $('pvRange'); range.max = ledger.length - 1;
  const jump = $('pvJump');
  const opts = [['', 'Jump to an event…'], [String(ledger.length - 1), `Last close (${labels[labels.length - 1]})`]];
  blotter.forEach(r => {
    if (r.side === 'ASSIGN' || r.side === 'DIVIDEND') {
      const i = labels.indexOf(r.time);
      if (i >= 0) opts.push([String(i), `${r.time} · ${r.side === 'DIVIDEND' ? 'dividend paid' : (/^Put/.test(r.note) ? 'put assigned' : 'shares called away')}`]);
    }
  });
  jump.innerHTML = opts.map(([v, t]) => `<option value="${v}">${t}</option>`).join('');
  const cell = (k, v, key) => `<div class="pv-cell${key ? ' key' : ''}"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  function show(i) {
    i = Math.max(0, Math.min(ledger.length - 1, i)); range.value = i;
    const r = ledger[i];
    $('pvDate').textContent = r.date;
    const opt = r.short_put ? `Short put ${r.short_put}` : r.short_call ? `Short call ${r.short_call}` : 'none';
    $('pvGrid').innerHTML = [
      cell('SPY close', f(r.close, 'px')), cell('Cash', f(r.cash, 'usd2')), cell('Shares', `${r.shares} · ${f(r.stock_value, 'usd0')}`),
      cell('Cost basis / share', r.shares ? f(r.cost_basis, 'px') : '—'), cell('Open option', opt),
      cell('Option buyback (mid)', r.option_mark != null ? `${f(r.option_mark, 'px')} · ${f(r.option_value, 'usd0')}` : '—'),
      cell('Accrued interest', f(r.accrued_interest, 'usd2')), cell('Dividend receivable', f(r.div_receivable, 'usd2')),
      cell('NAV', f(r.nav, 'usd2'), true), cell('Put collateral', f(r.put_collateral, 'usd0')), cell('Free cash', f(r.free_cash, 'usd0')),
      cell('Reg T initial', f(r.regt_initial, 'usd0')), cell('Reg T maintenance', f(r.regt_maint, 'usd0')),
      cell('Available funds', `<span class="${cls(r.available)}">${f(r.available, 'usd0')}</span>`),
      cell('Excess equity', `<span class="${cls(r.excess)}">${f(r.excess, 'usd0')}</span>`),
      cell('Implied vol (open option)', f(r.iv, 'pct1')),
      cell('Position delta', `${f(r.pos_delta, 'dec1')} sh · ${f(r.dollar_delta, 'usd0')}`, true),
      cell('Gamma (Δ per $1)', f(r.pos_gamma, 'dec2')), cell('Theta ($/day)', f(r.pos_theta, 'usd2')), cell('Vega ($/vol pt)', f(r.pos_vega, 'usd2')),
      cell('SPY 100 sh + cash', f(r.bh100, 'usd0')),
    ].join('');
    const t = byDate[r.date] || [];
    $('pvTrades').querySelector('tbody').innerHTML = t.length ? t.map(b => `<tr><td>${b.instrument}</td><td class="side-${b.side}">${b.side}</td>
      <td>${b.qty ?? '—'}</td><td>${f(b.fill, 'px')}</td><td class="${cls(b.cash_delta)}">${f(b.cash_delta, 'usd2')}</td><td>${b.note}</td></tr>`).join('')
      : '<tr><td colspan="6">No trades this day; positions marked to the close.</td></tr>';
  }
  range.addEventListener('input', e => show(+e.target.value));
  $('pvPrev').addEventListener('click', () => show(+range.value - 1));
  $('pvNext').addEventListener('click', () => show(+range.value + 1));
  jump.addEventListener('change', e => { if (e.target.value !== '') show(+e.target.value); e.target.value = ''; });
  show(ledger.length - 1);

  // ================================================================= FILLS
  lazy('locChart', () => new Chart($('locChart'), { type: 'bar', data: { labels: F.trades.loc_bins, datasets: [{ data: F.trades.loc_hist,
    borderRadius: 4, borderSkipped: 'bottom', backgroundColor: F.trades.loc_bins.map(b => /at bid|at ask/.test(b) ? T.gamma : /%/.test(b) ? T.put : T.dim) }] },
    options: { responsive: true, plugins: { legend: { display: false }, title: { display: true, text: 'Where the last trade printed vs the closing quote' } },
      scales: { x: { grid: { display: false } }, y: { title: { display: true, text: 'quotes' } } } } }));
  const pts = F.scatter.map(p => ({ x: p.mid, y: p.trade })), mx = Math.max(...pts.map(p => p.x)), reg = F.trades.regression;
  lazy('scatterChart', () => new Chart($('scatterChart'), { data: { datasets: [
    { type: 'scatter', label: 'Near-the-money quotes', data: pts, backgroundColor: 'rgba(61, 139, 224, 0.35)', pointRadius: 2 },
    { type: 'line', label: `Fit, R² = ${f(reg.r2, 'dec4')}`, data: [{ x: 0, y: reg.intercept }, { x: mx, y: reg.slope * mx + reg.intercept }], borderColor: T.ink, borderWidth: 1.5, pointRadius: 0 }] },
    options: { responsive: true, plugins: { legend: { align: 'start' } },
      scales: { x: { type: 'linear', title: { display: true, text: 'Mid = (BID + ASK) / 2' } }, y: { title: { display: true, text: 'TRDPRC_1 (last trade)' } } } } }));

  // ================================================================= WEEKLY, BLOTTER, LEDGER
  $('weeklyTable').querySelector('tbody').innerHTML = weekly.map(w => `<tr>
    <td>${w.week_of}</td><td><span class="phase ${w.phase}">${w.phase}</span></td><td>${f(w.spot_entry, 'px')}</td><td>${w.floor != null ? f(w.floor, 'px') : '—'}</td>
    <td>${w.strike != null ? w.strike : '—'}</td><td>${f(w.delta, 'dec3')}</td><td>${w.bid != null ? `${f(w.bid, 'px')} / ${f(w.ask, 'px')}` : '—'}</td>
    <td>${f(w.premium, 'usd2')}</td><td class="side-${(w.outcome || '').split(' ')[0]}">${w.outcome || '—'}</td><td>${f(w.spot_expiry, 'px')}</td>
    <td>${f(w.payoff, 'usd0')}</td><td class="${cls(w.seller_pnl)}">${f(w.seller_pnl, 'usd0')}</td>
    <td>${isNum(w.implied_move) ? '±' + f(w.implied_move, 'px') : '—'}</td>
    <td class="${isNum(w.realized_move) && w.realized_move > w.implied_move ? 'neg' : ''}">${isNum(w.realized_move) ? '±' + f(w.realized_move, 'px') : '—'}</td></tr>`).join('');

  const groups = { All: () => true, Options: r => /\.U/.test(r.instrument) || r.instrument === 'OPTION', Shares: r => r.instrument === meta.ticker,
    'Cash (deposit, interest, dividends)': r => ['DEPOSIT', 'INTEREST', 'DIVIDEND'].includes(r.side) };
  const fb = $('blotterFilters');
  const drawBlotter = g => {
    fb.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.g === g));
    $('blotterTable').querySelector('tbody').innerHTML = blotter.filter(groups[g]).map(r => `<tr><td>${r.time}</td><td>${r.instrument}</td>
      <td class="side-${r.side}">${r.side}</td><td>${r.qty ?? '—'}</td><td>${f(r.limit, 'px')}</td><td>${f(r.fill, 'px')}</td>
      <td class="${cls(r.cash_delta)}">${f(r.cash_delta, 'usd2')}</td><td>${r.note}</td></tr>`).join('');
  };
  fb.innerHTML = Object.keys(groups).map(g => `<button data-g="${g}">${g} (${blotter.filter(groups[g]).length})</button>`).join('');
  fb.addEventListener('click', e => { if (e.target.dataset.g) drawBlotter(e.target.dataset.g); });
  drawBlotter('All');

  $('ledgerTable').querySelector('tbody').innerHTML = ledger.map(r => `<tr><td>${r.date}</td><td>${f(r.close, 'px')}</td><td>${f(r.cash, 'usd2')}</td>
    <td>${r.shares}</td><td>${f(r.stock_value, 'usd0')}</td><td>${r.short_put || '—'}</td><td>${r.short_call || '—'}</td><td>${f(r.option_value, 'usd0')}</td>
    <td>${f(r.div_receivable, 'usd2')}</td><td>${f(r.nav, 'usd2')}</td><td>${f(r.put_collateral, 'usd0')}</td><td class="${cls(r.free_cash)}">${f(r.free_cash, 'usd0')}</td>
    <td>${f(r.regt_initial, 'usd0')}</td><td>${f(r.regt_maint, 'usd0')}</td><td class="${cls(r.available)}">${f(r.available, 'usd0')}</td>
    <td class="${cls(r.excess)}">${f(r.excess, 'usd0')}</td><td>${f(r.pos_delta, 'dec1')}</td><td>${f(r.pos_theta, 'usd0')}</td></tr>`).join('');
  const neg = M.min_available < 0 || M.min_free_cash < 0;
  $('regtNote').textContent = neg
    ? `Available funds or free cash went negative (minimum ${f(M.min_available, 'usd0')} / ${f(M.min_free_cash, 'usd0')}): on those days the account could not have put the trade on as written.`
    : `Lowest available funds over the year: ${f(M.min_available, 'usd0')}; lowest free cash: ${f(M.min_free_cash, 'usd0')}. Neither went negative, so every put was fully cash-secured and every trade could have been put on.`;
  const navLinks = [...document.querySelectorAll('.topbar nav a[href^="#"]')];
  if ('IntersectionObserver' in window) {
    const byId = Object.fromEntries(navLinks.map(a => [a.getAttribute('href').slice(1), a]));
    const visible = new Set();
    const spy = new IntersectionObserver(es => {
      es.forEach(e => (e.isIntersecting ? visible.add(e.target.id) : visible.delete(e.target.id)));
      const current = Object.keys(byId).find(id => visible.has(id));
      navLinks.forEach(a => a.classList.toggle('active', a === byId[current]));
    }, { rootMargin: '-40% 0px -55% 0px' });
    Object.keys(byId).forEach(id => { const sec = document.getElementById(id); if (sec) spy.observe(sec); });
  }
})();
