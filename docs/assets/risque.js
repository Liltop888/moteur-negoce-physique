// « Négocie ton baril » : ticket de caisse interactif et simulation d'une année de préfinancement.
// Même modèle que src/m2/deal.py : prix de Schwartz (Ornstein-Uhlenbeck sur le log-prix), défaut de Cox
// d'intensité λ0·(S/65,47)^(−β), récupération de 50 % des réserves, plancher sur le prix moyen.
(function () {
  const $ = (id) => document.getElementById(id);
  if (!$("ng-ticket")) return;
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const fr = (v, d = 2) => v.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const usd = (v) => (v < 0 ? "−" : "+") + fr(Math.abs(v)) + " $";

  const K_ = 0.8995, SIG = 0.5185, LT = 65.47, S0 = 96.24, R = 0.04, REC = 0.5, DT = 1 / 12;
  const MU = Math.log(LT), A = Math.exp(-K_ * DT), SD = SIG * Math.sqrt((1 - A * A) / (2 * K_));
  const N = 6000;

  // générateur reproductible
  function rng(seed) {
    let s = seed >>> 0;
    const u = () => { s = (s + 0x6d2b79f5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
    return () => { let a = 0; while (a === 0) a = u(); return Math.sqrt(-2 * Math.log(a)) * Math.cos(2 * Math.PI * u()); };
  }
  // trajectoires communes (antithétiques), 12 mois
  const P = new Float64Array(N * 12);
  (function () {
    const g = rng(20261012);
    for (let i = 0; i < N / 2; i++) {
      let x1 = Math.log(S0), x2 = Math.log(S0);
      for (let k = 0; k < 12; k++) {
        const z = g();
        x1 = x1 * A + MU * (1 - A) + SD * z; x2 = x2 * A + MU * (1 - A) - SD * z;
        P[i * 12 + k] = Math.exp(x1); P[(i + N / 2) * 12 + k] = Math.exp(x2);
      }
    }
  })();
  // (S/65,47)^(−3) précalculé : le calcul suit le curseur sans ralentir
  const W3 = new Float64Array(N * 12);
  for (let j = 0; j < N * 12; j++) { const q = LT / P[j]; W3[j] = q * q * q; }
  const w = (j, beta) => (beta ? W3[j] : 1);
  const F = [], T_ = [];
  for (let k = 1; k <= 12; k++) {
    const t = k * DT, m = Math.log(S0) * Math.exp(-K_ * t) + MU * (1 - Math.exp(-K_ * t));
    const v = SIG * SIG * (1 - Math.exp(-2 * K_ * t)) / (2 * K_);
    F.push(Math.exp(m + v / 2)); T_.push(t);
  }

  function lam0For(pd, beta) {
    // probabilité de défaut à un an = pd, en moyenne sur les trajectoires
    const f = (l0) => {
      let s = 0;
      for (let i = 0; i < N; i++) {
        let H = 0;
        for (let k = 0; k < 12; k++) H += l0 * w(i * 12 + k, beta) * DT;
        s += 1 - Math.exp(-H);
      }
      return s / N - pd;
    };
    if (pd <= 0) return 0;
    let lo = 1e-5, hi = 50;
    for (let it = 0; it < 40; it++) { const mid = Math.sqrt(lo * hi); if (f(mid) > 0) hi = mid; else lo = mid; }
    return Math.sqrt(lo * hi);
  }

  let cacheKey = "", cacheL0 = 0;
  function compute(x) {
    const T = x.duree, beta = x.lie ? 3 : 0;
    const key = x.pd + "|" + beta;
    if (key !== cacheKey) { cacheL0 = lam0For(x.pd / 100, beta); cacheKey = key; }
    const l0 = cacheL0;
    const av = F.slice(0, T).map((f) => f - x.remise);
    const advRest = av.map((_, k) => av.slice(k).reduce((a, b) => a + b, 0));
    let cva = 0, floor = 0;
    for (let i = 0; i < N; i++) {
      let surv = 1, path = 0, sum = 0;
      for (let k = 0; k < T; k++) {
        const S = P[i * 12 + k];
        sum += S;
        const lam = l0 * w(i * 12 + k, beta);
        const s2 = surv * Math.exp(-lam * DT);
        const loss = Math.max(advRest[k] - REC * (T - k) * S, 0);
        path += (surv - s2) * loss * Math.exp(-R * T_[k]);
        surv = s2;
      }
      cva += path;
      if (x.plancher > 0) floor += Math.max(x.plancher - sum / T, 0);
    }
    cva = cva / N / T;
    floor = x.plancher > 0 ? Math.exp(-R * T / 12) * floor / N : 0;
    const fin = av.reduce((a, v, k) => a + v * (Math.exp(R * T_[k]) - 1), 0) / T;
    const net = x.remise - cva - fin - floor;
    const capital = (av.reduce((a, b) => a + b, 0) / T) * 30.4 * (T + 1) / 2;   // pour 1 baril/jour
    return { cva, fin, floor, net, roc: net * 365 / capital, l0, av };
  }

  // ---------------------------------------------------------------- interface
  const ids = ["remise", "duree", "plancher", "pd"];
  const fmt = { remise: (v) => fr(v) + " $", duree: (v) => v + " mois", plancher: (v) => (v > 0 ? fr(v, 0) + " $" : "aucun"), pd: (v) => fr(v, 0) + " %" };
  function read() {
    const x = {};
    ids.forEach((k) => { x[k] = parseFloat($("ng-" + k).value); const o = $("ngo-" + k); if (o) o.textContent = fmt[k](x[k]); });
    x.lie = $("ng-lie").checked;
    return x;
  }
  const shown = {};
  function animateTo(id, val, signed = true) {
    const el = $(id), from = shown[id] ?? val, t0 = performance.now();
    shown[id] = val;
    const step = (t) => {
      const p = Math.min(1, (t - t0) / 350), e = 1 - Math.pow(1 - p, 3), v = from + (val - from) * e;
      el.textContent = signed ? usd(v) : (v < 0 ? "−" : "") + fr(Math.abs(v)) + " $";
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  let last = null;
  function update() {
    const x = read();
    const r = compute(x); last = { x, r };
    animateTo("ngv-remise", x.remise);
    animateTo("ngv-cva", -r.cva); animateTo("ngv-fin", -r.fin); animateTo("ngv-floor", -r.floor);
    animateTo("ngv-net", r.net, false);
    const tot = $("ng-total");
    tot.classList.toggle("perte", r.net < 0);
    const pct = fr(r.roc * 100, 0);
    $("ng-verdict").textContent = r.net < 0
      ? "Affaire perdante : les risques coûtent plus que la remise."
      : r.roc < 0.08 ? `Mauvaise affaire : ton argent ne rapporte qu'environ ${pct} % par an, pour beaucoup de risque.`
      : r.roc < 0.2 ? `Correct : ton argent rapporte environ ${pct} % par an.`
      : `Bonne affaire : ton argent rapporte environ ${pct} % par an.`;
    $("ng-row-floor").style.opacity = x.plancher > 0 ? 1 : 0.45;
    // barre de répartition
    const parts = [["cva", r.cva], ["fin", r.fin], ["floor", r.floor]], tot2 = Math.max(x.remise, 0.01);
    parts.forEach(([k, v]) => { $("ngb-" + k).style.width = Math.min(100, (v / tot2) * 100) + "%"; });
    $("ngb-net").style.width = Math.max(0, (r.net / tot2) * 100) + "%";
  }
  let pending = false;
  const schedule = () => { if (!pending) { pending = true; requestAnimationFrame(() => { pending = false; update(); }); } };
  ids.forEach((k) => $("ng-" + k).addEventListener("input", schedule));
  $("ng-lie").addEventListener("change", update);
  document.querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => {
    const p = JSON.parse(b.dataset.preset);
    Object.entries(p).forEach(([k, v]) => { if (k === "lie") $("ng-lie").checked = v; else $("ng-" + k).value = v; });
    update();
  }));
  update();

  // ---------------------------------------------------------------- « Joue l'année »
  const cv = $("ng-canvas"), ctx = cv.getContext("2d");
  let anim = null;
  function play() {
    if (!last) return;
    const { x, r } = last, T = x.duree, beta = x.lie ? 3 : 0;
    const g = rng((Math.random() * 1e9) | 0), u = Math.random;
    const path = []; let lx = Math.log(S0);
    for (let k = 0; k < T; k++) { lx = lx * A + MU * (1 - A) + SD * g(); path.push(Math.exp(lx)); }
    // instant de défaut
    let defaultAt = -1, surv = 1;
    for (let k = 0; k < T; k++) {
      const lam = r.l0 * Math.pow(path[k] / LT, -beta), s2 = surv * Math.exp(-lam * DT);
      if (defaultAt < 0 && u() < 1 - s2 / surv) defaultAt = k;
      surv = s2;
    }
    const advRest = r.av.map((_, k) => r.av.slice(k).reduce((a, b) => a + b, 0));
    cancelAnimationFrame(anim);
    const t0 = performance.now(), per = 650;
    $("ng-play").disabled = true;
    const log = $("ng-log"); log.innerHTML = "";
    let shownMonths = -1;
    const frame = (t) => {
      const m = Math.min(T, (t - t0) / per);
      drawYear(path, m, defaultAt, x);
      const done = Math.floor(m);
      while (shownMonths < done - 1 || (m >= T && shownMonths < T - 1)) {
        shownMonths++;
        const k = shownMonths, S = path[k];
        if (defaultAt >= 0 && k >= defaultAt) {
          if (k === defaultAt) {
            const loss = Math.max(advRest[k] - REC * (T - k) * S, 0);
            log.insertAdjacentHTML("beforeend", `<li class="bad">Mois ${k + 1} : le pétrole est à ${fr(S, 0)} $, le producteur fait faillite. Tu récupères la moitié de ses réserves : perte de ${fr(loss / T)} $ par baril prévu.</li>`);
          }
          break;
        }
        log.insertAdjacentHTML("beforeend", `<li>Mois ${k + 1} : pétrole à ${fr(S, 0)} $, baril livré ✓</li>`);
      }
      if (m < T && !(defaultAt >= 0 && m > defaultAt + 1)) anim = requestAnimationFrame(frame);
      else finish(path, defaultAt, x, r, advRest);
    };
    anim = requestAnimationFrame(frame);
  }
  function finish(path, d, x, r, advRest) {
    const T = x.duree;
    const delivered = d >= 0 ? d : T;
    let res = delivered * x.remise;                                   // gain sur les barils livrés
    res -= r.fin * T;                                                  // coût de l'argent avancé
    if (d >= 0) res -= Math.max(advRest[d] - REC * (T - d) * path[d], 0);
    let floorPay = 0;
    if (x.plancher > 0 && d < 0) floorPay = Math.max(x.plancher - path.reduce((a, b) => a + b, 0) / T, 0);
    res -= floorPay;
    const perB = res / T;
    const box = $("ng-result");
    box.className = "ng-result " + (perB >= 0 ? "ok" : "ko");
    box.innerHTML = (d >= 0 ? "Faillite au mois " + (d + 1) + ". " : "Toutes les livraisons sont arrivées. ")
      + (floorPay > 0 ? `Le prix moyen est passé sous ${fr(x.plancher, 0)} $ : tu payes la garantie (${fr(floorPay)} $ par baril). ` : "")
      + `<b>Résultat de cette année : ${usd(perB)} par baril.</b> Rejoue : chaque année est différente.`;
    $("ng-play").disabled = false;
  }
  function drawYear(path, m, d, x) {
    const W = cv.width, H = cv.height, L = 64, Rm = 20, Tm = 22, B = 44, T = x.duree;
    ctx.clearRect(0, 0, W, H);
    const lo = 20, hi = 180;
    const X = (k) => L + (k / T) * (W - L - Rm), Y = (v) => Tm + (1 - (Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * (H - Tm - B);
    ctx.font = "22px Inter, sans-serif"; ctx.fillStyle = css("--muted"); ctx.strokeStyle = css("--rule"); ctx.lineWidth = 1; ctx.textAlign = "right";
    [40, 70, 100, 130, 160].forEach((v) => { ctx.beginPath(); ctx.moveTo(L, Y(v)); ctx.lineTo(W - Rm, Y(v)); ctx.stroke(); ctx.fillText(v + " $", L - 8, Y(v) + 7); });
    ctx.textAlign = "center";
    for (let k = 0; k <= T; k += Math.max(1, Math.round(T / 6))) ctx.fillText(k === 0 ? "auj." : "m" + k, X(k), H - 14);
    if (x.plancher > 0) {
      ctx.setLineDash([8, 6]); ctx.strokeStyle = css("--accent"); ctx.beginPath(); ctx.moveTo(L, Y(x.plancher)); ctx.lineTo(W - Rm, Y(x.plancher)); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = css("--accent"); ctx.textAlign = "left"; ctx.fillText("prix garanti", L + 6, Y(x.plancher) - 8);
    }
    const pts = [[0, S0]].concat(path.map((v, k) => [k + 1, v]));
    const end = d >= 0 ? Math.min(m, d + 1) : m;
    ctx.strokeStyle = css("--ink"); ctx.lineWidth = 3; ctx.beginPath();
    pts.forEach(([k, v], i) => {
      if (k > end + 1e-9) {
        if (i > 0 && pts[i - 1][0] < end) { const [k0, v0] = pts[i - 1], f = (end - k0) / (k - k0); ctx.lineTo(X(end), Y(v0 + (v - v0) * f)); }
        return;
      }
      i ? ctx.lineTo(X(k), Y(v)) : ctx.moveTo(X(k), Y(v));
    });
    ctx.stroke();
    for (let k = 1; k <= Math.floor(end); k++) {
      const bad = d >= 0 && k - 1 >= d;
      ctx.fillStyle = bad ? css("--neg") : css("--pos");
      ctx.beginPath(); ctx.arc(X(k), Y(path[k - 1]), bad ? 11 : 7, 0, 2 * Math.PI); ctx.fill();
      if (bad) { ctx.fillStyle = "#fff"; ctx.font = "bold 16px Inter"; ctx.fillText("✕", X(k), Y(path[k - 1]) + 6); ctx.font = "22px Inter, sans-serif"; }
    }
  }
  $("ng-play").addEventListener("click", play);
  drawYear([], 0, -1, read());
})();
