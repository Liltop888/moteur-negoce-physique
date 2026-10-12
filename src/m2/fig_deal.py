import json
import numpy as np
from style_fig import plt, save, NAVY, AMBER, MUTED, INK, GREEN

d = json.load(open("deal.json"))
rows = d["structures"]
lab = [f"Prépaiement\n{r['duree']} mois" for r in rows]
x = np.arange(len(rows))
fig, ax = plt.subplots(figsize=(7.3, 4.2))
ax.set_axisbelow(True)
b1 = [r["cva"] for r in rows]; b2 = [r["financement"] for r in rows]; b3 = [r["plancher"] for r in rows]
ax.bar(x, b1, .55, color=NAVY, label="Risque de défaut (CVA)")
ax.bar(x, b2, .55, bottom=b1, color="#6f8fb8", label="Financement de l'avance")
ax.bar(x, b3, .55, bottom=np.add(b1, b2), color=AMBER, label="Plancher offert (70 $ sur la moyenne)")
dec = d["hyp"]["decote"]
ax.axhline(dec, color=INK, lw=1.2, ls="--"); ax.text(1.55, dec + .15, f"décote obtenue : {dec:.2f} $".replace(".", ","), fontsize=9.5, color=INK)
for i, r in enumerate(rows):
    tot = r["decote_minimale"]
    ax.text(i, tot + .15, f"coût {tot:.2f} $".replace(".", ","), ha="center", fontsize=9.5, color=INK)
    ax.text(i, 8.6, f"marge {r['marge_nette']:.2f} $\ncapital {r['rendement_capital']*100:.0f} %/an".replace(".", ","), ha="center", fontsize=9.5,
            color=GREEN if r["duree"] == 3 else MUTED, fontweight="bold" if r["duree"] == 3 else "normal")
ax.set_xticks(x, lab); ax.set_ylim(0, 9.8); ax.set_ylabel("$ par baril")
ax.legend(fontsize=9, loc="center left", bbox_to_anchor=(0, .5))
ax.set_title("Ce que coûte chaque baril préfinancé, selon la durée")
save(fig, "fig_deal.png")
