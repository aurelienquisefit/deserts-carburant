"""Étape 3 — Géocodage inverse IGN (code commune INSEE de chaque station).

Les lots déjà traités sont relus depuis data/interim/geocodage_lots/ : relancer
après une interruption ne renvoie que les lots manquants.

Usage :
    python scripts/03_geocoder_ign.py [--force]
"""

import argparse
import json

from _commun import setup_logging

from carburants.pipeline import etape_geocodage

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    log = setup_logging()
    log.info("Étape géocodage : %s", json.dumps(etape_geocodage(force=a.force)))
