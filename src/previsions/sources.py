"""Téléchargement des prix publics. Chaque source renvoie une série pandas (index date, prix > 0)
ou lève une exception ; update.py consigne le résultat de chaque source dans docs/data/sources.json."""
import io
import re
import numpy as np
import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; comptoir-previsions/1.0; +https://github.com/SidyHaidara/moteur-negoce-physique)"}
EIA_XLS = "https://www.eia.gov/dnav/pet/xls/PET_PRI_SPT_S1_D.xls"
EU_XLSX = ("https://energy.ec.europa.eu/document/download/906e60ca-8b6a-44e7-8589-652854d2fd3f_en"
           "?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx")
OPEC_XML = "https://www.opec.org/basket/basketDayArchives.xml"
GH = "https://raw.githubusercontent.com/datasets/oil-prices/main/data/{}-daily.csv"


def get(url, timeout=90):
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.content


def clean(s):
    s = pd.to_numeric(s, errors="coerce")
    s.index = pd.to_datetime(s.index, errors="coerce")
    s = s[s.index.notna()].dropna()
    s = s[s > 0].sort_index()
    return s[~s.index.duplicated(keep="last")]


# ---------------------------------------------------------------- EIA (États-Unis) : tableau complet des prix spot
_eia_cache = {}


def eia_sheets():
    if "x" not in _eia_cache:
        _eia_cache["x"] = pd.read_excel(io.BytesIO(get(EIA_XLS)), sheet_name=None, header=2)
    return _eia_cache["x"]


def eia(pattern):
    for name, df in eia_sheets().items():
        if not name.lower().startswith("data"):
            continue
        for col in df.columns[1:]:
            if re.search(pattern, str(col), re.I):
                s = df.set_index(df.columns[0])[col]
                return clean(s)
    raise ValueError(f"colonne introuvable : {pattern}")


def github_dataset(name):
    df = pd.read_csv(io.BytesIO(get(GH.format(name))))
    return clean(df.set_index("Date")["Price"])


def wti():
    try:
        return eia(r"Cushing.*WTI|WTI.*Cushing"), "EIA"
    except Exception:
        return github_dataset("wti"), "EIA (miroir datasets/oil-prices)"


def brent():
    try:
        return eia(r"Brent"), "EIA"
    except Exception:
        return github_dataset("brent"), "EIA (miroir datasets/oil-prices)"


def essence_ny():
    return eia(r"New York Harbor Conventional Gasoline"), "EIA"


def diesel_ny():
    return eia(r"New York Harbor Ultra-Low Sulfur No 2 Diesel"), "EIA"


# ---------------------------------------------------------------- OPEP : panier de référence
def opep():
    r = requests.get(OPEC_XML, timeout=90, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8", "Referer": "https://www.opec.org/"})
    r.raise_for_status()
    xml = r.content.decode("utf-8", "ignore")
    pairs = re.findall(r'data="(\d{4}-\d{2}-\d{2})"\s+val="([\d.]+)"', xml)
    if not pairs:
        raise ValueError("format XML inattendu : " + xml[:300])
    d, v = zip(*pairs)
    return clean(pd.Series(np.array(v, float), index=list(d))), "OPEP"


# ---------------------------------------------------------------- Union européenne : Bulletin pétrolier hebdomadaire
_eu_cache = {}


def eu_book():
    if "x" not in _eu_cache:
        _eu_cache["x"] = pd.read_excel(io.BytesIO(get(EU_XLSX)), sheet_name=None, header=None)
    return _eu_cache["x"]


def eu_preview():
    out = {}
    for name, df in eu_book().items():
        codes = df.iloc[:, 1].astype(str).str.strip().value_counts().head(40).to_dict() if df.shape[1] > 1 else {}
        out[name] = dict(lignes=int(df.shape[0]), codes_pays=codes, debut=df.iloc[:8, :12].astype(str).values.tolist())
    return out


def eu(country_code, product):
    """Prix à la pompe taxes comprises (onglet « Prices with taxes ») : une ligne par pays et par semaine,
    colonne 0 = date, colonne 1 = code pays (« FR_ »), colonne 2 = Euro-super 95, colonne 3 = gazole, en €/1000 L."""
    book = eu_book()
    sheet = next((n for n in book if re.search(r"with\s*tax", n, re.I)), None)
    if sheet is None:
        raise ValueError("onglet 'with taxes' introuvable : " + ", ".join(book))
    df = book[sheet]
    head = " ".join(str(x) for x in df.iloc[:3, :].values.ravel())
    col = 2 if product == "essence" else 3
    if product == "essence" and not re.search(r"super\s*95|euro95", head, re.I):
        raise ValueError("colonne Euro-super 95 introuvable")
    ctr = df.iloc[:, 1].astype(str).str.strip().str.upper()
    rows = df[ctr.str.startswith(country_code + "_") | (ctr == country_code)]
    if rows.empty:
        raise ValueError(f"aucune ligne pour le pays {country_code}")
    dates = pd.to_datetime(rows.iloc[:, 0], errors="coerce")
    s = clean(pd.Series(pd.to_numeric(rows.iloc[:, col], errors="coerce").values, index=dates))
    if s.median() > 100:                 # €/1000 L -> €/L
        s = s / 1000
    return s, "Commission européenne, Bulletin pétrolier"


SERIES = [
    dict(id="wti", nom="WTI (brut américain)", unite="$/baril", freq="j", f=wti),
    dict(id="brent", nom="Brent (brut de la mer du Nord)", unite="$/baril", freq="j", f=brent),
    dict(id="essence_ny", nom="Essence, port de New York", unite="$/gallon", freq="j", f=essence_ny),
    dict(id="diesel_ny", nom="Diesel, port de New York", unite="$/gallon", freq="j", f=diesel_ny),
    dict(id="sp95_ue", nom="Essence (Euro-super 95) à la pompe, moyenne UE", unite="€/litre", freq="s", f=lambda: eu("EU", "essence")),
    dict(id="gazole_ue", nom="Gazole à la pompe, moyenne UE", unite="€/litre", freq="s", f=lambda: eu("EU", "diesel")),
]
