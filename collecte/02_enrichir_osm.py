"""Étape 2 — Enseignes OpenStreetMap (une requête Overpass, mise en cache).

Usage :
    python scripts/02_enrichir_osm.py                  # utilise le cache data/raw/osm s'il existe
    python scripts/02_enrichir_osm.py --force-download # nouvelle requête Overpass (à limiter !)
"""

import argparse
import json

from _commun import setup_logging

from carburants.pipeline import etape_osm

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--force-download", action="store_true")
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    log = setup_logging()
    log.info("Étape OSM : %s", json.dumps(etape_osm(force_download=a.force_download, force=a.force)))
