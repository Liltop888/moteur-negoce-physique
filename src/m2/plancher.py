"""Module 2 — Le prix plancher d'un préfinancement : options sous Schwartz, formule fermée et Monte Carlo.

Cours du M2 mobilisés : « Processus stochastiques et produits dérivés », « Introduction aux processus
de diffusion », « Probabilités numériques pour la finance, simulation de Monte-Carlo ».

Situation : le négociant préfinance 12 livraisons mensuelles et garantit au producteur un prix minimum K.
Ce plancher est une option de vente (put). Deux versions :
  (a) un plancher sur chaque livraison mensuelle  -> somme de 12 puts européens, formule fermée ;
  (b) un plancher sur le prix moyen de l'année    -> option sur moyenne (APO, la plus échangée sur le pétrole),
      sans formule fermée -> Monte Carlo, avec variables antithétiques et variable de contrôle géométrique.
Hypothèse : on prend la mesure historique comme mesure de pricing (prime de risque nulle, λ = 0),
faute de courbe des futures dans les données publiques accessibles. À remplacer par une calibration sur futures.
"""
from chemins import PARAMS, DATA  # noqa: F401  (fixe aussi le dossier de sortie)
import json
import numpy as np
from scipy import stats

P = json.load(open(PARAMS))
kappa, sigma, LT = P["kappa"], P["sigma"], P["niveau_lt"]
S0, K, r = 96.24, 80.0, 0.04            # dernier prix WTI (6 oct. 2026), plancher, taux sans risque
mu = np.log(LT)
t = np.arange(1, 13) / 12                # 12 dates de livraison
x0 = np.log(S0)


def ou_moments(t):
    m = x0 * np.exp(-kappa * t) + mu * (1 - np.exp(-kappa * t))
    v = sigma**2 * (1 - np.exp(-2 * kappa * t)) / (2 * kappa)
    return m, v


def black_put(F, K, v, T):
    sd = np.sqrt(v)
    d1 = (np.log(F / K) + v / 2) / sd
    d2 = d1 - sd
    return np.exp(-r * T) * (K * stats.norm.cdf(-d2) - F * stats.norm.cdf(-d1))


# ---------------------------------------------------------------- (a) 12 puts mensuels, formule fermée
m, v = ou_moments(t)
F = np.exp(m + v / 2)                    # prix à terme implicite sous Schwartz
put_ou = black_put(F, K, v, t)
put_gbm = black_put(F, K, sigma**2 * t, t)   # même courbe, mais volatilité sans retour à la moyenne
vol_eff = np.sqrt(v / t)                 # volatilité effective par maturité (effet Samuelson)
print("Prix à terme  :", F.round(2))
print("Vol effective :", (vol_eff * 100).round(1))
print(f"Plancher mensuel, coût moyen par baril : Schwartz {put_ou.mean():.3f} $  |  sans retour à la moyenne {put_gbm.mean():.3f} $")

# ---------------------------------------------------------------- (b) Plancher sur moyenne annuelle : Monte Carlo
# covariance exacte du vecteur (X_t1, ..., X_t12) sous Ornstein-Uhlenbeck
T1, T2 = np.meshgrid(t, t, indexing="ij")
C = sigma**2 / (2 * kappa) * np.exp(-kappa * (T1 + T2)) * (np.exp(2 * kappa * np.minimum(T1, T2)) - 1)
L = np.linalg.cholesky(C + 1e-14 * np.eye(12))
disc = np.exp(-r * 1.0)                  # paiement à la fin de l'année

# variable de contrôle : put sur moyenne géométrique, prix exact car ln(moyenne géométrique) est gaussien
mG, vG = m.mean(), C.sum() / 144
geo_exact = disc * (K * stats.norm.cdf((np.log(K) - mG) / np.sqrt(vG)) - np.exp(mG + vG / 2) * stats.norm.cdf((np.log(K) - mG - vG) / np.sqrt(vG)))


def simulate(n, rng, anti=False):
    Z = rng.standard_normal((n, 12))
    if anti:
        Z = np.vstack([Z, -Z])
    X = m + Z @ L.T
    S = np.exp(X)
    arith = disc * np.maximum(K - S.mean(1), 0)
    geo = disc * np.maximum(K - np.exp(X.mean(1)), 0)
    strip = (np.exp(-r * t) * np.maximum(K - S, 0)).mean(1)
    return arith, geo, strip


rng = np.random.default_rng(42)
N = 100_000
res = {}
a, g, s = simulate(N, rng)
res["Monte Carlo simple"] = (a.mean(), a.std(ddof=1) / np.sqrt(N))
check_strip = (s.mean(), s.std(ddof=1) / np.sqrt(N))
# antithétique : on moyenne chaque paire (Z, -Z)
a2, g2, _ = simulate(N // 2, rng, anti=True)
pair = 0.5 * (a2[: N // 2] + a2[N // 2:])
res["Variables antithétiques"] = (pair.mean(), pair.std(ddof=1) / np.sqrt(N // 2))
# variable de contrôle géométrique, coefficient b estimé
b = np.cov(a, g)[0, 1] / g.var(ddof=1)
cv = a - b * (g - geo_exact)
res["Variable de contrôle"] = (cv.mean(), cv.std(ddof=1) / np.sqrt(N))
corr = np.corrcoef(a, g)[0, 1]
base_var = res["Monte Carlo simple"][1] ** 2
eff = {k: base_var / v[1] ** 2 for k, v in res.items()}
for k, (p, se) in res.items():
    print(f"{k:26s} prix {p:.4f} $   erreur-type {se:.5f}   gain de variance ×{eff[k]:.1f}")
print(f"Contrôle : strip Monte Carlo {check_strip[0]:.4f} ± {check_strip[1]:.4f}  contre formule fermée {put_ou.mean():.4f}")
print(f"corrélation arithmétique/géométrique : {corr:.4f} ; put géométrique exact {geo_exact:.4f}")

# convergence pour la figure
conv = []
for n in [500, 1000, 2000, 5000, 10000, 20000, 50000, 100000]:
    rr = np.random.default_rng(n)
    a_, g_, _ = simulate(n, rr)
    b_ = np.cov(a_, g_)[0, 1] / g_.var(ddof=1)
    c_ = a_ - b_ * (g_ - geo_exact)
    conv.append(dict(n=n, simple=a_.mean(), se_simple=a_.std(ddof=1) / np.sqrt(n), cv=c_.mean(), se_cv=c_.std(ddof=1) / np.sqrt(n)))

# sensibilité au plancher K
Ks = np.arange(60, 101, 5)
by_K = [dict(K=float(k), strip=float(black_put(F, k, v, t).mean()), strip_gbm=float(black_put(F, k, sigma**2 * t, t).mean())) for k in Ks]

json.dump(dict(S0=S0, K=K, r=r, kappa=kappa, sigma=sigma, LT=LT, t=t.tolist(), F=F.tolist(), vol_eff=vol_eff.tolist(),
               put_ou=put_ou.tolist(), put_gbm=put_gbm.tolist(), strip_ou=float(put_ou.mean()), strip_gbm=float(put_gbm.mean()),
               mc={k: dict(prix=float(p), se=float(se), gain=float(eff[k])) for k, (p, se) in res.items()},
               strip_mc=list(map(float, check_strip)), geo_exact=float(geo_exact), corr=float(corr), conv=conv, by_K=by_K),
          open("plancher.json", "w"), indent=1)
