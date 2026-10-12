from chemins import PARAMS, DATA  # noqa: F401  (fixe aussi le dossier de sortie)
import json
from style_fig import plt, save, NAVY, AMBER, MUTED, INK

d = json.load(open("stockage.json"))
rows = d["rows"]
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.6, 3.9), gridspec_kw=dict(width_ratios=[1.15, 1]))
s0 = [x["S0"] for x in rows]
ax1.plot(s0, s0, color=MUTED, lw=2, ls="--", label="Vendre tout de suite")
ax1.plot(s0, [x["valeur_dp"] for x in rows], color=NAVY, lw=2.2, label="Valeur optimale (grille)")
ax1.scatter(s0, [x["valeur_lsm"] for x in rows], color=AMBER, s=30, zorder=4, label="Longstaff-Schwartz")
ax1.set_xlabel("Prix du baril aujourd'hui ($)"); ax1.set_ylabel("Valeur du baril stocké ($)")
ax1.legend(fontsize=9); ax1.set_title("Attendre paie quand le prix est bas")
ax2.plot(range(1, 12), d["frontiere"], color=NAVY, lw=2.2, marker="o", ms=4)
ax2.axhline(96.24, color=AMBER, lw=1.4, ls=":"); ax2.text(1, 93, "prix actuel : 96 $", color=AMBER, fontsize=9)
ax2.axhline(65.47, color=MUTED, lw=1, ls="--"); ax2.text(1, 62.5, "niveau de long terme : 65 $", color=MUTED, fontsize=9)
ax2.set_ylim(55, 100); ax2.set_xlabel("Mois"); ax2.set_ylabel("Vendre si le prix dépasse ($)")
ax2.set_title("Frontière de vente optimale")
save(fig, "fig_stockage.png")
