from chemins import PARAMS, DATA  # noqa: F401  (fixe aussi le dossier de sortie)
import json
import numpy as np
import plancher as pl
from style_fig import plt, save, NAVY, AMBER, MUTED, INK

d = json.load(open("plancher.json"))
# coût du plancher sur moyenne (Monte Carlo + variable de contrôle) pour chaque K
rng = np.random.default_rng(7)
X = pl.m + rng.standard_normal((60000, 12)) @ pl.L.T
S = np.exp(X)
Ks = np.array([k["K"] for k in d["by_K"]])
asian = []
for K in Ks:
    a = pl.disc * np.maximum(K - S.mean(1), 0)
    g = pl.disc * np.maximum(K - np.exp(X.mean(1)), 0)
    mG, vG = pl.mG, pl.vG
    ge = pl.disc * (K * pl.stats.norm.cdf((np.log(K) - mG) / np.sqrt(vG)) - np.exp(mG + vG / 2) * pl.stats.norm.cdf((np.log(K) - mG - vG) / np.sqrt(vG)))
    b = np.cov(a, g)[0, 1] / g.var(ddof=1)
    asian.append((a - b * (g - ge)).mean())
d["by_K_asian"] = [dict(K=float(k), asian=float(v)) for k, v in zip(Ks, asian)]
json.dump(d, open("plancher.json", "w"), indent=1)

fig, ax = plt.subplots(figsize=(7.3, 4.1))
ax.plot(Ks, [k["strip_gbm"] for k in d["by_K"]], color=MUTED, lw=2, ls="--", marker="o", ms=4, label="Plancher mensuel, sans retour à la moyenne")
ax.plot(Ks, [k["strip"] for k in d["by_K"]], color=NAVY, lw=2.2, marker="o", ms=4, label="Plancher mensuel, Schwartz (formule fermée)")
ax.plot(Ks, asian, color=AMBER, lw=2.2, marker="o", ms=4, label="Plancher sur la moyenne annuelle (Monte Carlo)")
ax.axvline(80, color=INK, lw=.8, alpha=.4)
ax.set_xlabel(r"Prix plancher garanti au producteur (\$/baril)  ·  prix actuel : 96 \$")
ax.set_ylabel("Coût du plancher ($ par baril)")
ax.legend(fontsize=9.3, loc="upper left")
ax.set_title("Combien coûte de garantir un prix minimum au producteur ?")
save(fig, "fig_plancher.png")

c = d["conv"]
n = np.array([x["n"] for x in c])
fig, ax = plt.subplots(figsize=(7.3, 3.7))
for key, se, col, lab in [("simple", "se_simple", MUTED, "Monte Carlo simple"), ("cv", "se_cv", AMBER, "Avec variable de contrôle géométrique")]:
    y = np.array([x[key] for x in c]); e = np.array([x[se] for x in c])
    ax.fill_between(n, y - 2 * e, y + 2 * e, color=col, alpha=.18)
    ax.plot(n, y, color=col, lw=2, marker="o", ms=4, label=lab)
ax.set_xscale("log"); ax.set_xlabel("Nombre de scénarios simulés"); ax.set_ylabel("Prix estimé ($/baril)")
ax.legend(fontsize=9.5); ax.set_title("Même précision avec 100 fois moins de scénarios")
save(fig, "fig_mc.png")
print([round(a, 3) for a in asian])
