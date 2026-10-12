"""
Qualité du brut par zone de production et ajustement de prix associé.

Qualités de référence (densité API, soufre % poids) :
  - WTI Midland     : API 40-44, soufre max 0,2 %   (spécification Platts)
  - Bakken          : API ~42,  soufre ~0,15 %      (spécification BKN, témoignage Auers au Congrès US)
  - Eagle Ford      : API ~47,7, soufre ~0,1 %      (même source ; Eagle Ford Light ~58,8 API)
  - WCS (Alberta)   : API 20,5-21,5, soufre 3,0-3,5 % (spécifications de blending WCS)
  - Brent, Mars, Est Texas, Panhandle, côte du Golfe : valeurs usuelles, marquées "estimation"

Les valeurs sont des moyennes de zone : un lease donné peut s'en écarter. Dès que tu as
l'analyse (assay) réelle d'un producteur, saisis-la à la place.
"""
import pandas as pd

GRADES = {
    #  grade                    API    soufre  source
    "WTI Midland":            (42.0,  0.20,   "vérifié (Platts)"),
    "Eagle Ford":             (47.7,  0.10,   "vérifié (Auers)"),
    "Bakken":                 (42.0,  0.15,   "vérifié (Auers)"),
    "WCS (Alberta lourd)":    (21.0,  3.50,   "vérifié (spéc. WCS)"),
    "Brent / Mer du Nord":    (38.0,  0.40,   "estimation"),
    "Mars (golfe du Mexique)": (29.0, 2.00,   "estimation"),
    "Côte du Golfe Texas":    (37.0,  0.30,   "estimation"),
    "Est Texas":              (39.0,  0.30,   "estimation"),
    "Panhandle / Nord Texas": (39.0,  0.40,   "estimation"),
}

# Districts de la Texas Railroad Commission -> zone de production principale (approximation)
TEXAS_DISTRICT_TO_GRADE = {
    "01": "Eagle Ford", "02": "Eagle Ford", "04": "Eagle Ford",
    "03": "Côte du Golfe Texas",
    "05": "Est Texas", "06": "Est Texas", "6E": "Est Texas",
    "7B": "Panhandle / Nord Texas", "09": "Panhandle / Nord Texas", "10": "Panhandle / Nord Texas",
    "7C": "WTI Midland", "08": "WTI Midland", "8A": "WTI Midland",
}


def grade_for_district(district):
    d = str(district).strip().upper()
    if d.isdigit():
        d = d.zfill(2)
    return TEXAS_DISTRICT_TO_GRADE.get(d)


def quality_adjustment(api, soufre):
    """
    Ajustement de prix (USD/baril) par rapport à un brut de référence léger et peu soufré.
    - Trop lourd (API < 35) : moins de produits légers à la raffinerie -> décote
    - Trop léger (API > 45, type condensat) : moins de diesel, raffineries moins intéressées -> petite décote
    - Soufre : coût de désulfuration -> décote proportionnelle
    Coefficients indicatifs, à calibrer sur les écarts de prix observés (ex. WCS vs WTI).
    """
    adj = 0.0
    if api < 35:
        adj -= (35 - api) * 0.15
    elif api > 45:
        adj -= (api - 45) * 0.10
    adj -= soufre * 0.6
    return round(adj, 2)


def reference_table():
    rows = [{"grade": g, "api": a, "soufre_pct": s, "source": src,
             "ajust_qualite_usd_b": quality_adjustment(a, s)} for g, (a, s, src) in GRADES.items()]
    return pd.DataFrame(rows)
