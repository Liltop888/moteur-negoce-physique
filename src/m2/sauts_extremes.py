"""Module 1 — Modèles de saut et valeurs extrêmes sur le WTI journalier.

Cours du M2 mobilisés : « Introduction aux modèles de saut », « Mesures de risque en finance et extrêmes ».
1. Merton (1976) : rendement journalier = diffusion gaussienne + sauts de Poisson à taille gaussienne,
   estimé par maximum de vraisemblance (densité = mélange de Poisson tronqué).
2. Théorie des valeurs extrêmes : loi de Pareto généralisée (GPD) sur les pertes au-delà d'un seuil
   (peaks over threshold), VaR et CVaR extrêmes.
3. Backtest : modèles estimés sur 2010-2019, VaR 99 % testée sur 2020-2026 (test de Kupiec).
"""
from chemins import PARAMS, DATA  # noqa: F401  (fixe aussi le dossier de sortie)
import json
import numpy as np
import pandas as pd
from scipy import stats, optimize

df = pd.read_csv(DATA, parse_dates=["Date"]).dropna()
df = df[df.Date >= "2010-01-01"]
neg = df[df.Price <= 0]
df = df[df.Price > 0]                      # 20 avril 2020 : prix négatif, log impossible
r = np.log(df.Price).diff().dropna()
r.index = df.Date.iloc[1:].values
train, test = r[:"2019-12-31"], r["2020-01-01":]
print(f"rendements : {len(r)} (apprentissage {len(train)}, test {len(test)}); jours à prix négatif retirés : {len(neg)}")


# ---------------------------------------------------------------- 1. Merton jump-diffusion
def merton_logpdf(x, mu, sig, lam, mj, sj, nmax=12):
    """Densité du rendement journalier : somme sur k sauts de Poisson(λ) × N(mu + k mj, sig² + k sj²)."""
    k = np.arange(nmax)[:, None]
    w = stats.poisson.pmf(k, lam)
    dens = (w * stats.norm.pdf(x[None, :], mu + k * mj, np.sqrt(sig**2 + k * sj**2))).sum(0)
    return np.log(dens + 1e-300)


def fit_merton(x):
    x = np.asarray(x)
    def nll(p):
        mu, ls, ll, mj, lsj = p
        return -merton_logpdf(x, mu, np.exp(ls), np.exp(ll), mj, np.exp(lsj)).sum()
    p0 = [x.mean(), np.log(x.std() * 0.7), np.log(0.05), 0.0, np.log(x.std() * 3)]
    res = optimize.minimize(nll, p0, method="Nelder-Mead", options={"maxiter": 20000, "xatol": 1e-8, "fatol": 1e-8})
    mu, ls, ll, mj, lsj = res.x
    return dict(mu=mu, sig=np.exp(ls), lam=np.exp(ll), mj=mj, sj=np.exp(lsj), nll=res.fun)


def merton_quantile(q, p):
    lo, hi = -1.0, 1.0
    cdf = lambda z: sum(stats.poisson.pmf(k, p["lam"]) * stats.norm.cdf(z, p["mu"] + k * p["mj"], np.sqrt(p["sig"]**2 + k * p["sj"]**2)) for k in range(12))
    return optimize.brentq(lambda z: cdf(z) - q, lo, hi)


mfull = fit_merton(r)
mtrain = fit_merton(train)
# test du rapport de vraisemblance : Merton contre gaussien (le gaussien est le cas λ = 0)
nll_gauss = -stats.norm.logpdf(r, r.mean(), r.std()).sum()
LR = 2 * (nll_gauss - mfull["nll"])
print("Merton (2010-2026) :", {k: round(v, 5) for k, v in mfull.items()}, " LR =", round(LR, 1))

# ---------------------------------------------------------------- 2. Valeurs extrêmes (POT / GPD)
def fit_gpd(x, qthr=0.95):
    loss = -np.asarray(x)
    u = np.quantile(loss, qthr)
    exc = loss[loss > u] - u
    xi, _, beta = stats.genpareto.fit(exc, floc=0)
    return dict(u=u, xi=xi, beta=beta, n=len(loss), nu=len(exc))


