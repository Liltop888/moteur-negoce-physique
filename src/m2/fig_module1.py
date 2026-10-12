from chemins import PARAMS, DATA  # noqa: F401  (fixe aussi le dossier de sortie)
import json
import numpy as np
import pandas as pd
from scipy import stats
from style_fig import plt, save, NAVY, AMBER, RED, MUTED, INK

d = json.load(open("sauts_extremes.json"))
r = pd.read_csv("wti_rendements.csv", index_col=0, parse_dates=True)["r"]
loss = np.sort(-r.values)[::-1]
n = len(loss)

# ---- Figure A : la queue des pertes (probabilité de dépasser une perte x), échelle log
x = np.linspace(0.02, 0.75, 400)
emp_x = loss[loss > 0.02]
emp_p = np.arange(1, len(emp_x) + 1) / n
p_norm = stats.norm.sf(x, -r.mean(), r.std())
m = d["merton"]
p_mer = sum(stats.poisson.pmf(k, m["lam"]) * stats.norm.sf(x, -(m["mu"] + k * m["mj"]), np.sqrt(m["sig"]**2 + k * m["sj"]**2)) for k in range(12))
g = d["gpd"]
xg = x[x > g["u"]]
p_gpd = g["nu"] / g["n"] * stats.genpareto.sf(xg - g["u"], g["xi"], scale=g["beta"])

fig, ax = plt.subplots(figsize=(7.3, 4.3))
ax.scatter(emp_x * 100, emp_p, s=9, color=INK, alpha=.55, label="Observé (WTI 2010-2026)", zorder=3)
ax.plot(x * 100, p_norm, color=MUTED, lw=2, ls="--", label="Loi normale")
ax.plot(x * 100, p_mer, color=NAVY, lw=2.2, label="Merton (diffusion + sauts)")
ax.plot(xg * 100, p_gpd, color=AMBER, lw=2.2, label="Valeurs extrêmes (Pareto généralisée)")
ax.set_yscale("log"); ax.set_ylim(1 / n / 3, 0.3); ax.set_xlim(2, 75)
ax.set_xlabel("Perte journalière (%)"); ax.set_ylabel("Probabilité qu'une journée perde plus")
ax.annotate("17 → 21 avril 2020 : −72 % (log)", (72, 1 / n), xytext=(42, 3e-4), color=INK, fontsize=9.5,
            arrowprops=dict(arrowstyle="->", color=MUTED))
ax.legend(loc="upper right", fontsize=9.5)
ax.set_title("La loi normale sous-estime les krachs du pétrole")
save(fig, "fig_queue.png")

# ---- Figure B : backtest GARCH + EVT, 2020-2026
v = pd.read_csv("var_garch_evt_test.csv", index_col=0, parse_dates=True)
var = v["var"].abs()
fig, ax = plt.subplots(figsize=(7.3, 3.9))
ax.plot(v.index, v.r * 100, color=MUTED, lw=.6, alpha=.8, label="Rendement journalier")
ax.plot(v.index, -var * 100, color=NAVY, lw=1.4, label="VaR 99 % du jour (GARCH + valeurs extrêmes)")
e = v[v.r < -var]
ax.scatter(e.index, e.r.clip(lower=-0.35) * 100, color=RED, s=22, zorder=4, label=f"Dépassements : {len(e)} (16,9 attendus)")
ax.set_ylim(-36, 22)
ax.text(pd.Timestamp("2020-05-20"), -34.5, "17 → 21/04/2020 : −72 % (hors cadre)", fontsize=8.5, color=RED)
ax.set_ylabel("%")
ax.legend(loc="lower right", fontsize=8.8, ncol=1)
ax.set_title("Prévision hors échantillon, 2020-2026 : modèle figé sur 2010-2019")
save(fig, "fig_var_backtest.png")
print("figures ok")
