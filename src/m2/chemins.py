"""Chemins du dépôt : données dans data/, résultats et figures dans resultats/m2/."""
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PARAMS = os.path.join(ROOT, "src", "schwartz_params.json")
DATA = os.path.join(ROOT, "data", "wti_daily.csv")
OUT = os.path.join(ROOT, "resultats", "m2")
os.makedirs(OUT, exist_ok=True)
os.chdir(OUT)
