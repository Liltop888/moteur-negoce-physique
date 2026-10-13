// Outils interactifs de Comptoir : rendement par baril et simulateur de couverture.
(function () {
  const $ = (id) => document.getElementById(id);
  const fr = (v, d = 2) => v.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const usd = (v, d = 2) => (v < 0 ? "−" : "") + fr(Math.abs(v), d) + " $";
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  // ---------------------------------------------------------- 1. Rendement net par baril
  const R = ["prix", "decote", "api", "soufre", "km", "jours", "taux", "pd", "lgd", "vol"];
  const fmt = {
    prix: (v) => fr(v, 0) + " $/b", decote: (v) => fr(v, 1) + " $/b", api: (v) => fr(v, 1) + "°",
    soufre: (v) => fr(v, 2) + " %", km: (v) => fr(v, 0) + " km", jours: (v) => fr(v, 0) + " j",
    taux: (v) => fr(v, 1) + " %", pd: (v) => fr(v, 0) + " %", lgd: (v) => fr(v, 0) + " %",
    vol: (v) => fr(v, 0) + " b/j",
  };

  function rendement() {
    const x = {};
    R.forEach((k) => { x[k] = parseFloat($("r-" + k).value); $("o-" + k).textContent = fmt[k](x[k]); });
    const qualite = -(Math.max(35 - x.api, 0) * 0.15 + Math.max(x.api - 45, 0) * 0.10) - x.soufre * 0.6;
    const transport = 0.8 + 0.008 * x.km * 1.25;
    const financement = x.prix * (x.taux / 100) * x.jours / 365;
    const perte = (x.pd / 100) * (x.jours / 365) * (x.lgd / 100) * x.prix;
    const net = x.decote + qualite - transport - financement - perte;
    const items = [
      ["Remise obtenue", x.decote], ["Qualité du pétrole", qualite], ["Transport", -transport],
      ["Argent bloqué", -financement], ["Risque de faillite", -perte],
    ];
    const max = Math.max(...items.map((i) => Math.abs(i[1])), 0.01);
    $("r-bars").innerHTML = items.map(([l, v]) =>
      `<div class="bar"><span>${l}</span><span class="track"><span class="fill" style="left:0;width:${(Math.abs(v) / max * 100).toFixed(1)}%;background:${v >= 0 ? "var(--pos)" : "var(--neg)"}"></span></span><span class="v">${v >= 0 ? "+" : "−"}${fr(Math.abs(v))}</span></div>`
    ).join("");
    const el = $("r-net");
    el.textContent = usd(net) + " / baril";
    el.className = "big " + (net >= 0 ? "pos" : "neg");
    const profit = net * x.vol * 365 / 1e6;
    const capital = x.prix * x.vol * x.jours / 1e6;
    $("r-profit").textContent = (profit < 0 ? "−" : "") + fr(Math.abs(profit), 1) + " M$";
    $("r-capital").textContent = fr(capital, 1) + " M$";
    $("r-roc").textContent = capital > 0 ? fr(profit / capital * 100, 0) + " %" : "—";
  }
  if ($("f-rend")) {
    R.forEach((k) => $("r-" + k).addEventListener("input", rendement));
    rendement();
  }

  // ---------------------------------------------------------- 2. Simulateur de couverture
  const C = ["s0", "lt", "k", "sig", "j", "m"];
  const cfmt = {
    s0: (v) => fr(v, 0) + " $", lt: (v) => fr(v, 0) + " $", k: (v) => fr(v, 2), sig: (v) => fr(v * 100, 0) + " %",
    j: (v) => fr(v, 0) + " j", m: (v) => fr(v, 1) + " $/b",
  };
  let seed = 7;
  function rand() { // générateur pseudo-aléatoire reproductible (mulberry32)
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  function normal() { // Box-Muller
    let u = 0; while (u === 0) u = rand();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand());
  }
  function stats(a) {
    const s = Float64Array.from(a).sort();
    const mean = a.reduce((p, v) => p + v, 0) / a.length;
    const n5 = Math.max(1, Math.floor(a.length * 0.05));
    let worst = 0; for (let i = 0; i < n5; i++) worst += s[i];
    return { mean, ploss: a.filter((v) => v < 0).length / a.length, cvar: worst / n5, s };
  }
  function couverture(newSeed) {
    const x = {};
    C.forEach((k) => { x[k] = parseFloat($("c-" + k).value); $("o-" + k).textContent = cfmt[k](x[k]); });
    if (newSeed) seed = Math.floor(Math.random() * 1e9); else seed = 7;
    const N = 20000, T = x.j / 365, mu = Math.log(x.lt), x0 = Math.log(x.s0);
    const a = Math.exp(-x.k * T);
    const sd = x.k > 1e-6 ? x.sig * Math.sqrt((1 - Math.exp(-2 * x.k * T)) / (2 * x.k)) : x.sig * Math.sqrt(T);
    const nc = new Array(N), cv = new Array(N);
    for (let i = 0; i < N; i++) {
      const st = Math.exp(x0 * a + mu * (1 - a) + sd * normal()); // solution exacte d'Ornstein-Uhlenbeck
      nc[i] = x.m + (st - x.s0);
      cv[i] = x.m + 0.6 * normal();
    }
    const A = stats(nc), B = stats(cv);
    const put = (p, s) => {
      $("c-" + p + "-m").textContent = usd(s.mean);
      $("c-" + p + "-p").textContent = fr(s.ploss * 100, 1) + " %";
      $("c-" + p + "-c").textContent = usd(s.cvar);
    };
    put("nc", A); put("c", B);
    draw(A.s, B.s);
  }
  function draw(a, b) {
    const cv = $("c-hist"), ctx = cv.getContext("2d");
    const W = cv.width, H = cv.height, L = 50, Rm = 14, Tm = 14, Bm = 40;
    ctx.clearRect(0, 0, W, H);
    const lo = Math.min(a[Math.floor(a.length * 0.005)], b[0], -2), hi = Math.max(a[Math.floor(a.length * 0.995)], b[b.length - 1], 2);
    const nb = 60, w = (hi - lo) / nb;
    const hist = (s) => { const h = new Array(nb).fill(0); s.forEach((v) => { const i = Math.floor((v - lo) / w); if (i >= 0 && i < nb) h[i]++; }); return h.map((c) => c / s.length); };
    const ha = hist(a), hb = hist(b), ma = Math.max(...ha) * 1.08, mb = Math.max(...hb) * 1.08;
    let ymax = ma;
    const X = (v) => L + (v - lo) / (hi - lo) * (W - L - Rm), Y = (p) => Tm + (1 - p / ymax) * (H - Tm - Bm);
    ctx.font = "20px IBM Plex Mono, monospace"; ctx.fillStyle = css("--muted"); ctx.strokeStyle = css("--rule"); ctx.lineWidth = 1;
    const step = (hi - lo) > 40 ? 10 : 5;
    for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) {
      ctx.beginPath(); ctx.moveTo(X(t), Tm); ctx.lineTo(X(t), H - Bm); ctx.stroke();
      ctx.textAlign = "center"; ctx.fillText((t > 0 ? "+" : "") + t, X(t), H - 12);
    }
    ctx.strokeStyle = css("--ink"); ctx.beginPath(); ctx.moveTo(X(0), Tm); ctx.lineTo(X(0), H - Bm); ctx.stroke();
    const bars = (h, color, alpha) => {
      ctx.globalAlpha = alpha; ctx.fillStyle = color;
      h.forEach((p, i) => { if (p > 0) { const x0 = X(lo + i * w), x1 = X(lo + (i + 1) * w); ctx.fillRect(x0, Y(p), Math.max(1, x1 - x0 - 1), H - Bm - Y(p)); } });
      ctx.globalAlpha = 1;
    };
    ymax = ma; bars(ha, css("--amber"), 0.75);
    ymax = mb; bars(hb, css("--accent"), 0.6);
    ctx.fillStyle = css("--muted"); ctx.textAlign = "left"; ctx.fillText("résultat en $ par baril (hauteurs normalisées)", L, Tm + 16);
    $("lg-nc").style.background = css("--amber"); $("lg-c").style.background = css("--accent");
  }
  if ($("f-couv")) {
    C.forEach((k) => $("c-" + k).addEventListener("input", () => couverture(false)));
    $("c-run").addEventListener("click", () => couverture(true));
    couverture(false);
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => couverture(false));
  }
})();
