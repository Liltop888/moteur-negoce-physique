"""
Calibration du modèle de Schwartz à un facteur sur l'historique réel du WTI.

Source : FRED (Federal Reserve Bank of St. Louis), série MCOILWTICO, prix spot WTI Cushing,
moyenne mensuelle en USD/baril (données EIA).

Méthode (estimateur exact d'un processus d'Ornstein-Uhlenbeck sur le log-prix) :
  x_{t+1} = a + b x_t + e_t,   e_t ~ N(0, s²)       (régression des moindres carrés = maximum de vraisemblance)
  kappa = -ln(b) / dt
  mu    = a / (1 - b)            -> niveau de long terme = exp(mu)
  sigma = s * sqrt(2 kappa / (1 - b²))

Correction : des moyennes mensuelles lissent les mouvements intra-mois ; la variance des écarts
entre deux moyennes successives vaut environ 2/3 de celle des prix ponctuels. On multiplie donc
sigma par sqrt(3/2).

Sortie : schwartz_params.json, lu automatiquement par stochastic.py.
"""
import json
import sys
import numpy as np
import pandas as pd

DT = 1 / 12
CORRECTION_MOYENNE = np.sqrt(1.5)


def calibrate(prices):
    x = np.log(prices.to_numpy())
    X, Y = x[:-1], x[1:]
    b, a = np.polyfit(X, Y, 1)
    resid = Y - (a + b * X)
    s = resid.std(ddof=2)
    kappa = -np.log(b) / DT
    mu = a / (1 - b)
    sigma = s * np.sqrt(2 * kappa / (1 - b ** 2)) * CORRECTION_MOYENNE
    # Erreur type de b -> intervalle de confiance sur kappa (méthode delta)
    se_b = s / np.sqrt(((X - X.mean()) ** 2).sum())
    return {
        "kappa": float(kappa), "niveau_lt": float(np.exp(mu)), "sigma": float(sigma),
        "demi_vie_mois": float(np.log(2) / kappa * 12),
        "kappa_ic95": [float(-np.log(min(b + 1.96 * se_b, 0.9999)) / DT),
                       float(-np.log(b - 1.96 * se_b) / DT)],
        "n_obs": int(len(x)),
    }


def main(path="wti_monthly_fred.csv"):
    df = pd.read_csv(path, parse_dates=["date"]).sort_values("date")
    rows = {}
    for nom, debut in [("2010-2026", "2010-01-01"), ("2015-2026", "2015-01-01"), ("2020-2026", "2020-01-01")]:
        rows[nom] = calibrate(df.loc[df["date"] >= debut, "wti"])
    table = pd.DataFrame(rows).T
    print(table.to_string())

    # On retient l'échantillon 2015-2026 : après la révolution du schiste (régime de prix actuel),
    # mais assez long pour estimer le retour à la moyenne.
    p = rows["2015-2026"]
    out = {"sigma": round(p["sigma"], 4), "kappa": round(p["kappa"], 4),
           "niveau_lt": round(p["niveau_lt"], 2),
           "dernier_prix": float(df["wti"].iloc[-1]), "dernier_mois": str(df["date"].iloc[-1].date()),
           "echantillon": "2015-2026", "source": "FRED MCOILWTICO (EIA), moyenne mensuelle"}
    with open("schwartz_params.json", "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("\nParamètres retenus :", out)
    return table


if __name__ == "__main__":
    main(*sys.argv[1:])
