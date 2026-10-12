// Interactions simples : le litre d'essence (accueil) et le quiz des producteurs (Lab).
(function () {
  const $ = (id) => document.getElementById(id);
  // ---------------------------------------------------------------- Accueil : le litre
  const info = {
    brut: "<b>Le pétrole brut : 0,71 € (35 %).</b> C'est le prix du baril (159 litres) sorti du puits, ramené à un litre. Quand le Brent monte de 10 $, ce morceau grossit d'environ 5 centimes. C'est la seule partie qui suit directement le marché mondial.",
    raff: "<b>Le raffinage : 0,10 € (5 %).</b> Le brut ne se met pas dans une voiture : une raffinerie le chauffe et le sépare en essence, diesel, kérosène. Sa marge est petite par litre, mais énorme en volume.",
    dist: "<b>Transport, stockage et station : 0,27 € (14 %).</b> Navires, pipelines, dépôts, camions-citernes, puis la marge de la station. C'est le monde du négoce physique : déplacer le bon produit au bon endroit, au bon moment.",
    tax: "<b>Les taxes : 0,93 € (46 %).</b> Accises et TVA. Près de la moitié du prix va à l'État. C'est pour ça que le prix à la pompe bouge moins que le pétrole brut : les taxes, en grande partie fixes, amortissent les mouvements.",
  };
  document.querySelectorAll(".litre .seg").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".litre .seg").forEach((x) => x.classList.toggle("on", x === b));
    $("litre-info").innerHTML = info[b.dataset.k];
  }));

  // ---------------------------------------------------------------- Lab : le quiz
  const q = $("quiz");
  if (q) {
    const rates = [5.5, 9.4, 10.2, 10.2, 32.8];
    q.querySelectorAll("button[data-g]").forEach((b) => b.addEventListener("click", () => {
      const g = +b.dataset.g;
      q.querySelectorAll("button[data-g]").forEach((x, i) => {
        x.disabled = true;
        const bar = x.querySelector("i"); bar.style.height = (rates[i] / 35 * 100) + "%";
        x.querySelector("em").textContent = rates[i].toLocaleString("fr-FR") + " %";
        x.classList.toggle("win", i === 4); x.classList.toggle("pick", i === g);
      });
      $("quiz-msg").innerHTML = g === 4
        ? "<b>Bien vu !</b> Le groupe que le modèle jugeait le plus à risque s'est arrêté six fois plus souvent que le plus sûr : 32,8 % contre 5,5 %."
        : "<b>Pas tout à fait.</b> C'est le groupe 5, celui que le modèle jugeait le plus à risque : 32,8 % de ses producteurs se sont arrêtés, six fois plus que le groupe 1 (5,5 %).";
    }));
  }
})();
