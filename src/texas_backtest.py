"""
Modèle empirique de sortie des opérateurs pétroliers du Texas et backtest hors échantillon.

Données : Texas Railroad Commission, « Production Data Query Dump » (dossier PDQ_DSV décompressé).
  - OG_OPERATOR_CYCLE_DATA_TABLE.dsv     production mensuelle par opérateur
  - OG_REGULATORY_LEASE_DW_DATA_TABLE.dsv bail -> opérateur actuel, district
  - OG_WELL_COMPLETION_DATA_TABLE.dsv     puits et date d'arrêt

Protocole :
  1. Indicateurs connus à une date t : déclin 12 mois, variation 6 mois, irrégularité (CV mensuel),
     nombre de mois sans production. Univers : 100 à 20 000 barils/jour.
  2. Sortie : production de la 2e année après t < 10 % de celle des 12 derniers mois.
  3. Logit estimé sur la crise de 2015 (t = 12/2014), testé tel quel sur la crise de 2020 (t = 12/2019).
  4. Robustesse (seuils, univers, protocole inversé), IC bootstrap de l'AUC.
  5. Modèle réestimé sur les deux crises, appliqué à la dernière date complète.

Usage :
  python texas_backtest.py --pdq chemin/vers/PDQ_DSV --date 202605 --out resultats
Sorties : resultats/backtest.json (agrégé, anonymisé) et resultats/operateurs.xlsx (noms : usage privé).
"""
import argparse, json, os
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.metrics import roc_auc_score, roc_curve

from crude_quality import GRADES, quality_adjustment, grade_for_district
from logistics import best_hub

FE = ["declin_12m", "accel_6m", "volatilite", "mois_a_zero"]
# Numéro de district interne -> nom de district RRC (table GP_DISTRICT_DATA_TABLE)
DMAP = {"01": "01", "02": "02", "03": "03", "04": "04", "05": "05", "06": "06", "07": "6E",
        "08": "7B", "09": "7C", "10": "08", "11": "8A", "13": "09", "14": "10"}


def charger(pdq):
    src = os.path.join(pdq, "OG_OPERATOR_CYCLE_DATA_TABLE.dsv")
    df = pd.read_csv(src, sep="}", dtype={"OPERATOR_NO": str, "CYCLE_YEAR_MONTH": str, "OPERATOR_NAME": str},
                     usecols=["OPERATOR_NO", "CYCLE_YEAR_MONTH", "OPERATOR_NAME",
                              "OPER_OIL_PROD_VOL", "OPER_COND_PROD_VOL"])
    df = df[df.CYCLE_YEAR_MONTH >= "201301"]
    df["liq"] = df.OPER_OIL_PROD_VOL.fillna(0) + df.OPER_COND_PROD_VOL.fillna(0)  # pétrole + condensat
    noms = df.sort_values("CYCLE_YEAR_MONTH").groupby("OPERATOR_NO").OPERATOR_NAME.last()
    wide = df.pivot_table(index="OPERATOR_NO", columns="CYCLE_YEAR_MONTH", values="liq", aggfunc="sum").fillna(0)

    reg = pd.read_csv(os.path.join(pdq, "OG_REGULATORY_LEASE_DW_DATA_TABLE.dsv"), sep="}", dtype=str,
                      usecols=["OIL_GAS_CODE", "DISTRICT_NO", "LEASE_NO", "OPERATOR_NO"]) \
        .drop_duplicates(["OIL_GAS_CODE", "DISTRICT_NO", "LEASE_NO"])
    w = pd.read_csv(os.path.join(pdq, "OG_WELL_COMPLETION_DATA_TABLE.dsv"), sep="}", dtype=str,
                    usecols=["OIL_GAS_CODE", "DISTRICT_NO", "LEASE_NO", "WELL_SHUTIN_DT"])
    w = w.merge(reg, on=["OIL_GAS_CODE", "DISTRICT_NO", "LEASE_NO"], how="inner")
    w["arret"] = w.WELL_SHUTIN_DT.notna() & w.WELL_SHUTIN_DT.fillna("000000").str.strip().ne("000000")
    puits = w.groupby("OPERATOR_NO").agg(nb_puits=("arret", "size"), puits_arret=("arret", "sum"))
    puits["part_puits_arret_pct"] = (puits.puits_arret / puits.nb_puits * 100).round(1)
    oil = reg[reg.OIL_GAS_CODE == "O"]
    dist = oil.groupby(["OPERATOR_NO", "DISTRICT_NO"]).size().reset_index(name="n") \
        .sort_values("n").drop_duplicates("OPERATOR_NO", keep="last").set_index("OPERATOR_NO").DISTRICT_NO
    statique = pd.concat([puits, dist.rename("district_no")], axis=1)
    return wide, noms, statique


