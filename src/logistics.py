"""
Logistique : distance de chaque producteur aux hubs de revente et choix du hub optimal.

Le hub le plus proche n'est pas toujours le meilleur : un hub côtier (Houston, Corpus Christi)
paie souvent plus cher le baril qu'un hub intérieur (Midland), car il donne accès à l'export.
On choisit donc le hub qui maximise : prime du hub - coût de transport.

Toutes les valeurs ci-dessous sont des HYPOTHÈSES à recalibrer :
  - coordonnées des districts RRC = centre approximatif de chaque région
  - primes de hub = ordres de grandeur, elles varient chaque jour (à brancher sur des cotations réelles)
  - coût transport = mélange camion / collecte ; un raccordement pipeline coûte nettement moins cher
"""
from math import radians, sin, cos, asin, sqrt

HUBS = {
    #  hub              lat      lon      prime vs Midland (USD/b)
    "Midland":        (31.997, -102.078, 0.00),
    "Cushing":        (35.985,  -96.767, 0.60),
    "Houston":        (29.760,  -95.370, 1.00),
    "Corpus Christi": (27.800,  -97.396, 0.80),
}

DISTRICT_COORDS = {  # centre approximatif des districts de la Texas Railroad Commission
    "01": (28.9, -98.9), "02": (28.8, -97.0), "03": (29.8, -95.6), "04": (27.5, -98.3),
    "05": (32.0, -96.5), "06": (32.3, -94.8), "6E": (32.4, -94.9), "7B": (32.5, -99.7),
    "7C": (31.3, -100.9), "08": (31.6, -103.0), "8A": (33.4, -102.3), "09": (33.6, -98.2),
    "10": (35.6, -101.0),
}

COUT_FIXE_USD_B = 0.80        # chargement, stockage tampon, inspection
COUT_KM_USD_B = 0.008         # transport par km et par baril
FACTEUR_DETOUR = 1.25         # la route n'est pas une ligne droite


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def transport_cost(km):
    return COUT_FIXE_USD_B + COUT_KM_USD_B * km * FACTEUR_DETOUR


def best_hub(district):
    """Renvoie (hub, distance_km, cout_transport, prime_hub, gain_net) ou None si district inconnu."""
    d = str(district).strip().upper()
    if d.isdigit():
        d = d.zfill(2)
    if d not in DISTRICT_COORDS:
        return None
    lat, lon = DISTRICT_COORDS[d]
    options = []
    for hub, (hlat, hlon, prime) in HUBS.items():
        km = haversine_km(lat, lon, hlat, hlon)
        cout = transport_cost(km)
        options.append((hub, round(km), round(cout, 2), prime, round(prime - cout, 2)))
    return max(options, key=lambda o: o[4])
