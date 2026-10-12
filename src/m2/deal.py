"""La réponse finale : quelle structure proposer, à quel prix, pour quel rendement et quel pire cas.

Compare trois durées de prépaiement glissant (3, 6, 12 mois) pour 1 baril/jour livré :
  coût du crédit (CVA, défaut lié au prix β = 3), financement, plancher sur la moyenne à 70 $,
  décote minimale pour couvrir ces coûts, capital immobilisé, rendement du capital.
Puis taille un portefeuille de 13 producteurs et mesure la perte de crédit extrême
(défauts conditionnellement indépendants sachant le prix : tous dépendent du même baril).
"""
import json
import numpy as np
from scipy import optimize, stats
from chemins import PARAMS  # noqa: F401

P = json.load(open(PARAMS))
kappa, sigma, LT = P["kappa"], P["sigma"], P["niveau_lt"]
mu = np.log(LT)
S0, r, rec, PD1, beta, K = 96.24, 0.04, 0.5, 0.15, 3.0, 70.0
DECOTE = 7.40
dt = 1 / 12
a = np.exp(-kappa * dt); sd = sigma * np.sqrt((1 - a**2) / (2 * kappa))
rng = np.random.default_rng(3)
N = 100_000
X = np.empty((N, 13)); X[:, 0] = np.log(S0)
Z = rng.standard_normal((N // 2, 12)); Z = np.vstack([Z, -Z])
for k in range(12):
    X[:, k + 1] = X[:, k] * a + mu * (1 - a) + sd * Z[:, k]
S = np.exp(X[:, 1:])
t = np.arange(1, 13) * dt
m = np.log(S0) * np.exp(-kappa * t) + mu * (1 - np.exp(-kappa * t))
v = sigma**2 * (1 - np.exp(-2 * kappa * t)) / (2 * kappa)
F = np.exp(m + v / 2)

# intensité calée une fois pour toutes : 15 % de défaut à un an, β = 3
def pd_year(l0):
    lam = l0 * (S / LT) ** (-beta)
    return 1 - np.exp(-(lam * dt).sum(1)).mean()
lam0 = optimize.brentq(lambda l: pd_year(l) - PD1, 1e-4, 50)
lam = lam0 * (S / LT) ** (-beta)
surv = np.exp(-np.cumsum(lam * dt, 1))
q_all = np.hstack([np.ones((N, 1)), surv[:, :-1]]) - surv     # P(défaut au mois k | trajectoire)

rows = []
for T in [3, 6, 12]:
    av = F[:T] - DECOTE
    adv_rest = np.array([av[k:].sum() for k in range(T)])
    bbl_rest = np.arange(T, 0, -1)
    loss = np.maximum(adv_rest - rec * bbl_rest * S[:, :T], 0)
    disc = np.exp(-r * t[:T])
    cva = (q_all[:, :T] * loss * disc).sum(1).mean() / T                      # $ par baril livré
    fin = (av * (np.exp(r * t[:T]) - 1)).mean()                                 # $ par baril
    A = S[:, :T].mean(1)
    floor = np.exp(-r * T / 12) * np.maximum(K - A, 0).mean()                  # plancher sur la moyenne de la période
    cost = cva + fin + floor
    capital_bpd = av.mean() * 30.4 * (T + 1) / 2                               # avance moyenne en cours pour 1 b/j
    net = DECOTE - cost
    rows.append(dict(duree=T, cva=cva, financement=fin, plancher=floor, decote_minimale=cost,
                     marge_nette=net, capital_par_bpj=capital_bpd, rendement_capital=net * 365 / capital_bpd))
for r_ in rows:
    print({k: round(v, 3) for k, v in r_.items()})

# ---------------------------------------------------------------- portefeuille : 13 producteurs, prépaiement 3 mois
T, n_prod, bpd_each = 3, 13, 770                       # 10 010 b/j, ≈ 22 % de la production des 13 cibles
row = rows[0]
bbl_month = bpd_each * 30.4
av = F[:T] - DECOTE
adv_rest = np.array([av[k:].sum() for k in range(T)])
loss1 = np.maximum(adv_rest - rec * np.arange(T, 0, -1) * S[:, :T], 0) * bbl_month * np.exp(-r * t[:T])   # $ par producteur
q = q_all[:, :T]
cum = np.cumsum(q, 1)
L_port = np.zeros(N); n_def = np.zeros(N)
for _ in range(n_prod):                                  # défauts indépendants sachant le prix
    u = rng.random(N)
    k = (cum < u[:, None]).sum(1)
    hit = k < T
    L_port += np.where(hit, loss1[np.arange(N), np.minimum(k, T - 1)], 0); n_def += hit
# comparaison : mêmes probabilités, mais défauts indépendants du prix (on mélange les trajectoires)
L_ind = np.zeros(N)
for _ in range(n_prod):
    perm = rng.permutation(N)
    u = rng.random(N)
    k = (cum[perm] < u[:, None]).sum(1)
    hit = k < T
    L_ind += np.where(hit, loss1[np.arange(N), np.minimum(k, T - 1)], 0)
def cvar(x, a=0.99):
    th = np.quantile(x, a); return x[x >= th].mean()
volume = n_prod * bpd_each
pnl_annuel = row["marge_nette"] * volume * 365
capital = row["capital_par_bpj"] * volume
port = dict(producteurs=n_prod, bpj_par_producteur=bpd_each, volume_bpj=volume, pnl_annuel=pnl_annuel, capital=capital,
            perte_moyenne_trimestre=float(L_port.mean()), cvar99_trimestre=float(cvar(L_port)),
            cvar99_trimestre_independant=float(cvar(L_ind)), p_3defauts_plus=float((n_def >= 3).mean()),
            p_3defauts_plus_independant=None)
print({k: (round(v, 0) if isinstance(v, float) else v) for k, v in port.items()})
print("CVaR99 lié au prix / indépendant :", round(cvar(L_port) / cvar(L_ind), 2))
json.dump(dict(hyp=dict(S0=S0, decote=DECOTE, plancher=K, PD1=PD1, beta=beta, recouvrement=rec, r=r), structures=rows, portefeuille=port),
          open("deal.json", "w"), indent=1)