def gpd_var_cvar(g, alpha):
    """VaR et CVaR (en perte positive) de McNeil-Frey pour un niveau alpha (ex. 0.99)."""
    var = g["u"] + g["beta"] / g["xi"] * (((g["n"] / g["nu"]) * (1 - alpha)) ** (-g["xi"]) - 1)
    cvar = (var + g["beta"] - g["xi"] * g["u"]) / (1 - g["xi"])
    return var, cvar


gfull = fit_gpd(r)
print("GPD pertes (2010-2026) :", {k: round(v, 4) if isinstance(v, float) else v for k, v in gfull.items()})

# bootstrap de ξ (paramètre de queue)
rng = np.random.default_rng(0)
xis = []
lossf = -r.values
for _ in range(300):
    s = rng.choice(r.values, len(r))
    xis.append(fit_gpd(s)["xi"])
xi_ci = np.percentile(xis, [2.5, 97.5])
print("xi IC95 bootstrap :", xi_ci.round(3))

# ---------------------------------------------------------------- 3. Comparaison des VaR (2010-2026)
levels = [0.99, 0.999]
table = []
for a in levels:
    v_norm = -(r.mean() + r.std() * stats.norm.ppf(1 - a))
    v_emp = -np.quantile(r, 1 - a)
    v_mer = -merton_quantile(1 - a, mfull)
    v_gpd, c_gpd = gpd_var_cvar(gfull, a)
    c_emp = -r[r <= np.quantile(r, 1 - a)].mean()
    c_norm = -(r.mean() - r.std() * stats.norm.pdf(stats.norm.ppf(1 - a)) / (1 - a))
    table.append(dict(niveau=a, var_normale=v_norm, var_merton=v_mer, var_gpd=v_gpd, var_empirique=v_emp,
                      cvar_normale=c_norm, cvar_gpd=c_gpd, cvar_empirique=c_emp))
tab = pd.DataFrame(table)
print((tab.set_index("niveau") * 100).round(2).T)

# ---------------------------------------------------------------- 4. Backtest hors échantillon 2020-2026
def kupiec(n_exc, n, p):
    if n_exc == 0:
        return 1.0
    ph = n_exc / n
    lr = -2 * ((n - n_exc) * np.log(1 - p) + n_exc * np.log(p) - (n - n_exc) * np.log(1 - ph) - n_exc * np.log(ph))
    return 1 - stats.chi2.cdf(lr, 1)


gtrain = fit_gpd(train)
a = 0.99
vars_train = {
    "Normale": -(train.mean() + train.std() * stats.norm.ppf(1 - a)),
    "Merton (sauts)": -merton_quantile(1 - a, mtrain),
    "Valeurs extrêmes (GPD)": gpd_var_cvar(gtrain, a)[0],
}
bt = []
for name, v in vars_train.items():
    n_exc = int((test < -v).sum())
    bt.append(dict(modele=name, var99=v, depassements=n_exc, attendus=round(len(test) * (1 - a), 1),
                   taux=n_exc / len(test), p_kupiec=kupiec(n_exc, len(test), 1 - a)))
bt = pd.DataFrame(bt)
print(bt.round(4))

# pire journée et contexte
worst = r.nsmallest(5)
print("5 pires journées :\n", (worst * 100).round(1))

out = dict(
    n=len(r), n_train=len(train), n_test=len(test), neg_days=[str(d.date()) for d in neg.Date],
    merton=mfull, merton_train=mtrain, LR=LR,
    merton_jumps_per_year=mfull["lam"] * 252,
    gpd=gfull, xi_ci=list(xi_ci), var_table=tab.to_dict("records"), backtest=bt.to_dict("records"),
    worst=[(str(pd.Timestamp(d).date()), float(v)) for d, v in worst.items()],
    vol_annual=float(r.std() * np.sqrt(252)),
)
json.dump(out, open("sauts_extremes.json", "w"), indent=1, default=float)
r.to_frame("r").to_csv("wti_rendements.csv")


