"""Configuration centrale : chemins, sources et seuils.

Tous les paramètres « de recherche » (rayons, seuils de fraîcheur, bornes de prix)
sont regroupés ici pour être cités dans le rapport et modifiés en un seul endroit.
Aucun secret n'est stocké ici : les identifiants S3 / INSEE sont lus dans
l'environnement (voir ``storage.py`` et ``insee.py``).
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
# src/carburants/config.py -> parents[2] = racine du projet
PROJECT_ROOT = Path(os.environ.get("CARBURANTS_ROOT", Path(__file__).resolve().parents[2]))

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
LOG_DIR = PROJECT_ROOT / "logs"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
FIGURES_DIR = OUTPUT_DIR / "figures"
TABLES_DIR = OUTPUT_DIR / "tables"
REPORT_DIR = PROJECT_ROOT / "rapport"

# Fichiers intermédiaires produits par les scripts (noms stables => idempotence)
FLUX_ZIP = RAW_DIR / "flux" / "prix_instantane.zip"
FLUX_META = RAW_DIR / "flux" / "prix_instantane.meta.json"
STATIONS_PARQUET = INTERIM_DIR / "stations.parquet"
PRICES_PARQUET = INTERIM_DIR / "prix.parquet"
RUPTURES_PARQUET = INTERIM_DIR / "ruptures.parquet"
OSM_JSON = RAW_DIR / "osm" / "overpass_fuel_fr.json"
OSM_PARQUET = INTERIM_DIR / "osm_fuel.parquet"
OSM_MATCH_PARQUET = INTERIM_DIR / "osm_match.parquet"
GS_JSON = RAW_DIR / "osm" / "overpass_grandes_surfaces_fr.json"
GS_PARQUET = INTERIM_DIR / "osm_grandes_surfaces.parquet"
# Magasins bio : tag shop=supermarket mais pas des grandes surfaces ; exclus de la distance
GS_EXCLUDED_PATTERN = r"biocoop|la vie claire|naturalia"
GEOCODE_PARQUET = INTERIM_DIR / "geocodage_ign.parquet"
COMMUNES_PARQUET = INTERIM_DIR / "communes.parquet"
INSEE_FILOSOFI_ZIP = RAW_DIR / "insee" / "filosofi_communes_2023.zip"
DATASET_PARQUET = PROCESSED_DIR / "stations_prix_contexte.parquet"
COMMUNE_DESERTS_PARQUET = PROCESSED_DIR / "communes_deserts.parquet"
QUALITY_JSON = PROCESSED_DIR / "journal_qualite.json"
METRICS_JSON = TABLES_DIR / "indicateurs.json"
COLLECT_LOG = LOG_DIR / "collecte.jsonl"

# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
# Flux officiel « prix des carburants » (ministère de l'Économie) :
# ZIP contenant un unique XML (encodage ISO-8859-1) avec tous les points de vente.
FLUX_INSTANTANE_URL = "https://donnees.roulez-eco.fr/opendata/instantane_ruptures"
# Archives : un fichier par jour ou par année (non utilisées par défaut, voir README).
FLUX_JOUR_URL = "https://donnees.roulez-eco.fr/opendata/jour/{yyyymmdd}"
FLUX_ANNEE_URL = "https://donnees.roulez-eco.fr/opendata/annee/{yyyy}"

# Overpass API (OpenStreetMap). Instance principale par défaut ; surchargeable.
OVERPASS_URL = os.environ.get("CARBURANTS_OVERPASS_URL", "https://overpass-api.de/api/interpreter")

# Géoplateforme IGN — service de géocodage (successeur de l'API Adresse).
IGN_GEOCODAGE_BASE = os.environ.get("CARBURANTS_IGN_GEOCODAGE_URL", "https://data.geopf.fr/geocodage")
IGN_REVERSE_CSV_URL = f"{IGN_GEOCODAGE_BASE}/reverse/csv"
IGN_SEARCH_CSV_URL = f"{IGN_GEOCODAGE_BASE}/search/csv"

# Identifiant poli envoyé à toutes les API (pas d'adresse e-mail codée en dur :
# définir CARBURANTS_USER_AGENT pour y ajouter un contact si une API l'exige).
USER_AGENT = os.environ.get(
    "CARBURANTS_USER_AGENT",
    "carburants-projet-pedagogique/0.1 (projet etudiant ENSAE; python-requests)",
)

# ---------------------------------------------------------------------------
# Nomenclature carburants du flux (attribut ``id`` des balises <prix>)
# ---------------------------------------------------------------------------
FUEL_IDS = {"1": "Gazole", "2": "SP95", "3": "E85", "4": "GPLc", "5": "E10", "6": "SP98"}
MAIN_FUELS = ("Gazole", "E10", "SP98", "SP95", "E85", "GPLc")

# ---------------------------------------------------------------------------
# Seuils de nettoyage
# ---------------------------------------------------------------------------
PRICE_MIN_EUR = 0.50   # €/L : en dessous, valeur jugée aberrante (erreur de saisie)
PRICE_MAX_EUR = 3.50   # €/L : au-dessus, idem
MAX_PRICE_AGE_DAYS = 7  # un prix non mis à jour depuis plus de 7 jours est « périmé »

# Emprise approximative de la France métropolitaine (Corse incluse), WGS84
METRO_BBOX = {"lat_min": 41.2, "lat_max": 51.3, "lon_min": -5.3, "lon_max": 9.7}

# ---------------------------------------------------------------------------
# Paramètres d'analyse
# ---------------------------------------------------------------------------
COMPETITION_RADII_KM = (1, 3, 5, 10)
ISOLATION_THRESHOLD_KM = 10.0           # station « isolée » : aucun concurrent à moins de 10 km
DESERT_THRESHOLDS_KM = (5.0, 10.0, 15.0)  # analyse de sensibilité des déserts
DEFAULT_DESERT_KM = 10.0
OSM_MATCH_MAX_DISTANCE_M = 150.0         # appariement station flux ↔ objet OSM

# Collecte horaire
COLLECT_MIN_INTERVAL_MINUTES = 55        # jamais plus d'une capture par heure
COLLECT_ENV_FLAG = "CARBURANTS_COLLECT_ENABLED"  # opt-in explicite


def ensure_dirs() -> None:
    """Crée l'arborescence locale de travail (opération idempotente)."""
    for d in (RAW_DIR / "flux", RAW_DIR / "osm", RAW_DIR / "insee", INTERIM_DIR, PROCESSED_DIR,
              SNAPSHOT_DIR, LOG_DIR, FIGURES_DIR, TABLES_DIR, REPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)
