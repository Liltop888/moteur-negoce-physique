# Préfinancement de producteurs pétroliers en difficulté

**Risque de défaut, prix du brut et allocation sous contrainte de risque**
Sidy Ali Haidara · M1 Économétrie et Statistique, Université Paris 1 Panthéon-Sorbonne · octobre 2026

📄 Rapport complet (9 pages) : [`rapport/rapport_moteur_negoce.pdf`](rapport/rapport_moteur_negoce.pdf)

## La question

Un négociant qui préfinance un petit producteur de pétrole obtient une décote sur le prix,
mais s'expose à son défaut, qui survient surtout quand le prix chute. Combien rapporte
réellement un baril une fois les coûts et les risques déduits, et combien en acheter à chaque producteur ?

## Méthode

| Étape | Modèle |
|---|---|
| Prix du pétrole | Schwartz (1997) à un facteur, Ornstein-Uhlenbeck sur le log-prix, calibré sur le WTI 2015-2026, simulation exacte |
| Défaut lié au prix | Modèle structurel de Merton, point de défaut KMV, simulation conjointe prix-défauts |
| Défaut observé | Logit de sortie estimé sur la production mensuelle des 12 163 opérateurs du Texas |
| Rendement par baril | Décote, qualité du brut (API, soufre), hub de revente optimal, financement, perte attendue |
| Allocation | Programme linéaire CVaR de Rockafellar-Uryasev, scénarios regroupés par motif de défaut |

## Résultats principaux

![Taux de sortie par quintile](figures/quintiles.png)

- **Validation hors échantillon** : entraîné sur la crise de 2015, testé sans réajustement sur la crise de 2020,
  le modèle atteint une **AUC de 0,71** (IC 95 % bootstrap : 0,65-0,78), contre 0,66 pour le déclin seul.
  Le quintile le plus risqué a connu **six fois plus de sorties** que le plus sûr (32,8 % contre 5,5 %).
- **Ce qui prédit la sortie** : l'irrégularité de la production et la chute récente, pas le déclin sur un an.
- **Couverture** : sans futures, le gain moyen par baril varie de +3,89 $ à −3,36 $ selon la vitesse de retour
  à la moyenne retenue dans son intervalle de confiance ; couvert, il reste à 2,64 $.
- **Wrong-way risk** : quand les défauts suivent le prix, la perte extrême d'un portefeuille diversifié augmente
  de 79 % et la probabilité de défauts en chaîne passe de 4 % à 23 %.

## Reproduire

```bash
pip install -r requirements.txt
cd src
python calibrate.py ../data/wti_monthly_fred.csv     # calibration du modèle de prix
python producer_scoring.py --demo                     # chaîne complète sur producteurs fictifs
python texas_backtest.py --pdq ../data/PDQ_DSV --date 202605 --out ../resultats   # données réelles (voir data/README.md)
```

Version Stata/Mata du moteur : `stata/moteur_negoce.do` (Stata 16 ou plus récent).

## Structure

```
src/        calibrate.py · stochastic.py · producer_scoring.py · ml_portfolio.py
            texas_backtest.py · crude_quality.py · logistics.py · rrc_production.py
stata/      moteur_negoce.do
data/       prix du WTI, producteurs de démonstration (le fichier du Texas est à télécharger)
figures/    graphiques du rapport
rapport/    rapport PDF
resultats/  backtest_reference.json (résultats agrégés, sans noms d'opérateurs)
```

## Limites

Une « sortie » peut être une faillite ou une cession de baux ; la relation détresse-décote et les primes de hub
sont des hypothèses ; la vitesse de retour à la moyenne du prix est mal identifiée. Détails et extensions
(faillites Chapter 11, modèle de Schwartz-Smith par filtre de Kalman, modèle de survie) dans le rapport.

Les résultats nominatifs par opérateur ne sont pas publiés : ce sont des prédictions statistiques, pas des constats.

Licence MIT.

## Partie 2 : les outils du M2 Probabilités et Finance

Quatre modules qui valorisent l'accord de préfinancement sur les prix journaliers du WTI (2010-2026) :

| Module | Méthode | Résultat clé |
|---|---|---|
| `sauts_extremes.py` | Merton à sauts, valeurs extrêmes (GPD), GARCH + EVT, tests de Kupiec et Christoffersen | Seul GARCH + EVT passe le backtest 2020-2026 (19 dépassements pour 16,9 attendus) |
| `plancher.py` | Put sous Schwartz (formule fermée), option sur moyenne par Monte Carlo + variable de contrôle | Plancher à 80 $ : 6,32 $/b ; variance divisée par 98 |
| `stockage.py` | Arrêt optimal : Longstaff-Schwartz contre programmation dynamique | À 50 $, attendre vaut 7,44 $ ; à 96 $, vendre tout de suite |
| `cva.py` | CVA avec intensité de défaut liée au prix (wrong-way risk) | 2,72 → 2,91 $/b |

```bash
cd src/m2
python run_all.py     # résultats et figures dans resultats/m2/
```
Page du site : https://liltop888.github.io/moteur-negoce-physique/modeles.html
