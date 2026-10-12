"""Style commun des figures (palette du site : encre, bleu marine, ambre)."""
from chemins import PARAMS, DATA  # noqa: F401  (fixe aussi le dossier de sortie)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK, MUTED, RULE = "#1d1d1f", "#615d57", "#e2ddd3"
NAVY, AMBER, RED, GREEN = "#1f4f8a", "#b06a1b", "#b23a2e", "#2e7a4f"

plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    "font.family": "DejaVu Sans", "font.size": 10.5, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": RULE, "grid.linewidth": 0.7, "legend.frameon": False,
    "axes.titleweight": "bold", "axes.titlesize": 11.5, "axes.titlelocation": "left",
})


def save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
