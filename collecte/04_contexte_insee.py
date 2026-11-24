"""Étape 4 — Contexte communal via pynsee (population, superficie, densité, centroïde).

Affiche les colonnes réellement reçues : à comparer aux candidats de
``carburants.insee`` (le schéma ADMIN EXPRESS varie selon les millésimes).

Usage :
    python scripts/04_contexte_insee.py [--force]
"""

import argparse
import json

from _commun import setup_logging

from carburants.pipeline import etape_insee

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--force", action="store_true")
    a = p.parse_args()
    log = setup_logging()
    log.info("Étape INSEE : %s", json.dumps(etape_insee(force=a.force), ensure_ascii=False))
