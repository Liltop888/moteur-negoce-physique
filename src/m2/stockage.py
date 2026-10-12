"""Module 3 — Quand vendre un baril stocké ? Arrêt optimal par Longstaff-Schwartz.

Cours du M2 mobilisés : « Options américaines : théorie et méthodes numériques », « Convexité, optimisation
et contrôle stochastique », « Probabilités numériques » (régression Monte Carlo).

Situation : un négociant détient un baril en cuve. Chaque mois (12 dates), il peut le vendre au prix spot
ou attendre, en payant le stockage c par mois. Problème d'arrêt optimal :
    V(S0) = sup_τ E[ e^{-rτ} S_τ − c · Σ_{k<τ} e^{-r k/12} ]
Le prix suit le modèle de Schwartz calibré sur le WTI (mesure historique : négociant non couvert).
Méthodes : (1) Longstaff-Schwartz (2001), régression sur des polynômes du prix ;
           (2) référence par programmation dynamique sur grille (quadrature de Gauss-Hermite) ;
           (3) borne basse honnête : politique LSM appliquée à de nouveaux scénarios indépendants.
"""
from chemins import PARAMS, DATA  # noqa: F401  (fixe aussi le dossier de sortie)
import json
import numpy as np

P = json.load(open(PARAMS))
kappa, sigma, mu = P["kappa"], P["sigma"], np.log(P["niveau_lt"])
r, c, M, dt = 0.04, 0.45, 12, 1 / 12
a = np.exp(-kappa * dt)
sd = sigma * np.sqrt((1 - a**2) / (2 * kappa))
disc = np.exp(-r * dt)


def paths(S0, n, rng):
    X = np.empty((n, M + 1)); X[:, 0] = np.log(S0)
    Z = rng.standard_normal((n // 2, M)); Z = np.vstack([Z, -Z])
    for k in range(M):
        X[:, k + 1] = X[:, k] * a + mu * (1 - a) + sd * Z[:, k]
    return np.exp(X)


def basis(s):
    x = s / 65.0
    return np.column_stack([np.ones_like(x), x, x**2, x**3])


def lsm_fit(S):
    """Régressions de la valeur de continuation, de la date M-1 à 1 (on ne garde que les coefficients)."""
    n = S.shape[0]
    cash = S[:, M].copy()                 # à l'échéance on vend
    betas = [None] * (M + 1)
    for k in range(M - 1, 0, -1):
        cont_target = disc * cash - c     # attendre un mois : on paie le stockage, valeur actualisée
        B = basis(S[:, k])
        beta, *_ = np.linalg.lstsq(B, cont_target, rcond=None)
        betas[k] = beta
        cont = B @ beta
        sell = S[:, k] >= cont
        cash = np.where(sell, S[:, k], cont_target)
    return betas


def lsm_value(S, betas):
    """Applique la règle d'arrêt (vendre si prix ≥ continuation estimée) à des scénarios donnés."""
    n = S.shape[0]
    val = np.zeros(n); alive = np.ones(n, bool); acc = np.zeros(n)  # acc : coûts de stockage actualisés
    for k in range(1, M + 1):
        acc[alive] += c * np.exp(-r * (k - 1) * dt)
        if k < M:
            sell = alive & (S[:, k] >= basis(S[:, k]) @ betas[k])
        else:
            sell = alive.copy()
        val[sell] = np.exp(-r * k * dt) * S[sell, k] - acc[sell]
        alive &= ~sell
    return val


def value(S0, rng, n=100_000):
    S_fit = paths(S0, n, rng)
    betas = lsm_fit(S_fit)
    hold = lsm_value(paths(S0, n, rng), betas)        # nouveaux scénarios -> borne basse sans biais d'optimisme
    return max(S0, hold.mean()), hold.mean(), hold.std() / np.sqrt(n), betas


# ---------------------------------------------------------------- référence : programmation dynamique sur grille
gh_x, gh_w = np.polynomial.hermite_e.hermegauss(40); gh_w = gh_w / gh_w.sum()
grid = np.linspace(np.log(15), np.log(250), 1500)


def dp_value():
    V = np.exp(grid)                                   # à l'échéance
    boundary = [None] * (M + 1)
    for k in range(M - 1, -1, -1):
        nxt = grid[:, None] * a + mu * (1 - a) + sd * gh_x[None, :]
        cont = disc * (np.interp(nxt, grid, V) * gh_w).sum(1) - c
        if k == 0:
            return cont, boundary
        sell = np.exp(grid) >= cont
        boundary[k] = float(np.exp(grid[np.argmax(sell)])) if sell.any() else None
        V = np.maximum(np.exp(grid), cont)


cont0, bnd = dp_value()
rng = np.random.default_rng(1)
rows = []
for S0 in [40, 50, 55, 60, 65, 70, 80, 96.24]:
    v_lsm, hold, se, _ = value(S0, rng)
    v_dp = max(S0, float(np.interp(np.log(S0), grid, cont0)))
    rows.append(dict(S0=S0, vendre_maintenant=S0, valeur_lsm=v_lsm, attendre_lsm=hold, se=se, valeur_dp=v_dp,
                     prime_attente=v_lsm - S0))
    print(f"S0={S0:6.2f}  vendre={S0:6.2f}  LSM={v_lsm:7.3f} (attendre {hold:7.3f} ± {se:.3f})  grille={v_dp:7.3f}")
print("Frontière de vente (prix au-dessus duquel on vend), mois 1 à 11 :", [round(b, 1) for b in bnd[1:M]])
json.dump(dict(r=r, c=c, rows=rows, frontiere=bnd[1:M]), open("stockage.json", "w"), indent=1)

# sensibilité à κ (mal estimé : IC 0,09-1,77) — prime d'attente à 50 $ et frontière au mois 1, par la grille
sens = []
for kap in [0.09, 0.45, 0.8995, 1.35, 1.77]:
    kappa = kap; a = np.exp(-kappa * dt); sd = sigma * np.sqrt((1 - a**2) / (2 * kappa))
    c0, b = dp_value()
    sens.append(dict(kappa=kap, prime_50=float(np.interp(np.log(50), grid, c0)) - 50, frontiere_m1=b[1]))
print(sens)
d = json.load(open("stockage.json")); d["sens_kappa"] = sens; json.dump(d, open("stockage.json", "w"), indent=1)
