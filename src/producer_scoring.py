"""
Moteur de classement des petits/moyens producteurs de pétrole en difficulté
et d'allocation optimale pour un négociant physique.

Modes :
  python producer_scoring.py --demo                      -> producteurs fictifs d'exemple
  python producer_scoring.py --sec CIK1 CIK2             -> vrais bilans SEC (sur ton ordinateur)
  + --rrc-lease ... --rrc-operator ...                   -> production Texas RRC (déclin, zone, hub)
  + --labels historique.csv                              -> modèle supervisé de défaut (colonnes FEATURES + defaut)

Chaîne de calcul :
  données -> score de détresse -> défaut de Merton lié au prix (simulation Schwartz conjointe)
  -> qualité + hub optimal -> rendement net / baril -> segmentation & anomalies
  -> allocation optimale sous contrainte CVaR et ligne de crédit -> mesure du wrong-way risk
"""
import argparse
import sys
import numpy as np
import pandas as pd

from crude_quality import quality_adjustment, reference_table
from logistics import best_hub
import stochastic as st
import ml_portfolio as ml

USER_AGENT = "Research prototype contact@example.com"  # la SEC exige un User-Agent avec un email

# --------------------------------------------------------------------------
# Paramètres (hypothèses à mettre à jour)
# --------------------------------------------------------------------------
BENCHMARK_USD = st.DERNIER_PRIX or 70.0  # dernier prix WTI observé (calibrate.py), sinon 70
TAUX_FINANCEMENT = 0.08   # coût annuel de ta ligne de crédit
JOURS_PORTAGE = 45        # durée entre paiement (avance) et revente
PERTE_EN_CAS_DEFAUT = 0.6
LIGNE_CREDIT_MUSD = 40.0  # capital mobilisable pour les avances
CVAR_MAX_MUSD = 4.0       # perte moyenne maximale acceptée dans les 5 % pires scénarios (1 an)

