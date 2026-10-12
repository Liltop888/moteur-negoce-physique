"""Module 4 — Le coût du risque de défaut d'un préfinancement : CVA avec wrong-way risk.

Cours du M2 mobilisés : « Modèles de taux et produits dérivés : risque de contrepartie »,
« Stratégie quantitative : application au marché du crédit » (modèles à intensité).

Situation : le négociant paie d'avance 12 livraisons mensuelles d'un baril chacune, au prix à terme moins
la décote (7,4 $/b). Si le producteur fait défaut au mois k, les livraisons restantes sont perdues ; on
récupère 50 % de la valeur des réserves nanties, qui vaut (barils restants × prix du jour).
    Perte_k = max( avance restante − 0,5 × barils restants × S_k , 0 )
Défaut : processus de Cox d'intensité λ_t = λ0 · (S_t / 65,47)^(−β).
   β = 0  -> défaut indépendant du prix ;  β > 0 -> le producteur fait défaut quand le prix baisse (wrong-way).
λ0 est recalé pour chaque β afin que la probabilité de défaut à un an reste 15 % : seule la dépendance change.
CVA = E[ Σ_k e^{−r t_k} · P(défaut dans le mois k | trajectoire de prix) · Perte_k ]   (Monte Carlo conditionnel)
"""
from chemins import PARAMS, DATA  # noqa: F401  (fixe aussi le dossier de sortie)
import json
import numpy as np
from scipy import optimize

P = json.load(open(PARAMS))
kappa, sigma, LT = P["kappa"], P["sigma"], P["niveau_lt"]
mu = np.log(LT)
S0, r, decote, rec, PD1 = 96.24, 0.04, 7.4, 0.5, 0.15
M, dt = 12, 1 / 12
t = np.arange(1, M + 1) * dt
a = np.exp(-kappa * dt); sd = sigma * np.sqrt((1 - a**2) / (2 * kappa))

rng = np.random.default_rng(11)
N = 200_000
X = np.empty((N, M + 1)); X[:, 0] = np.log(S0)
Z = rng.standard_normal((N // 2, M)); Z = np.vstack([Z, -Z])
for k in range(M):
    X[:, k + 1] = X[:, k] * a + mu * (1 - a) + sd * Z[:, k]
S = np.exp(X[:, 1:])                       # prix aux 12 dates de livraison

m = X[:, 0][0] * np.exp(-kappa * t) + mu * (1 - np.exp(-kappa * t))
v = sigma**2 * (1 - np.exp(-2 * kappa * t)) / (2 * kappa)
F = np.exp(m + v / 2)
avance = F - decote                        # prix payé d'avance pour chaque livraison
adv_rest = np.array([avance[k:].sum() for k in range(M)])   # avance non encore livrée si défaut avant la livraison k
bbl_rest = np.arange(M, 0, -1)
loss = np.maximum(adv_rest[None, :] - rec * bbl_rest[None, :] * S, 0)   # perte si défaut au mois k
disc = np.exp(-r * t)
prime_avance = (avance * np.exp(-r * 0)).sum()


def default_probs(lam0, beta):
    lam = lam0 * (S / LT) ** (-beta)
    H = np.cumsum(lam * dt, axis=1)
    surv = np.exp(-H)
    surv_prev = np.hstack([np.ones((N, 1)), surv[:, :-1]])
    return surv_prev - surv, 1 - surv[:, -1]


res = []
for beta in [0, 1, 2, 3, 4]:
    lam0 = optimize.brentq(lambda l: default_probs(l, beta)[1].mean() - PD1, 1e-4, 50)
    q, pd1 = default_probs(lam0, beta)
    per_path = (q * loss * disc).sum(1)
    cva = per_path.mean(); se = per_path.std() / np.sqrt(N)
    # exposition attendue conditionnelle au défaut, et prob. de défaut selon le prix final
    low = S[:, -1] < np.quantile(S[:, -1], 0.2)
    res.append(dict(beta=beta, lam0=lam0, cva_total=cva, se=se, cva_par_baril=cva / M, pd_prix_bas=float(pd1[low].mean()),
                    pd_prix_haut=float(pd1[S[:, -1] > np.quantile(S[:, -1], 0.8)].mean()),
                    perte_moy_si_defaut=float((q * loss).sum() / q.sum())))
    print(f"β={beta}: CVA {cva:.2f} $ (± {se:.3f}) soit {cva / M:.2f} $/baril ; PD si prix bas {res[-1]['pd_prix_bas']:.1%} / prix haut {res[-1]['pd_prix_haut']:.1%} ; perte moyenne si défaut {res[-1]['perte_moy_si_defaut']:.1f} $")

# contrôle analytique pour β = 0 : CVA = Σ P(défaut mois k) · E[perte_k] · actualisation
lam_ind = -np.log(1 - PD1)
pk = np.exp(-lam_ind * (t - dt)) - np.exp(-lam_ind * t)
cva_check = (pk * loss.mean(0) * disc).sum()
print(f"contrôle β=0 : {cva_check:.3f}")
json.dump(dict(S0=S0, decote=decote, recouvrement=rec, PD1=PD1, avance_totale=float(avance.sum()), res=res, check_beta0=float(cva_check)),
          open("cva.json", "w"), indent=1)

# queue de la perte : on tire explicitement l'instant de défaut sur chaque trajectoire
tail = []
for row in res:
    q, _ = default_probs(row["lam0"], row["beta"])
    u = np.random.default_rng(5).random(N)
    cum = np.cumsum(q, axis=1)
    k = (cum < u[:, None]).sum(1)                       # k = 12 -> pas de défaut
    L = np.where(k < M, loss[np.arange(N), np.minimum(k, M - 1)] * disc[np.minimum(k, M - 1)], 0.0)
    thr = np.quantile(L, 0.99)
    tail.append(dict(beta=row["beta"], moyenne=float(L.mean()), var99=float(thr), cvar99=float(L[L >= thr].mean()),
                     p_perte_sup_250=float((L > 250).mean())))
    print(tail[-1])
d = json.load(open("cva.json")); d["queue"] = tail; json.dump(d, open("cva.json", "w"), indent=1)
