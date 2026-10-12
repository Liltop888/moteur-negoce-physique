// Page Prévisions : lit data/previsions.json (mis à jour chaque lundi) et dessine l'éventail de chaque série.
(function () {
  const $ = (id) => document.getElementById(id);
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const fr = (v, d) => v.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const dec = (u) => (u.includes("litre") || u.includes("gallon") ? 3 : 2);
  const pct = (v) => (v == null ? "—" : fr(v * 100, 0) + " %");
  const dfr = (s) => new Date(s + "T00:00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
  let DATA = null, current = null;

  function draw(s) {
    const cv = $("pv-chart"), ctx = cv.getContext("2d");
    const W = cv.width, H = cv.height, L = 70, R = 18, T = 20, B = 46;
    ctx.clearRect(0, 0, W, H);
    const hd = s.historique.dates.slice(-(s.freq === "j" ? 130 : 52)), hp = s.historique.prix.slice(-hd.length);
    const fd = s.eventail.dates, q = s.eventail.valeurs;
    const all = hp.concat(q[0], q[4]);
    let lo = Math.min(...all), hi = Math.max(...all);
    const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const n = hd.length + fd.length;
    const X = (i) => L + (i / (n - 1)) * (W - L - R);
    const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
    ctx.font = "22px Inter, sans-serif"; ctx.lineWidth = 1;
    // grille
    ctx.strokeStyle = css("--rule"); ctx.fillStyle = css("--muted"); ctx.textAlign = "right";
    const ticks = 5;
    for (let k = 0; k <= ticks; k++) {
      const v = lo + (hi - lo) * k / ticks, y = Y(v);
      ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(W - R, y); ctx.stroke();
      ctx.fillText(fr(v, dec(s.unite) === 3 ? 2 : 0), L - 8, y + 7);
    }
    // éventail : 5-95 puis 25-75
    const band = (a, b, alpha) => {
      ctx.beginPath();
      ctx.moveTo(X(hd.length - 1), Y(hp[hp.length - 1]));
      fd.forEach((_, i) => ctx.lineTo(X(hd.length + i), Y(q[a][i])));
      for (let i = fd.length - 1; i >= 0; i--) ctx.lineTo(X(hd.length + i), Y(q[b][i]));
      ctx.closePath(); ctx.globalAlpha = alpha; ctx.fillStyle = css("--accent"); ctx.fill(); ctx.globalAlpha = 1;
    };
    band(0, 4, 0.16); band(1, 3, 0.26);
    // médiane
    ctx.setLineDash([6, 6]); ctx.strokeStyle = css("--accent"); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(X(hd.length - 1), Y(hp[hp.length - 1]));
    fd.forEach((_, i) => ctx.lineTo(X(hd.length + i), Y(q[2][i]))); ctx.stroke(); ctx.setLineDash([]);
    // historique
    ctx.strokeStyle = css("--ink"); ctx.lineWidth = 2.4; ctx.beginPath();
    hp.forEach((v, i) => (i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v)))); ctx.stroke();
    // séparation aujourd'hui
    ctx.strokeStyle = css("--muted"); ctx.lineWidth = 1; ctx.setLineDash([3, 5]);
    ctx.beginPath(); ctx.moveTo(X(hd.length - 1), T); ctx.lineTo(X(hd.length - 1), H - B); ctx.stroke(); ctx.setLineDash([]);
    // dates
    ctx.fillStyle = css("--muted"); ctx.textAlign = "center";
    ctx.textAlign = "left"; ctx.fillText(dfr(hd[0]), X(0), H - 14);
    ctx.textAlign = "center"; ctx.fillText(dfr(hd[Math.floor(hd.length / 2)]), X(Math.floor(hd.length / 2)), H - 14);
    ctx.textAlign = "right"; ctx.fillText("aujourd'hui", X(hd.length - 1) - 6, H - 14);
    ctx.fillStyle = css("--accent"); ctx.fillText(dfr(fd[fd.length - 1]), X(n - 1), H - 14);
  }

  function show(id) {
    const s = DATA.series.find((x) => x.id === id); current = s;
    document.querySelectorAll(".pv-tab").forEach((b) => b.setAttribute("aria-pressed", b.dataset.id === id));
    const d = dec(s.unite), u = s.unite;
    $("pv-nom").textContent = s.nom;
    $("pv-prix").textContent = fr(s.dernier, d) + " " + u;
    $("pv-date").textContent = "dernier prix connu : " + dfr(s.date) + " · source : " + s.source;
    const h = s.horizons;
    $("pv-sem").textContent = fr(h["1 semaine"].bas, d) + " à " + fr(h["1 semaine"].haut, d);
    $("pv-mois").textContent = fr(h["1 mois"].bas, d) + " à " + fr(h["1 mois"].haut, d);
    const b1 = s.backtest["1 semaine"], b4 = s.backtest["1 mois"];
    $("pv-bt").innerHTML =
      `<dt>Fourchette 1 semaine</dt><dd>${pct(b1.couverture)} <span class="muted">(${b1.n} tests)</span></dd>` +
      `<dt>Fourchette 1 mois</dt><dd>${pct(b4.couverture)} <span class="muted">(${b4.n} tests)</span></dd>` +
      `<dt>Largeur moyenne (1 semaine)</dt><dd>± ${fr(b1.largeur_moy * 50, 1)} %</dd>`;
    const p = s.publiees;
    $("pv-live").textContent = p && p.notees ? `${p.dedans} sur ${p.notees} dans la fourchette` : "première évaluation dans une semaine";
    draw(s);
  }

  function table() {
    $("pv-table").innerHTML = "<tr><th>Prix</th><th class='r'>Aujourd'hui</th><th class='r'>Dans 1 semaine (90 %)</th><th class='r'>Dans 1 mois (90 %)</th><th class='r'>Score passé</th></tr>" +
      DATA.series.map((s) => {
        const d = dec(s.unite), h = s.horizons;
        return `<tr><td><a href="#graphique" data-id="${s.id}" class="pv-link">${s.nom}</a></td><td class="r">${fr(s.dernier, d)} <span class="muted">${s.unite}</span></td>` +
          `<td class="r">${fr(h["1 semaine"].bas, d)} – ${fr(h["1 semaine"].haut, d)}</td><td class="r">${fr(h["1 mois"].bas, d)} – ${fr(h["1 mois"].haut, d)}</td>` +
          `<td class="r">${pct(s.backtest["1 semaine"].couverture)}</td></tr>`;
      }).join("");
    document.querySelectorAll(".pv-link").forEach((a) => a.addEventListener("click", () => show(a.dataset.id)));
  }


  // ---------------------------------------------------------------- Et toi ? (WTI, 1 semaine)
  function toi(d) {
    const s = d.series.find((x) => x.id === "wti") || d.series[0];
    const p = s.historique.prix, h = 5, last = s.dernier;
    const moves = [];
    for (let i = 0; i + h < p.length; i++) moves.push(Math.abs(p[i + h] / p[i] - 1));
    $("toi-prix").textContent = fr(last, 2) + " $";
    const m = s.horizons["1 semaine"];
    $("mod-band").textContent = fr(m.bas, 0) + " à " + fr(m.haut, 0) + " $";
    $("mod-score").textContent = pct(s.backtest["1 semaine"].couverture) + " des semaines";
    const upd = () => {
      const w = +$("toi-w").value / 100;
      $("toi-out").textContent = "± " + (w * 100).toFixed(0) + " %";
      $("toi-band").textContent = fr(last * (1 - w), 0) + " à " + fr(last * (1 + w), 0) + " $";
      const hit = moves.filter((x) => x <= w).length / moves.length;
      $("toi-score").textContent = pct(hit) + " des semaines";
      $("toi-msg").innerHTML = hit < 0.8
        ? `<b>Trop étroit.</b> Sur la dernière année, ta fourchette n'aurait contenu le prix que ${pct(hit)} des semaines. L'intuition sous-estime presque toujours la volatilité du pétrole.`
        : hit > 0.97 ? "<b>Trop large.</b> Ta fourchette ne se trompe presque jamais, mais elle est si large qu'elle n'apprend rien. Une bonne fourchette à 90 % se trompe environ une fois sur dix."
        : "<b>Bien réglé !</b> Ta fourchette contient le prix environ 9 semaines sur 10 : c'est exactement ce que vise le modèle.";
    };
    $("toi-w").addEventListener("input", upd); upd();
  }

  fetch("data/previsions.json", { cache: "no-store" }).then((r) => r.json()).then((d) => {
    DATA = d;
    $("pv-maj").textContent = "Mis à jour le " + new Date(d.mise_a_jour).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    $("pv-tabs").innerHTML = d.series.map((s) => `<button type="button" class="pv-tab" data-id="${s.id}" aria-pressed="false">${s.nom.split(" (")[0]}</button>`).join("");
    document.querySelectorAll(".pv-tab").forEach((b) => b.addEventListener("click", () => show(b.dataset.id)));
    table(); show(d.series[0].id); if ($("toi-w")) toi(d);
    window.addEventListener("resize", () => current && draw(current));
  }).catch(() => { $("pv-maj").textContent = "Les données n'ont pas pu être chargées."; });
})();