# --------------------------------------------------------------------------
# 1. Données
# --------------------------------------------------------------------------
SEC_TAGS = {
    "debt": ["LongTermDebt", "LongTermDebtNoncurrent", "DebtInstrumentCarryingAmount"],
    "debt_current": ["LongTermDebtCurrent", "DebtCurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "op_income": ["OperatingIncomeLoss"],
    "dda": ["DepreciationDepletionAndAmortization"],
}


def _latest(facts, tags):
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for t in tags:
        units = gaap.get(t, {}).get("units", {}).get("USD", [])
        annual = [u for u in units if u.get("form") == "10-K"]
        if annual:
            return sorted(annual, key=lambda u: u["end"])[-1]["val"]
    return None


def fetch_sec(ciks):
    import requests
    rows = []
    for cik in ciks:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json"
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        r.raise_for_status()
        f = r.json()
        op = _latest(f, SEC_TAGS["op_income"]) or 0
        dda = _latest(f, SEC_TAGS["dda"]) or 0
        rows.append({
            "producteur": f.get("entityName", cik), "pays": "USA",
            "dette_musd": (_latest(f, SEC_TAGS["debt"]) or 0) / 1e6,
            "dette_court_terme_musd": (_latest(f, SEC_TAGS["debt_current"]) or 0) / 1e6,
            "cash_musd": (_latest(f, SEC_TAGS["cash"]) or 0) / 1e6,
            "ebitda_musd": (op + dda) / 1e6,
            # À compléter (Texas RRC remplit production, qualité et hub automatiquement) :
            "production_bpj": np.nan, "volume_non_engage_pct": 0.5, "cout_production_usd_b": 40,
            "api": 38, "soufre_pct": 0.3, "distance_hub_km": 150,
            "going_concern": False, "risque_juridique": 1,
        })
    return pd.DataFrame(rows)


def demo_data():
    """Producteurs FICTIFS, uniquement pour tester la chaîne de calcul."""
    d = [
        # nom, pays, dette, dette CT, cash, ebitda, prod b/j, % non engagé, coût prod, API, soufre, km hub, going concern, risque jur
        ("Producteur A (Permian)",         "USA",     420, 180, 15, 60,  9000, 0.6, 45, 40, 0.2,  80, True,  1),
        ("Producteur B (Bakken)",          "USA",     150,  20, 40, 70,  6000, 0.3, 38, 41, 0.1, 400, False, 1),
        ("Producteur C (Alberta lourd)",   "Canada",  300, 120, 10, 45,  7000, 0.7, 40, 21, 3.5, 250, False, 1),
        ("Producteur D (Mer du Nord)",     "UK",      600, 350, 25, 80, 12000, 0.5, 50, 37, 0.4,  60, True,  2),
        ("Producteur E (Eagle Ford)",      "USA",      90,  10, 30, 55,  4000, 0.4, 35, 45, 0.1, 120, False, 1),
        ("Producteur F (onshore Afrique)", "Afrique", 250, 200,  5, 20,  5000, 0.8, 40, 33, 0.8, 300, True,  4),
        ("Producteur G (Oklahoma)",        "USA",     200,  60, 12, 35,  3500, 0.5, 42, 39, 0.3, 150, False, 1),
        ("Producteur H (Saskatchewan)",    "Canada",  110,  50,  8, 25,  3000, 0.6, 40, 30, 1.5, 200, False, 1),
    ]
    cols = ["producteur", "pays", "dette_musd", "dette_court_terme_musd", "cash_musd", "ebitda_musd",
            "production_bpj", "volume_non_engage_pct", "cout_production_usd_b", "api", "soufre_pct",
            "distance_hub_km", "going_concern", "risque_juridique"]
    return pd.DataFrame(d, columns=cols)


# --------------------------------------------------------------------------
# 2. Scoring
# --------------------------------------------------------------------------
def clip(x, lo, hi):
    return max(lo, min(hi, x))


def score(df):
    out = df.copy().reset_index(drop=True)

    out["dette_ebitda"] = out["dette_musd"] / out["ebitda_musd"].clip(lower=1)
    out["couverture_ct"] = out["cash_musd"] / out["dette_court_terme_musd"].clip(lower=1)

    # Score de détresse 0-100 : sert à estimer la décote négociable (besoin de cash du producteur)
    out["score_detresse"] = (
        out["dette_ebitda"].apply(lambda x: clip(x / 8, 0, 1)) * 45
        + out["couverture_ct"].apply(lambda x: clip(1 - x, 0, 1)) * 35
        + out["going_concern"].astype(int) * 20
    )
    if "declin_annuel_pct" in out:
        out["score_detresse"] += out["declin_annuel_pct"].fillna(0).apply(
            lambda d: clip(-d / 30, 0, 1)) * 15
    out["score_detresse"] = out["score_detresse"].clip(upper=100).round(1)

    # Probabilité de défaut : Merton lié au prix du pétrole (simulation Schwartz conjointe)
    ok = out["production_bpj"].notna() & out["cout_production_usd_b"].notna()
    out["proba_defaut"] = 0.01 + (out["score_detresse"] / 100) ** 2 * 0.35
    out["methode_defaut"] = "heuristique"
    out["distance_au_defaut"] = np.nan
    if ok.any():
        _, _, pd_merton = st.joint_default_simulation(out[ok], BENCHMARK_USD)
        out.loc[ok, "proba_defaut"] = pd_merton
        out.loc[ok, "methode_defaut"] = "Merton + Schwartz"
        out.loc[ok, "distance_au_defaut"] = [round(st.distance_to_default(r, BENCHMARK_USD), 2)
                                             for _, r in out[ok].iterrows()]
    out["proba_defaut"] = out["proba_defaut"].round(3)

    out["decote_negociee"] = (1.0 + out["score_detresse"] / 100 * 7.0).round(2)
    out["ajust_qualite"] = [quality_adjustment(a, s) for a, s in zip(out["api"], out["soufre_pct"])]

    # Logistique : hub optimal si la zone texane est connue, sinon distance saisie à la main
    districts = out["district_principal"] if "district_principal" in out else pd.Series([None] * len(out))
    hubs = [best_hub(d) if pd.notna(d) else None for d in districts]
    km_saisie = out["distance_hub_km"].tolist()
    out["hub_revente"] = [h[0] if h else "saisie manuelle" for h in hubs]
    out["distance_hub_km"] = [h[1] if h else km for h, km in zip(hubs, km_saisie)]
    out["cout_logistique"] = [round(h[2] - h[3], 2) if h else round(0.8 + km * 0.006, 2)
                              for h, km in zip(hubs, km_saisie)]

    out["cout_financement"] = round(BENCHMARK_USD * TAUX_FINANCEMENT * JOURS_PORTAGE / 365, 2)
    out["perte_attendue"] = (out["proba_defaut"] * PERTE_EN_CAS_DEFAUT * BENCHMARK_USD
                             * JOURS_PORTAGE / 365).round(2)
    out["prime_risque_juridique"] = ((out["risque_juridique"] - 1) * 1.0).round(2)

    out["rendement_net_usd_b"] = (
        out["decote_negociee"] + out["ajust_qualite"] - out["cout_logistique"]
        - out["cout_financement"] - out["perte_attendue"] - out["prime_risque_juridique"]
    ).round(2)
    out["volume_dispo_bpj"] = (out["production_bpj"] * out["volume_non_engage_pct"]).round(0)

    out["eligible"] = out["risque_juridique"] < 4
    out["decision"] = out.apply(
        lambda r: "EXCLU (conformité)" if not r["eligible"]
        else ("Cible prioritaire" if r["rendement_net_usd_b"] >= 3 and r["proba_defaut"] < 0.25
              else ("À surveiller" if r["rendement_net_usd_b"] > 0 else "Pas rentable")),
        axis=1,
    )
    return out


# --------------------------------------------------------------------------
# 3. Portefeuille, risque prix, wrong-way risk
# --------------------------------------------------------------------------
def portfolio_analysis(res):
    usable = res[res["production_bpj"].notna() & res["cout_production_usd_b"].notna()].reset_index(drop=True)
    _, defaults, _ = st.joint_default_simulation(usable, BENCHMARK_USD, n_scen=4000, seed=11)
    pnl = ml.scenario_pnl(usable, defaults, BENCHMARK_USD, JOURS_PORTAGE, PERTE_EN_CAS_DEFAUT)
    x, stats = ml.optimize_allocation(usable, pnl, BENCHMARK_USD, JOURS_PORTAGE,
                                      LIGNE_CREDIT_MUSD, CVAR_MAX_MUSD)
    alloc = pd.DataFrame({"producteur": usable["producteur"], "allocation_bpj": np.round(x, 0)})

    # Wrong-way risk : même allocation, mais défauts rendus indépendants (on mélange chaque colonne)
    rng = np.random.default_rng(3)
    indep = np.column_stack([rng.permutation(defaults[:, j]) for j in range(defaults.shape[1])])
    pnl_i = ml.scenario_pnl(usable, indep, BENCHMARK_USD, JOURS_PORTAGE, PERTE_EN_CAS_DEFAUT)
    # Portefeuille de référence diversifié : même volume chez chaque producteur éligible
    ref = np.where(usable["eligible"].to_numpy(),
                   np.minimum(2000, usable["volume_dispo_bpj"].fillna(0).to_numpy()), 0.0)
    lignes = []
    for nom, poids in [("Portefeuille optimal", x), ("Portefeuille diversifié de référence", ref)]:
        actifs = poids > 1
        for hyp, dmat, p in [("liés au prix (réaliste)", defaults, pnl), ("indépendants (naïf)", indep, pnl_i)]:
            port = (p / 1e6) @ poids
            lignes.append({
                "Portefeuille": nom, "Défauts": hyp,
                "Producteurs": int(actifs.sum()),
                "CVaR 95 % (MUSD)": round(st.var_cvar(port)[1], 2),
                # Événement extrême : au moins la moitié des producteurs font défaut la même année
                "Proba défaut de la moitié ou plus": round(float(
                    (dmat[:, actifs].sum(axis=1) >= max(1, int(np.ceil(actifs.sum() / 2)))).mean()), 3),
            })
    wwr = pd.DataFrame(lignes)

    # Risque prix d'une cargaison : couverte par futures ou non
    marge = float(res.loc[res["eligible"], "rendement_net_usd_b"].max())
    nc, cv = st.deal_pnl_distribution(BENCHMARK_USD, marge, JOURS_PORTAGE)
    risque_prix = pd.DataFrame({
        "Stratégie (par baril, meilleur deal)": ["Non couvert", "Couvert par futures"],
        "Gain moyen USD/b": [round(nc.mean(), 2), round(cv.mean(), 2)],
        "Proba de perte": [round((nc < 0).mean(), 3), round((cv < 0).mean(), 3)],
        "VaR 95 % USD/b": [round(st.var_cvar(nc)[0], 2), round(st.var_cvar(cv)[0], 2)],
        "CVaR 95 % USD/b": [round(st.var_cvar(nc)[1], 2), round(st.var_cvar(cv)[1], 2)],
    })
    return alloc, stats, wwr, risque_prix


# --------------------------------------------------------------------------
# 4. Programme principal
# --------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true")
    p.add_argument("--sec", nargs="*")
    p.add_argument("--rrc-lease", help="OG_LEASE_CYCLE_DATA_TABLE.dsv (Texas RRC)")
    p.add_argument("--rrc-operator", help="OG_OPERATOR_DW_DATA_TABLE.dsv (Texas RRC)")
    p.add_argument("--labels", help="CSV historique avec colonnes FEATURES + 'defaut' (0/1)")
    p.add_argument("--out", default="classement_producteurs.xlsx")
    a = p.parse_args()

    df = fetch_sec(a.sec) if a.sec else demo_data()

    rrc = None
    if a.rrc_lease and a.rrc_operator:
        from rrc_production import load_operator_production, merge_with_producers
        rrc = load_operator_production(a.rrc_lease, a.rrc_operator)
        df = merge_with_producers(df, rrc)

    res = score(df)
    res = ml.segment_and_flag(res)
    alloc, stats, wwr, risque_prix = portfolio_analysis(res)
    res = res.merge(alloc, on="producteur", how="left")
    res["allocation_bpj"] = res["allocation_bpj"].fillna(0)
    res = res.sort_values(["eligible", "rendement_net_usd_b"], ascending=[False, False])

    supervise = None
    if a.labels:
        hist = pd.read_csv(a.labels)
        model, auc, feats = ml.train_default_model(hist)
        res["proba_defaut_ml"] = model.predict_proba(res[feats].fillna(res[feats].median()))[:, 1].round(3)
        supervise = pd.DataFrame({"Indicateur": ["AUC validation croisée (5 plis)", "Variables"],
                                  "Valeur": [round(auc, 3), ", ".join(feats)]})

    cols = ["producteur", "pays", "decision", "allocation_bpj", "segment", "anomalie",
            "score_detresse", "proba_defaut", "methode_defaut", "distance_au_defaut",
            "decote_negociee", "ajust_qualite", "hub_revente", "distance_hub_km", "cout_logistique",
            "cout_financement", "perte_attendue", "prime_risque_juridique", "rendement_net_usd_b",
            "volume_dispo_bpj", "dette_ebitda", "couverture_ct", "api", "soufre_pct",
            "declin_annuel_pct", "zone_brut", "proba_defaut_ml"]
    cols = [c for c in cols if c in res]

    print(res[["producteur", "decision", "segment", "proba_defaut", "rendement_net_usd_b",
               "hub_revente", "allocation_bpj"]].to_string(index=False))
    print("\nPortefeuille optimal :", {k: round(v, 3) for k, v in stats.items()})
    print("\n" + wwr.to_string(index=False))
    print("\n" + risque_prix.to_string(index=False))

    with pd.ExcelWriter(a.out, engine="openpyxl") as w:
        res[cols].round(3).to_excel(w, sheet_name="Classement", index=False)
        pd.DataFrame({
            "Indicateur": ["Profit espéré sur 1 an (MUSD)", "VaR 95 % (MUSD)", "CVaR 95 % (MUSD)",
                           "Capital immobilisé (MUSD)", "Probabilité de perte sur l'année",
                           "Plafond CVaR (MUSD)", "Ligne de crédit (MUSD)"],
            "Valeur": [round(stats["profit_espere_musd"], 2), round(stats["var95_musd"], 2),
                       round(stats["cvar95_musd"], 2), round(stats["capital_utilise_musd"], 2),
                       round(stats["proba_perte"], 3), CVAR_MAX_MUSD, LIGNE_CREDIT_MUSD],
        }).to_excel(w, sheet_name="Portefeuille optimal", index=False)
        wwr.to_excel(w, sheet_name="Wrong-way risk", index=False)
        risque_prix.to_excel(w, sheet_name="Risque prix", index=False)
        if supervise is not None:
            supervise.to_excel(w, sheet_name="Modèle supervisé", index=False)
        if rrc is not None:
            prospects = rrc[(rrc["production_bpj"].between(500, 20000))
                            & (rrc["declin_annuel_pct"] <= -15)].sort_values("declin_annuel_pct")
            if "api" in prospects:
                prospects = prospects.assign(ajust_qualite_usd_b=[
                    quality_adjustment(x, y) if pd.notna(x) else None
                    for x, y in zip(prospects["api"], prospects["soufre_pct"])])
            if "district_principal" in prospects:
                h = prospects["district_principal"].map(best_hub)
                prospects = prospects.assign(
                    hub_optimal=[v[0] if v else None for v in h],
                    gain_net_hub_usd_b=[v[4] if v else None for v in h])
            prospects.to_excel(w, sheet_name="Prospects Texas", index=False)
        reference_table().to_excel(w, sheet_name="Qualités de brut", index=False)
        df.to_excel(w, sheet_name="Données brutes", index=False)
        pd.DataFrame({
            "Paramètre": ["Prix de référence USD/b", "Taux de financement", "Jours de portage",
                          "Perte en cas de défaut", "Volatilité prix (Schwartz)",
                          "Retour à la moyenne kappa", "Niveau de long terme USD/b",
                          "Volatilité propre producteur", "Calibration du modèle de prix", "Source des données"],
            "Valeur": [BENCHMARK_USD, TAUX_FINANCEMENT, JOURS_PORTAGE, PERTE_EN_CAS_DEFAUT,
                       st.SIGMA, st.KAPPA, st.NIVEAU_LT, st.VOL_IDIO, st.SOURCE_PARAMS,
                       ("SEC" if a.sec else "FICTIVES (démo)") + (" + Texas RRC" if rrc is not None else "")],
        }).to_excel(w, sheet_name="Hypothèses", index=False)
        for ws in w.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = max(
                    12, min(34, max(len(str(c.value or "")) for c in col) + 2))
            ws.freeze_panes = "A2"


if __name__ == "__main__":
    sys.exit(main())
