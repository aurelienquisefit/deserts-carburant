"""Étape 1 — Télécharger (une fois) le flux instantané, puis le parser et le nettoyer.

Usage :
    python scripts/01_telecharger_flux.py                  # réutilise le cache s'il existe
    python scripts/01_telecharger_flux.py --force-download # nouveau téléchargement
    python scripts/01_telecharger_flux.py --force          # recalcule les tables depuis le cache
"""

import argparse
import json

from _commun import setup_logging

from carburants.pipeline import etape_flux

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--force-download", action="store_true", help="re-télécharger le flux")
    p.add_argument("--force", action="store_true", help="recalculer les tables même si elles existent")
    a = p.parse_args()
    log = setup_logging()
    res = etape_flux(force_download=a.force_download, force=a.force)
    log.info("Étape flux : %s", json.dumps(res, ensure_ascii=False))
