"""Prévision en fourchette : GARCH(1,1) + simulation historique filtrée (Barone-Adesi et al., 1999).

On ne prédit pas la direction du prix : on prédit sa distribution. Le modèle
  1. estime une volatilité qui change dans le temps (GARCH) sur les rendements logarithmiques ;
  2. retire cette volatilité pour obtenir des chocs « standardisés », dont on garde la vraie forme
     (queues épaisses comprises) au lieu de supposer une loi normale ;
  3. simule des milliers de trajectoires futures en tirant ces chocs au hasard et en faisant
     évoluer la volatilité jour après jour ;
  4. lit la fourchette à 90 % (quantiles 5 % et 95 %) dans les prix simulés.
Le backtest refait ces prévisions dans le passé, avec seulement l'information disponible à chaque date,
et compte combien de fois le vrai prix est tombé dans la fourchette (objectif : 90 %).
"""
import numpy as np
from scipy import optimize, stats


def garch_filter(x, omega, alpha, beta, s0):
    s2 = np.empty(len(x) + 1)
    s2[0] = s0
    for t in range(len(x)):
        s2[t + 1] = omega + alpha * x[t] ** 2 + beta * s2[t]
    return s2                       # s2[t] = variance prévue pour le rendement t ; s2[-1] = pour demain


def fit_garch(r):
    x = np.asarray(r) - np.mean(r)
    v0 = x.var()

    def nll(p):
        om, a, b = np.exp(p[0]), 1 / (1 + np.exp(-p[1])), 1 / (1 + np.exp(-p[2]))
        if a + b >= 0.999:
            return 1e10
        s2 = garch_filter(x, om, a, b, v0)[:-1]
        return 0.5 * np.sum(np.log(s2) + x**2 / s2)

    best = None
    for start in ([np.log(v0 * 0.05), -2.5, 2.0], [np.log(v0 * 0.2), -1.5, 1.0]):
        res = optimize.minimize(nll, start, method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-6, "fatol": 1e-6})
        if best is None or res.fun < best.fun:
            best = res
    om, a, b = np.exp(best.x[0]), 1 / (1 + np.exp(-best.x[1])), 1 / (1 + np.exp(-best.x[2]))
    return dict(omega=om, alpha=a, beta=b, mu=float(np.mean(r)), v0=v0)


def simulate(r, p, horizon, n=4000, rng=None):
    """Trajectoires de rendements cumulés sur `horizon` pas (dérive nulle : on ne parie pas sur la direction)."""
    rng = rng or np.random.default_rng(0)
    x = np.asarray(r) - p["mu"]
    s2 = garch_filter(x, p["omega"], p["alpha"], p["beta"], p["v0"])
    z = x / np.sqrt(s2[:-1])
    z = (z - z.mean()) / z.std()
    var = np.full(n, s2[-1])
    cum = np.zeros((n, horizon))
    tot = np.zeros(n)
    for h in range(horizon):
        eps = rng.choice(z, n) * np.sqrt(var)
        tot = tot + eps
        cum[:, h] = tot
        var = p["omega"] + p["alpha"] * eps**2 + p["beta"] * var
    return cum


def forecast(prices, horizons, qs=(0.05, 0.25, 0.5, 0.75, 0.95), n=4000, window=2600):
    """prices : série pandas de prix > 0 ; horizons : dict nom -> nombre de pas."""
    lp = np.log(prices.values)
    r = np.diff(lp)[-window:]
    p = fit_garch(r)
    H = max(horizons.values())
    cum = simulate(r, p, H, n)
    last = prices.values[-1]
    fan = np.exp(np.quantile(cum, qs, axis=0)) * last          # (quantiles, pas)
    out = {k: dict(pas=h, bas=float(fan[0, h - 1]), median=float(fan[2, h - 1]), haut=float(fan[-1, h - 1])) for k, h in horizons.items()}
    vol_annuelle = None
    return dict(dernier=float(last), params=p, fan=fan.tolist(), horizons=out, vol_jour=float(np.sqrt(garch_filter(r - p["mu"], p["omega"], p["alpha"], p["beta"], p["v0"])[-1])))


def backtest(prices, h, step, n_origins, refit_every=13, n=2000, window=2600, level=0.90):
    """Prévisions refaites dans le passé : à chaque origine, seulement les données disponibles ce jour-là."""
    lp = np.log(prices.values)
    dates = prices.index
    T = len(lp)
    origins = list(range(T - 1 - h - step * (n_origins - 1), T - h, step))
    origins = [o for o in origins if o > 300]
    hits, rows, p = [], [], None
    rng = np.random.default_rng(1)
    lo_q, hi_q = (1 - level) / 2, 1 - (1 - level) / 2
    for i, o in enumerate(origins):
        r = np.diff(lp[: o + 1])[-window:]
        if p is None or i % refit_every == 0:
            p = fit_garch(r)
        cum = simulate(r, p, h, n, rng)[:, -1]
        lo, hi = np.quantile(cum, [lo_q, hi_q])
        real = lp[o + h] - lp[o]
        hit = bool(lo <= real <= hi)
        hits.append(hit)
        rows.append(dict(date=str(dates[o].date()), cible=str(dates[o + h].date()), prix=float(np.exp(lp[o])),
                         bas=float(np.exp(lp[o] + lo)), haut=float(np.exp(lp[o] + hi)), reel=float(np.exp(lp[o + h])), dedans=hit))
    k, N = len(hits) - sum(hits), len(hits)
    pi = 1 - level
    ph = k / N if N else 0
    if 0 < k < N:
        lr = -2 * ((N - k) * np.log(1 - pi) + k * np.log(pi) - (N - k) * np.log(1 - ph) - k * np.log(ph))
        pval = float(1 - stats.chi2.cdf(lr, 1))
    else:
        pval = None
    return dict(couverture=sum(hits) / N if N else None, n=N, p_kupiec=pval, lignes=rows)


def naive_backtest(prices, h, step, n_origins, level=0.90, window=2600):
    """Comparaison : fourchette « loi normale, volatilité fixe » estimée sur la même fenêtre."""
    lp = np.log(prices.values)
    T = len(lp)
    origins = [o for o in range(T - 1 - h - step * (n_origins - 1), T - h, step) if o > 300]
    z = stats.norm.ppf(1 - (1 - level) / 2)
    hits = []
    for o in origins:
        r = np.diff(lp[: o + 1])[-window:]
        sd = r.std() * np.sqrt(h)
        real = lp[o + h] - lp[o]
        hits.append(abs(real) <= z * sd)
    return sum(hits) / len(hits) if hits else None
