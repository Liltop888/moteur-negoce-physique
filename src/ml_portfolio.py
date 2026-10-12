"""
Apprentissage statistique (programme type M2 MVA) et optimisation de portefeuille.

1) Segmentation non supervisée (k-means sur variables standardisées) :
   regroupe les producteurs en profils (sains / tendus / critiques) sans étiquette préalable.
2) Détection d'anomalies (Isolation Forest) :
   repère les profils atypiques -> donnée erronée, montage inhabituel ou risque de fraude :
   à vérifier en priorité dans ta conformité (KYC).
3) Modèle supervisé de défaut (gradient boosting + validation croisée) :
   ne s'entraîne QUE si tu fournis un historique réel de défauts (ex. liste des Chapter 11
   de producteurs). Sans étiquettes réelles, aucun modèle supervisé n'est honnête.
4) Allocation optimale sous contrainte de risque (Rockafellar-Uryasev, 2000) :
   choisit combien de barils/jour prendre chez chaque producteur pour maximiser le profit
   espéré, avec une CVaR 95 % plafonnée et une ligne de crédit limitée. C'est un programme
   linéaire résolu sur les scénarios simulés conjointement (prix + défauts corrélés).
"""
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest, GradientBoostingClassifier
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import StandardScaler

FEATURES = ["dette_ebitda", "couverture_ct", "api", "soufre_pct", "cout_logistique", "proba_defaut"]


def segment_and_flag(df, seed=0):
    feats = [f for f in FEATURES + ["declin_annuel_pct"] if f in df]
    X = StandardScaler().fit_transform(df[feats].fillna(df[feats].median()))
    out = df.copy()
    k = min(3, len(df))
    km = KMeans(n_clusters=k, n_init=20, random_state=seed).fit(X)
    out["_cl"] = km.labels_
    ordre = out.groupby("_cl")["score_detresse"].mean().sort_values().index
    noms = ["Profil sain", "Profil tendu", "Profil critique"][:k]
    out["segment"] = out["_cl"].map(dict(zip(ordre, noms)))
    iso = IsolationForest(contamination=min(0.15, 1 / max(len(df), 2)) if len(df) < 20 else 0.1,
                          random_state=seed).fit(X)
    out["anomalie"] = np.where(iso.predict(X) == -1, "Profil atypique : vérifier", "")
    return out.drop(columns="_cl")


def train_default_model(df_hist, label_col="defaut"):
    """Entraîne un modèle de défaut sur un historique réel. Renvoie (modèle, AUC moyenne en CV)."""
    feats = [f for f in FEATURES if f in df_hist and f != "proba_defaut"]
    X, y = df_hist[feats].fillna(df_hist[feats].median()), df_hist[label_col].astype(int)
    model = GradientBoostingClassifier(random_state=0)
    auc = cross_val_score(model, X, y, cv=5, scoring="roc_auc").mean()
    return model.fit(X, y), float(auc), feats


def scenario_pnl(df, defaults, s0, jours, lgd):
    """P&L annuel (USD) par baril/jour engagé, par scénario et par producteur."""
    marge = (df["decote_negociee"] + df["ajust_qualite"] - df["cout_logistique"]
             - df["cout_financement"] - df["prime_risque_juridique"]).to_numpy()
    sain = marge * 365
    defaut = marge * 365 * 0.5 - lgd * s0 * jours  # marge sur la moitié de l'année, avance perdue
    return np.where(defaults, defaut, sain)


def optimize_allocation(df, pnl, s0, jours, ligne_credit_musd, cvar_max_musd, beta=0.95):
    """Programme linéaire CVaR. Variables : x (b/j par producteur), alpha (VaR), z (excès par scénario)."""
    n_s, n = pnl.shape
    cap = np.where(df["eligible"].to_numpy(), df["volume_dispo_bpj"].fillna(0).to_numpy(), 0.0)
    pnl_m = pnl / 1e6
    # Minimiser -profit espéré
    c = np.concatenate([-pnl_m.mean(axis=0), [0.0], np.zeros(n_s)])
    # z_s >= -pnl_s.x - alpha   <=>  -pnl_s.x - alpha - z_s <= 0
    A1 = np.hstack([-pnl_m, -np.ones((n_s, 1)), -np.eye(n_s)])
    b1 = np.zeros(n_s)
    # alpha + 1/((1-beta) N) sum z <= CVaR max
    A2 = np.concatenate([np.zeros(n), [1.0], np.full(n_s, 1 / ((1 - beta) * n_s))])[None, :]
    # capital immobilisé : sum x * s0 * jours <= ligne de crédit
    A3 = np.concatenate([np.full(n, s0 * jours / 1e6), [0.0], np.zeros(n_s)])[None, :]
    A = np.vstack([A1, A2, A3])
    b = np.concatenate([b1, [cvar_max_musd, ligne_credit_musd]])
    bounds = [(0, ci) for ci in cap] + [(None, None)] + [(0, None)] * n_s
    res = linprog(c, A_ub=A, b_ub=b, bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(res.message)
    x = res.x[:n]
    port = pnl_m @ x
    losses = -port
    var = np.quantile(losses, beta)
    stats = {
        "profit_espere_musd": float(port.mean()),
        "var95_musd": float(var),
        "cvar95_musd": float(losses[losses >= var].mean()),
        "capital_utilise_musd": float(x.sum() * s0 * jours / 1e6),
        "proba_perte": float((port < 0).mean()),
    }
    return x, stats
