"""Lance toute la partie 2 dans l'ordre : python run_all.py (depuis src/m2)."""
import runpy, os
here = os.path.dirname(os.path.abspath(__file__))
for s in ["sauts_extremes", "plancher", "stockage", "cva", "deal", "fig_module1", "fig_module2", "fig_module3", "fig_module4", "fig_deal"]:
    print(f"\n=== {s} ===")
    runpy.run_path(os.path.join(here, s + ".py"), run_name="__main__")
