"""
Module Texas RRC : production de pétrole par opérateur.

Source : Texas Railroad Commission, "Production Data Query Dump" (PDQ), téléchargement gratuit
sur https://mft.rrc.texas.gov (rubrique Production Data). Le fichier zip contient des tables
séparées par le caractère "}" ; deux nous intéressent :
  - OG_LEASE_CYCLE_DATA_TABLE.dsv   : production mensuelle par lease (OPERATOR_NO, CYCLE_YEAR_MONTH,
                                      LEASE_OIL_PROD_VOL ...)
  - OG_OPERATOR_DW_DATA_TABLE.dsv   : noms des opérateurs (OPERATOR_NO, OPERATOR_NAME)

Le fichier lease est très gros (plusieurs Go) : il est lu par morceaux.

Ce module calcule, pour chaque opérateur :
  - production_bpj        : production moyenne de pétrole des 12 derniers mois (barils/jour)
  - declin_annuel_pct     : variation des 12 derniers mois vs les 12 mois précédents
  - nb_leases             : nombre de leases actifs (indicateur de taille / dispersion)
"""
import re
import pandas as pd

SEP = "}"
COL_OPERATOR = "OPERATOR_NO"
COL_MONTH = "CYCLE_YEAR_MONTH"
COL_OIL = "LEASE_OIL_PROD_VOL"
COL_LEASE = "LEASE_NO"
COL_NAME = "OPERATOR_NAME"
COL_DISTRICT = "DISTRICT_NO"


def load_operator_production(lease_file, operator_file, chunksize=2_000_000):
    header = pd.read_csv(lease_file, sep=SEP, nrows=0).columns
    has_district = COL_DISTRICT in header
    usecols = [COL_OPERATOR, COL_MONTH, COL_OIL, COL_LEASE] + ([COL_DISTRICT] if has_district else [])
    parts, dparts = [], []
    for chunk in pd.read_csv(lease_file, sep=SEP, usecols=usecols, dtype=str,
                             chunksize=chunksize, engine="c"):
        chunk[COL_OIL] = pd.to_numeric(chunk[COL_OIL], errors="coerce").fillna(0)
        parts.append(chunk.groupby([COL_OPERATOR, COL_MONTH])
                     .agg(oil=(COL_OIL, "sum"), leases=(COL_LEASE, "nunique")).reset_index())
        if has_district:
            dparts.append(chunk.groupby([COL_OPERATOR, COL_DISTRICT])[COL_OIL].sum().reset_index())
    monthly = (pd.concat(parts).groupby([COL_OPERATOR, COL_MONTH])
               .agg(oil=("oil", "sum"), leases=("leases", "sum")).reset_index())

    months = sorted(monthly[COL_MONTH].unique())
    if len(months) < 24:
        raise ValueError("Il faut au moins 24 mois de données pour calculer le déclin.")
    last12, prev12 = months[-12:], months[-24:-12]

    cur = monthly[monthly[COL_MONTH].isin(last12)].groupby(COL_OPERATOR) \
        .agg(oil_12m=("oil", "sum"), nb_leases=("leases", "max"))
    prv = monthly[monthly[COL_MONTH].isin(prev12)].groupby(COL_OPERATOR) \
        .agg(oil_prev_12m=("oil", "sum"))
    res = cur.join(prv, how="left").fillna({"oil_prev_12m": 0})
    res["production_bpj"] = (res["oil_12m"] / 365).round(0)
    res["declin_annuel_pct"] = ((res["oil_12m"] / res["oil_prev_12m"].where(res["oil_prev_12m"] > 0)
                                 - 1) * 100).round(1)

    names = pd.read_csv(operator_file, sep=SEP, usecols=[COL_OPERATOR, COL_NAME], dtype=str) \
        .drop_duplicates(COL_OPERATOR).set_index(COL_OPERATOR)
    res = res.join(names, how="left").reset_index()
    res["periode"] = f"{last12[0]}-{last12[-1]}"
    cols = [COL_OPERATOR, COL_NAME, "production_bpj", "declin_annuel_pct", "nb_leases", "periode"]

    if dparts:
        # District principal = celui où l'opérateur produit le plus -> qualité de brut de la zone
        from crude_quality import GRADES, grade_for_district
        d = pd.concat(dparts).groupby([COL_OPERATOR, COL_DISTRICT])[COL_OIL].sum().reset_index()
        main = d.sort_values(COL_OIL, ascending=False).drop_duplicates(COL_OPERATOR)
        main = main[[COL_OPERATOR, COL_DISTRICT]].rename(columns={COL_DISTRICT: "district_principal"})
        res = res.merge(main, on=COL_OPERATOR, how="left")
        res["zone_brut"] = res["district_principal"].map(grade_for_district)
        res["api"] = res["zone_brut"].map(lambda g: GRADES[g][0] if g in GRADES else None)
        res["soufre_pct"] = res["zone_brut"].map(lambda g: GRADES[g][1] if g in GRADES else None)
        cols += ["district_principal", "zone_brut", "api", "soufre_pct"]
    return res[cols]


def _norm(name):
    """Normalise un nom d'entreprise pour rapprocher RRC et SEC."""
    name = str(name).upper()
    name = re.sub(r"[^A-Z0-9 ]", " ", name)
    name = re.sub(r"\b(INC|LLC|LP|L P|CORP|CORPORATION|CO|COMPANY|LTD|OPERATING|OPERATIONS|"
                  r"ENERGY|RESOURCES|PETROLEUM|OIL|GAS|PRODUCTION|HOLDINGS|THE)\b", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def merge_with_producers(producers, rrc):
    """Ajoute production et déclin aux producteurs (SEC ou démo) par rapprochement de noms."""
    rrc = rrc.copy()
    rrc["_key"] = rrc[COL_NAME].map(_norm)
    rrc = rrc.sort_values("production_bpj", ascending=False).drop_duplicates("_key")
    out = producers.copy()
    out["_key"] = out["producteur"].map(_norm)
    extra = [c for c in ["production_bpj", "declin_annuel_pct", "nb_leases", "district_principal", "zone_brut",
              "api", "soufre_pct"]
             if c in rrc]
    out = out.merge(rrc[["_key"] + extra], on="_key", how="left", suffixes=("", "_rrc"))
    # Les données RRC remplacent les valeurs saisies à la main quand elles existent
    for c in ["production_bpj", "api", "soufre_pct"]:
        if f"{c}_rrc" in out:
            out[c] = out[f"{c}_rrc"].combine_first(out[c])
            out = out.drop(columns=[f"{c}_rrc"])
    return out.drop(columns=["_key"])
