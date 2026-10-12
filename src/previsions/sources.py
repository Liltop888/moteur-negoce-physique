"""Téléchargement des prix publics. Chaque source renvoie une série pandas (index date, prix > 0)
ou lève une exception ; update.py consigne le résultat de chaque source dans docs/data/sources.json."""
import io
import re
import numpy as np
import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; comptoir-previsions/1.0; +https://github.com/Liltop888/moteur-negoce-physique)"}
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
    xml = get(OPEC_XML).decode("utf-8", "ignore")
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
        out[name] = df.iloc[:8, :12].astype(str).values.tolist()
    return out


def eu(country_code, product):
    """Prix à la pompe taxes comprises, en €/1000 L -> €/L. Cherche l'onglet « with taxes » puis la colonne
    dont l'en-tête contient le code pays et le produit (Euro-super 95 ou gasoil/diesel)."""
    book = eu_book()
    sheet = next((n for n in book if re.search(r"with\s*tax", n, re.I)), None)
    if sheet is None:
        raise ValueError("onglet 'with taxes' introuvable : " + ", ".join(book))
    df = book[sheet]
    prod_pat = r"super|95|petrol|essence" if product == "essence" else r"diesel|gas\s*oil|gasoil"
    # en-tête sur plusieurs lignes : on concatène les 6 premières lignes de chaque colonne
    head = [" ".join(str(x) for x in df.iloc[:6, j].tolist()) for j in range(df.shape[1])]
    # la colonne pays peut être fusionnée : on propage le dernier code pays vu vers la droite
    country, cols = None, []
    for j, h in enumerate(head):
        m = re.search(r"\b([A-Z]{2})\b", h)
        if m and m.group(1) not in ("EU", "NA"):
            country = m.group(1)
        if country == country_code and re.search(prod_pat, h, re.I):
            cols.append(j)
    if not cols:
        raise ValueError(f"colonne {country_code}/{product} introuvable")
    dates = pd.to_datetime(df.iloc[:, 0], errors="coerce", dayfirst=True)
    s = pd.Series(pd.to_numeric(df.iloc[:, cols[0]], errors="coerce").values, index=dates)
    s = clean(s)
    if s.median() > 100:                 # €/1000 L -> €/L
        s = s / 1000
    return s, "Commission européenne, Bulletin pétrolier"


SERIES = [
    dict(id="wti", nom="WTI (brut américain)", unite="$/baril", freq="j", f=wti),
    dict(id="brent", nom="Brent (brut de la mer du Nord)", unite="$/baril", freq="j", f=brent),
    dict(id="opep", nom="Panier OPEP", unite="$/baril", freq="j", f=opep),
    dict(id="essence_ny", nom="Essence, port de New York", unite="$/gallon", freq="j", f=essence_ny),
    dict(id="diesel_ny", nom="Diesel, port de New York", unite="$/gallon", freq="j", f=diesel_ny),
    dict(id="sp95_fr", nom="SP95 à la pompe, France", unite="€/litre", freq="s", f=lambda: eu("FR", "essence")),
    dict(id="gazole_fr", nom="Gazole à la pompe, France", unite="€/litre", freq="s", f=lambda: eu("FR", "diesel")),
    dict(id="sp95_de", nom="Super 95 à la pompe, Allemagne", unite="€/litre", freq="s", f=lambda: eu("DE", "essence")),
    dict(id="gazole_de", nom="Diesel à la pompe, Allemagne", unite="€/litre", freq="s", f=lambda: eu("DE", "diesel")),
]
