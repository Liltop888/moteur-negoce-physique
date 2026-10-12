from chemins import PARAMS, DATA  # noqa: F401  (fixe aussi le dossier de sortie)
import json
from style_fig import plt, save, NAVY, AMBER, MUTED

d = json.load(open("cva.json"))
res = d["res"]
b = [x["beta"] for x in res]
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.6, 3.7))
ax1.plot(b, [x["pd_prix_bas"] * 100 for x in res], color=AMBER, lw=2.2, marker="o", label="si le prix finit bas (20 % pires)")
ax1.plot(b, [x["pd_prix_haut"] * 100 for x in res], color=NAVY, lw=2.2, marker="o", label="si le prix finit haut (20 % meilleurs)")
ax1.axhline(15, color=MUTED, ls="--", lw=1); ax1.text(1.5, 16.2, "moyenne : 15 % dans tous les cas", fontsize=8.8, color=MUTED)
ax1.set_xlabel("β : sensibilité du défaut au prix"); ax1.set_ylabel("Probabilité de défaut à un an (%)")
ax1.set_ylim(0, 44); ax1.legend(fontsize=8.8, loc="upper left"); ax1.set_title("Le défaut suit le prix")
ax2.set_axisbelow(True); ax2.bar(b, [x["cva_par_baril"] for x in res], color=NAVY, width=.6)
for x in res:
    ax2.text(x["beta"], x["cva_par_baril"] + .05, f"{x['cva_par_baril']:.2f}".replace(".", ","), ha="center", fontsize=9)
ax2.axhline(d["decote"], color=AMBER, ls=":", lw=1.4); ax2.text(-.3, d["decote"] - .45, "décote négociée : 7,40 $", color=AMBER, fontsize=9)
ax2.set_ylim(0, 8); ax2.set_xlabel("β"); ax2.set_ylabel("CVA ($ par baril)")
ax2.set_title("Coût du risque de défaut (CVA)")
save(fig, "fig_cva.png")