class Panel:
    def __init__(self, wide):
        self.wide, self.M, self.X = wide, list(wide.columns), wide.to_numpy()

    def t(self, ym):
        return self.M.index(ym)

    def indicateurs(self, t):
        X = self.X
        l12, p12 = X[:, t - 11:t + 1], X[:, t - 23:t - 11]
        l6, p6 = X[:, t - 5:t + 1], X[:, t - 11:t - 5]
        f = pd.DataFrame(index=self.wide.index)
        f["prod_bpj"] = l12.sum(1) / 365
        f["declin_12m"] = np.where(p12.sum(1) > 0, l12.sum(1) / np.maximum(p12.sum(1), 1) - 1, np.nan)
        f["accel_6m"] = np.where(p6.sum(1) > 0, l6.sum(1) / np.maximum(p6.sum(1), 1) - 1, np.nan)
        m = l12.mean(1)
        f["volatilite"] = np.where(m > 0, l12.std(1) / np.maximum(m, 1e-9), np.nan)
        f["mois_a_zero"] = (l12 == 0).sum(1)
        return f

    def echantillon(self, ym, seuil=0.10, lo=100, hi=20000):
        t = self.t(ym)
        f = self.indicateurs(t)
        f = f[(f.prod_bpj >= lo) & (f.prod_bpj <= hi)].dropna(subset=FE)
        f = borner(f)
        l12, nxt = self.X[:, t - 11:t + 1].sum(1), self.X[:, t + 13:t + 25].sum(1)
        y = (nxt < seuil * l12).astype(int)
        f["sortie"] = y[self.wide.index.get_indexer(f.index)]
        return f


def borner(f):
    g = f.copy()
    g["declin_12m"] = g.declin_12m.clip(-1, 2)
    g["accel_6m"] = g.accel_6m.clip(-1, 2)
    g["volatilite"] = g.volatilite.clip(0, 3)
    return g


def logit(df):
    return sm.Logit(df.sortie, sm.add_constant(df[FE])).fit(disp=0)