# ---------------------------------------------------------------- 5. Volatilité par vagues : GARCH(1,1) + EVT (McNeil & Frey, 2000)
def garch_filter(x, omega, alpha, beta, s0):
    s2 = np.empty(len(x)); s2[0] = s0
    for t in range(1, len(x)):
        s2[t] = omega + alpha * x[t - 1] ** 2 + beta * s2[t - 1]
    return s2


def fit_garch(x):
    x = np.asarray(x) - np.mean(x)
    v0 = x.var()
    def nll(p):
        om, a, b = np.exp(p[0]), 1 / (1 + np.exp(-p[1])), 1 / (1 + np.exp(-p[2]))
        if a + b >= 0.9999:
            return 1e10
        s2 = garch_filter(x, om, a, b, v0)
        return 0.5 * np.sum(np.log(s2) + x**2 / s2)
    res = optimize.minimize(nll, [np.log(v0 * 0.05), -2.5, 2.0], method="Nelder-Mead", options={"maxiter": 20000})
    om, a, b = np.exp(res.x[0]), 1 / (1 + np.exp(-res.x[1])), 1 / (1 + np.exp(-res.x[2]))
    return dict(omega=om, alpha=a, beta=b, v0=v0)


mu_tr = train.mean()
gp = fit_garch(train.values)
print("GARCH(1,1) 2010-2019 :", {k: round(v, 6) for k, v in gp.items()}, " persistance =", round(gp["alpha"] + gp["beta"], 4))
allx = r.values - mu_tr
s2_all = garch_filter(allx, gp["omega"], gp["alpha"], gp["beta"], gp["v0"])   # paramètres figés sur 2010-2019
sig_all = np.sqrt(s2_all)
z_train = allx[: len(train)] / sig_all[: len(train)]
gz = fit_gpd(z_train)
a = 0.99
q_norm = stats.norm.ppf(1 - a)
q_evt = -gpd_var_cvar(gz, a)[0]
sig_test = sig_all[len(train):]
cond = []
for name, q in [("GARCH + loi normale", q_norm), ("GARCH + valeurs extrêmes", q_evt)]:
    var_t = -(mu_tr + sig_test * q)
    exc = (test.values < -var_t).astype(int)
    n_exc = int(exc.sum())
    # test d'indépendance de Christoffersen : les dépassements arrivent-ils en grappes ?
    n00 = n01 = n10 = n11 = 0
    for i in range(1, len(exc)):
        p_, c_ = exc[i - 1], exc[i]
        n00 += (p_ == 0) & (c_ == 0); n01 += (p_ == 0) & (c_ == 1); n10 += (p_ == 1) & (c_ == 0); n11 += (p_ == 1) & (c_ == 1)
    pi0, pi1, pi = n01 / max(n00 + n01, 1), n11 / max(n10 + n11, 1), (n01 + n11) / (n00 + n01 + n10 + n11)
    ll = lambda p, a_, b_: (a_ * np.log(1 - p) if a_ else 0) + (b_ * np.log(p) if b_ else 0)
    lr_ind = -2 * (ll(pi, n00 + n10, n01 + n11) - ll(pi0, n00, n01) - ll(pi1, n10, n11))
    cond.append(dict(modele=name, var99=float(np.median(var_t)), depassements=n_exc, attendus=round(len(test) * (1 - a), 1),
                     taux=n_exc / len(test), p_kupiec=kupiec(n_exc, len(test), 1 - a), p_christoffersen=1 - stats.chi2.cdf(lr_ind, 1)))
    if "extrêmes" in name:
        pd.DataFrame({"r": test.values, "var": -var_t}, index=test.index).to_csv("var_garch_evt_test.csv")
cond = pd.DataFrame(cond)
print(cond.round(4))
out.update(garch=gp, gpd_z=gz, backtest_cond=cond.to_dict("records"), q_evt=q_evt, q_norm=q_norm)
json.dump(out, open("sauts_extremes.json", "w"), indent=1, default=float)
