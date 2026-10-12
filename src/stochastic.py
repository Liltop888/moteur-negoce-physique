"""
Modèles stochastiques (programme type M2 Probabilités & Finance « El Karoui »).

1) Prix du pétrole : modèle de Schwartz à un facteur (1997)
       d ln S_t = kappa * (mu - ln S_t) dt + sigma dW_t
   -> processus d'Ornstein-Uhlenbeck sur le log-prix : le pétrole revient vers un niveau de
      long terme (coût marginal de production), contrairement à une action (Black-Scholes).
   Simulation exacte (pas d'erreur de discrétisation) :
       X_{t+dt} = X_t e^{-kappa dt} + mu (1 - e^{-kappa dt}) + sigma sqrt((1 - e^{-2 kappa dt}) / (2 kappa)) Z

2) Risque de défaut : modèle structurel de Merton (1974)
   La valeur des actifs d'un producteur = valeur actualisée de sa production future, qui dépend
   DIRECTEMENT du prix du pétrole. Défaut si valeur des actifs < dette à l'horizon.
   Seuil de défaut : point KMV (dette court terme + moitié de la dette longue - cash).
   Comme prix et défauts sont simulés ensemble, on capture le « wrong-way risk » :
   quand le pétrole chute, plusieurs producteurs font défaut EN MÊME TEMPS, juste au moment où
   la marchandise que tu détiens vaut moins.

3) Mesures de risque : VaR et CVaR (Expected Shortfall) à 95 %.

Paramètres = hypothèses raisonnables à calibrer sur l'historique des futures (WTI, Brent).
"""
import numpy as np

SIGMA = 0.35          # volatilité annuelle du log-prix (valeur par défaut)
KAPPA = 1.0           # vitesse de retour à la moyenne (valeur par défaut)
NIVEAU_LT = 70.0      # niveau de long terme USD/b (valeur par défaut)
DERNIER_PRIX = None
SOURCE_PARAMS = "valeurs par défaut (non calibrées)"

# Paramètres calibrés sur l'historique réel (fichier produit par calibrate.py), s'il existe
import json as _json
import os as _os
_p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "schwartz_params.json")
if _os.path.exists(_p):
    with open(_p, encoding="utf-8") as _f:
        _c = _json.load(_f)
    SIGMA, KAPPA, NIVEAU_LT = _c["sigma"], _c["kappa"], _c["niveau_lt"]
    DERNIER_PRIX = _c.get("dernier_prix")
    SOURCE_PARAMS = f"calibré sur {_c['source']}, {_c['echantillon']}"
VOL_IDIO = 0.25       # volatilité propre à chaque producteur (géologie, exécution, gestion)
ANNEES_RESERVES = 6   # durée de vie économique de la production
TAUX_ACTU = 0.10
N_SCEN = 20000
SEED = 7


def simulate_price(s0, horizon_years, n_steps=12, n_scen=N_SCEN, rng=None):
    """Trajectoires du prix (n_scen, n_steps+1) selon Schwartz 1 facteur, simulation exacte."""
    rng = rng or np.random.default_rng(SEED)
    dt = horizon_years / n_steps
    mu = np.log(NIVEAU_LT)
    a = np.exp(-KAPPA * dt)
    sd = SIGMA * np.sqrt((1 - np.exp(-2 * KAPPA * dt)) / (2 * KAPPA))
    x = np.empty((n_scen, n_steps + 1))
    x[:, 0] = np.log(s0)
    z = rng.standard_normal((n_scen, n_steps))
    for t in range(n_steps):
        x[:, t + 1] = x[:, t] * a + mu * (1 - a) + sd * z[:, t]
    return np.exp(x), z


def var_cvar(pnl, level=0.95):
    """VaR et CVaR des pertes (nombres positifs = pertes)."""
    losses = -np.asarray(pnl)
    var = np.quantile(losses, level)
    return float(var), float(losses[losses >= var].mean())


def deal_pnl_distribution(s0, marge_usd_b, jours, n_scen=N_SCEN, rng=None):
    """
    P&L par baril d'une cargaison achetée aujourd'hui et revendue dans `jours`.
      - non couvert : on subit la variation du prix S_T - S_0
      - couvert     : vente de futures à l'achat -> il ne reste que la marge + un risque de base résiduel
    """
    rng = rng or np.random.default_rng(SEED)
    paths, _ = simulate_price(s0, jours / 365, n_steps=max(1, jours // 5), n_scen=n_scen, rng=rng)
    st = paths[:, -1]
    non_couvert = marge_usd_b + (st - s0)
    base = rng.normal(0, 0.6, n_scen)  # risque de base : écart hub physique vs future (hypothèse)
    couvert = marge_usd_b + base
    return non_couvert, couvert


def default_point_musd(r):
    """
    Point de défaut KMV (Moody's) : dette court terme + 50 % de la dette long terme - cash.
    Une entreprise ne fait pas défaut quand ses actifs passent sous TOUTE sa dette, mais quand
    elle ne peut plus honorer ce qui arrive à échéance ; la dette longue pèse moins à 1 an.
    """
    ct = r.get("dette_court_terme_musd", r["dette_musd"])
    lt = max(r["dette_musd"] - ct, 0)
    return max(ct + 0.5 * lt - r["cash_musd"], 0)


def asset_value_musd(price, prod_bpj, cout_prod):
    """Valeur actualisée de la production (annuité sur ANNEES_RESERVES, déclin ignoré)."""
    annuite = (1 - (1 + TAUX_ACTU) ** -ANNEES_RESERVES) / TAUX_ACTU
    marge = np.maximum(price - cout_prod, 0)
    return prod_bpj * 365 * marge * annuite / 1e6


def joint_default_simulation(producers, s0, horizon_years=1.0, n_scen=N_SCEN, seed=SEED):
    """
    Simule conjointement le prix et la valeur des actifs de chaque producteur.
    Renvoie : prix final (n_scen,), matrice des défauts (n_scen, n_prod), proba de défaut Merton.
    `producers` : DataFrame avec production_bpj, cout_production_usd_b, dette_musd, cash_musd.
    """
    rng = np.random.default_rng(seed)
    paths, _ = simulate_price(s0, horizon_years, n_steps=12, n_scen=n_scen, rng=rng)
    st = paths[:, -1]
    n = len(producers)
    defaults = np.zeros((n_scen, n), dtype=bool)
    for j, (_, r) in enumerate(producers.iterrows()):
        v = asset_value_musd(st, r["production_bpj"], r["cout_production_usd_b"])
        choc = np.exp(VOL_IDIO * np.sqrt(horizon_years) * rng.standard_normal(n_scen)
                      - 0.5 * VOL_IDIO ** 2 * horizon_years)
        defaults[:, j] = v * choc < default_point_musd(r)
    return st, defaults, defaults.mean(axis=0)


def distance_to_default(producer, s0):
    """Distance au défaut (en écarts-types) façon Merton/KMV, pour lecture intuitive."""
    v0 = asset_value_musd(s0, producer["production_bpj"], producer["cout_production_usd_b"])
    d = max(default_point_musd(producer), 1e-6)
    marge = max(s0 - producer["cout_production_usd_b"], 1e-6)
    vol_actifs = np.sqrt((SIGMA * s0 / marge) ** 2 + VOL_IDIO ** 2)  # levier opérationnel
    if v0 <= 0:
        return -np.inf
    return float((np.log(v0 / d) - 0.5 * vol_actifs ** 2) / vol_actifs)
