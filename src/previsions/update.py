"""Mise à jour hebdomadaire des prévisions (lancée chaque lundi par GitHub Actions, ou à la main).

    python src/previsions/update.py            # depuis la racine du dépôt

Écrit :
  docs/data/previsions.json  prix récents, éventail de prévision, backtest, score des prévisions publiées
  docs/data/journal.csv      registre daté de toutes les prévisions publiées (on n'y modifie jamais une ligne)
  docs/data/sources.json     état de chaque source de données (utile si un site change de format)
"""
import json
import os
import sys
import traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from modele import forecast, backtest, naive_backtest  # noqa: E402
import sources  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "docs", "data")
os.makedirs(OUT, exist_ok=True)
JOURNAL = os.path.join(OUT, "journal.csv")
HORIZONS = {"j": {"1 semaine": 5, "1 mois": 21}, "s": {"1 semaine": 1, "1 mois": 4}}
STEP = {"j": 5, "s": 1}
HIST = {"j": 260, "s": 104}
now = datetime.now(timezone.utc)


def future_dates(last, n, freq):
    return [d.date().isoformat() for d in (pd.bdate_range(last, periods=n + 1)[1:] if freq == "j" else pd.date_range(last, periods=n + 1, freq="7D")[1:])]


def score_journal(journal, series):
    """Note les prévisions publiées dont la date cible est passée : le vrai prix est-il dans la fourchette ?"""
    rows = []
    for _, j in journal.iterrows():
        s = series.get(j["serie"])
        if s is None:
            continue
        after = s[s.index > pd.Timestamp(j["date_donnee"])]
        if len(after) < int(j["pas"]):
            continue
        real = float(after.iloc[int(j["pas"]) - 1])
        rows.append(dict(serie=j["serie"], horizon=j["horizon"], publie=j["publie"], bas=j["bas"], haut=j["haut"], reel=real,
                         dedans=bool(j["bas"] <= real <= j["haut"])))
    return rows


status, out, series = {}, {}, {}
for spec in sources.SERIES:
    sid = spec["id"]
    try:
        s, src = spec["f"]()
        if len(s) < 400 and spec["freq"] == "j" or len(s) < 150:
            raise ValueError(f"série trop courte ({len(s)} points)")
        series[sid] = s
        hz = HORIZONS[spec["freq"]]
        f = forecast(s, hz)
        H = max(hz.values())
        bt = {k: backtest(s, h, STEP[spec["freq"]], 156) for k, h in hz.items()}
        naive = {k: naive_backtest(s, h, STEP[spec["freq"]], 156) for k, h in hz.items()}
        for k in bt:
            ln = bt[k]["lignes"]
            bt[k]["largeur_moy"] = float(np.mean([(r["haut"] - r["bas"]) / r["prix"] for r in ln])) if ln else None
            bt[k]["lignes"] = ln[-52:]
        hist = s.iloc[-HIST[spec["freq"]]:]
        out[sid] = dict(
            id=sid, nom=spec["nom"], unite=spec["unite"], source=src, freq=spec["freq"],
            date=str(s.index[-1].date()), dernier=f["dernier"], vol_jour=f["vol_jour"],
            historique=dict(dates=[str(d.date()) for d in hist.index], prix=[round(float(v), 4) for v in hist.values]),
            eventail=dict(dates=future_dates(s.index[-1], H, spec["freq"]), quantiles=[5, 25, 50, 75, 95],
                          valeurs=[[round(v, 4) for v in row] for row in f["fan"]]),
            horizons=f["horizons"],
            backtest={k: dict(couverture=v["couverture"], n=v["n"], p_kupiec=v["p_kupiec"], largeur_moy=v["largeur_moy"],
                              naif=naive[k], lignes=v["lignes"]) for k, v in bt.items()},
        )
        status[sid] = dict(ok=True, source=src, points=len(s), debut=str(s.index[0].date()), fin=str(s.index[-1].date()))
    except Exception as e:  # une source qui tombe ne bloque pas les autres
        status[sid] = dict(ok=False, erreur=f"{type(e).__name__}: {e}"[:500], trace=traceback.format_exc()[-800:])
        if sid.endswith(("_fr", "_de")) and "apercu_ue" not in status:
            try:
                status["apercu_ue"] = sources.eu_preview()
            except Exception as e2:
                status["apercu_ue"] = f"{type(e2).__name__}: {e2}"

# ---------------------------------------------------------------- journal daté (ajout seulement)
journal = pd.read_csv(JOURNAL) if os.path.exists(JOURNAL) else pd.DataFrame(
    columns=["publie", "serie", "date_donnee", "horizon", "pas", "dernier", "bas", "median", "haut"])
new = []
for sid, o in out.items():
    already = ((journal["serie"] == sid) & (journal["date_donnee"] == o["date"])).any() if len(journal) else False
    if already:
        continue
    for k, h in o["horizons"].items():
        new.append(dict(publie=now.date().isoformat(), serie=sid, date_donnee=o["date"], horizon=k, pas=h["pas"],
                        dernier=round(o["dernier"], 4), bas=round(h["bas"], 4), median=round(h["median"], 4), haut=round(h["haut"], 4)))
if new:
    journal = pd.concat([journal, pd.DataFrame(new)], ignore_index=True)
    journal.to_csv(JOURNAL, index=False)

scored = score_journal(journal, series)
for sid in out:
    mine = [r for r in scored if r["serie"] == sid]
    out[sid]["publiees"] = dict(notees=len(mine), dedans=sum(r["dedans"] for r in mine), dernieres=mine[-6:])

json.dump(dict(mise_a_jour=now.isoformat(timespec="minutes"), series=list(out.values())),
          open(os.path.join(OUT, "previsions.json"), "w"), ensure_ascii=False)
json.dump(dict(mise_a_jour=now.isoformat(timespec="minutes"), sources=status),
          open(os.path.join(OUT, "sources.json"), "w"), ensure_ascii=False, indent=1, default=str)
ok = [k for k, v in status.items() if isinstance(v, dict) and v.get("ok")]
print(f"{len(ok)} séries à jour : {', '.join(ok)}")
print("échecs :", {k: v.get("erreur") for k, v in status.items() if isinstance(v, dict) and not v.get("ok")})