def predire(m, df):
    return m.predict(sm.add_constant(df[FE], has_constant="add"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdq", required=True, help="dossier PDQ_DSV décompressé")
    ap.add_argument("--date", default="202605", help="dernier mois complet (AAAAMM)")
    ap.add_argument("--prix", type=float, default=97.31, help="prix WTI de référence")
    ap.add_argument("--out", default="resultats")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    wide, noms, statique = charger(a.pdq)
    P = Panel(wide)
    tr, te = P.echantillon("201412"), P.echantillon("201912")
    m = logit(tr)
    p = predire(m, te)
    res = {"n_train": len(tr), "taux_train": float(tr.sortie.mean()), "n_test": len(te), "taux_test": float(te.sortie.mean()),
           "logit": {"coef": m.params.round(3).to_dict(), "se": m.bse.round(3).to_dict(),
                     "p": m.pvalues.round(4).to_dict(), "pseudo_r2": round(m.prsquared, 3)},
           "auc": round(roc_auc_score(te.sortie, p), 3),
           "auc_declin_seul": round(roc_auc_score(te.sortie, -te.declin_12m), 3)}
    fpr, tpr, _ = roc_curve(te.sortie, p)
    res["roc"] = {"fpr": fpr.round(4).tolist(), "tpr": tpr.round(4).tolist()}
    rng, y, pp, aucs = np.random.default_rng(0), te.sortie.to_numpy(), np.asarray(p), []
    for _ in range(1000):
        i = rng.integers(0, len(y), len(y))
        if y[i].min() != y[i].max():
            aucs.append(roc_auc_score(y[i], pp[i]))
    res["auc_ic95"] = [round(np.percentile(aucs, 2.5), 3), round(np.percentile(aucs, 97.5), 3)]
    q = te.assign(p=p, q=pd.qcut(p, 5, labels=[1, 2, 3, 4, 5]))
    res["quintiles"] = q.groupby("q", observed=True).agg(n=("sortie", "size"), taux=("sortie", "mean"), p_moy=("p", "mean")) \
        .round(4).reset_index().astype(float).to_dict("records")
    res["auc_protocole_inverse"] = round(roc_auc_score(tr.sortie, predire(logit(te), tr)), 3)
    rob = []
    for seuil in [0.05, 0.10, 0.25]:
        for lo, hi in [(100, 20000), (500, 20000), (100, 5000)]:
            a_, b_ = P.echantillon("201412", seuil, lo, hi), P.echantillon("201912", seuil, lo, hi)
            rob.append({"seuil": seuil, "univers": f"{lo}-{hi}", "n_test": len(b_),
                        "auc": round(roc_auc_score(b_.sortie, predire(logit(a_), b_)), 3)})
    res["robustesse"] = rob

    # --- application à la dernière date complète
    m2 = logit(pd.concat([tr, te]))
    now = P.indicateurs(P.t(a.date))
    now = now[(now.prod_bpj >= 100) & (now.prod_bpj <= 20000)].dropna(subset=FE)
    brut = now.copy()
    now = borner(now)
    now["proba_sortie_2ans"] = predire(m2, now)
    now["declin_12m"] = brut.declin_12m
    now = now.join(statique).join(noms)
    now["district"] = now.district_no.map(DMAP)
    now["zone_brut"] = now.district.map(grade_for_district)
    now["api"] = now.zone_brut.map(lambda g: GRADES[g][0] if g in GRADES else np.nan)
    now["soufre_pct"] = now.zone_brut.map(lambda g: GRADES[g][1] if g in GRADES else np.nan)
    hubs = now.district.map(lambda d: best_hub(d) if isinstance(d, str) else None)
    now["hub"] = [h[0] if h else None for h in hubs]
    now["cout_logistique"] = [round(h[2] - h[3], 2) if h else np.nan for h in hubs]
    # Rendement net (hypothèse : décote de 1 à 8 $/b selon le rang de risque)
    now["decote"] = 1 + now.proba_sortie_2ans.rank(pct=True) * 7
    now["ajust_qualite"] = [quality_adjustment(x, s) if pd.notna(x) else np.nan for x, s in zip(now.api, now.soufre_pct)]
    pd_an = 1 - (1 - now.proba_sortie_2ans) ** 0.5
    now["rendement_net_usd_b"] = (now.decote + now.ajust_qualite - now.cout_logistique
                                  - a.prix * 0.08 * 45 / 365 - pd_an * 0.6 * a.prix * 45 / 365)

    gros = now[now.prod_bpj >= 500]
    cibles = gros[(gros.mois_a_zero == 0) & (gros.proba_sortie_2ans >= 0.15)].sort_values("proba_sortie_2ans", ascending=False)
    res["application"] = {"date": a.date, "operateurs_100_20000": len(now), "operateurs_500_plus": len(gros),
                          "production_500_plus_bpj": round(float(gros.prod_bpj.sum())),
                          "proba_15_plus": int((gros.proba_sortie_2ans >= 0.15).sum()),
                          "cibles_actives": len(cibles), "production_cibles_bpj": round(float(cibles.prod_bpj.sum()))}
    json.dump(res, open(os.path.join(a.out, "backtest.json"), "w"), indent=1, default=float)

    cols = ["OPERATOR_NAME", "prod_bpj", "declin_12m", "accel_6m", "mois_a_zero", "part_puits_arret_pct",
            "proba_sortie_2ans", "zone_brut", "hub", "rendement_net_usd_b"]
    with pd.ExcelWriter(os.path.join(a.out, "operateurs.xlsx"), engine="openpyxl") as xw:
        cibles[cols].round(3).to_excel(xw, sheet_name="Cibles actives")
        gros.sort_values("proba_sortie_2ans", ascending=False)[cols].round(3).to_excel(xw, sheet_name="Tous 500+ bpj")
    print(json.dumps({k: v for k, v in res.items() if k not in ("roc", "robustesse")}, indent=1, default=float))


if __name__ == "__main__":
    main()
