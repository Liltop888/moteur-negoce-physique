# Données

| Fichier | Source | Inclus |
|---|---|---|
| `wti_monthly_fred.csv` | FRED, série MCOILWTICO (prix spot mensuel du WTI, EIA), 01/2010-09/2026 | oui |
| `producteurs_demo.csv` | Producteurs **fictifs** pour tester la chaîne de calcul | oui |
| `PDQ_DSV/` | Texas Railroad Commission, *Production Data Query Dump* (environ 35 Go décompressé) | non |

Pour le modèle du Texas, téléchargez le *Production Data Query Dump* (format CSV/DSV) depuis
la page « Data Sets Available for Download » de la Railroad Commission :
https://www.rrc.texas.gov/resource-center/research/data-sets-available-for-download/
puis décompressez-le dans `data/PDQ_DSV/`. Seules trois tables sont lues :
`OG_OPERATOR_CYCLE_DATA_TABLE.dsv`, `OG_REGULATORY_LEASE_DW_DATA_TABLE.dsv`, `OG_WELL_COMPLETION_DATA_TABLE.dsv`.
