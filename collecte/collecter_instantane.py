"""Collecte horaire OPT-IN du flux instantané (une capture par exécution, au plus).

Ce script ne fait RIEN sans activation explicite :
    python scripts/collecter_instantane.py --activer
ou  CARBURANTS_COLLECT_ENABLED=1 python scripts/collecter_instantane.py

Planification (à mettre en place vous-même, jamais automatiquement) — exemple cron
toutes les heures à la minute 7, pour éviter les heures pleines :
    7 * * * * cd /chemin/du/projet && CARBURANTS_COLLECT_ENABLED=1 python scripts/collecter_instantane.py

Stockage : data/snapshots/ (ignoré par Git) ou S3 si CARBURANTS_STORAGE=s3
(voir README, section SSPCloud). Journal : logs/collecte.jsonl.

Options :
    --garder-brut        conserver aussi le ZIP brut (volumineux ; déconseillé en local)
    --intervalle-min N   intervalle minimal entre deux captures (défaut 55 min, minimum 30)
"""

import argparse
import json
import sys

from _commun import setup_logging

from carburants import config as C
from carburants.collect import collect_once, collection_enabled
from carburants.flux import fetch_flux_bytes
from carburants.http_client import make_session
from carburants.storage import storage_from_env

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--activer", action="store_true", help="active la collecte (opt-in)")
    p.add_argument("--garder-brut", action="store_true")
    p.add_argument("--intervalle-min", type=float, default=C.COLLECT_MIN_INTERVAL_MINUTES)
    a = p.parse_args()
    log = setup_logging("carburants.collecte")
    if not collection_enabled(a.activer):
        log.warning("Collecte désactivée (opt-in) : utiliser --activer ou %s=1. Aucune requête envoyée.",
                    C.COLLECT_ENV_FLAG)
        sys.exit(0)
    if a.intervalle_min < 30:
        log.error("Intervalle trop court (%s min) : minimum 30 min pour ménager le serveur.", a.intervalle_min)
        sys.exit(2)
    session = make_session()
    record = collect_once(storage_from_env(C.SNAPSHOT_DIR), C.COLLECT_LOG,
                          fetch=lambda: fetch_flux_bytes(session),
                          min_interval_minutes=a.intervalle_min, keep_raw=a.garder_brut)
    log.info("Collecte : %s", json.dumps(record, ensure_ascii=False))
    sys.exit(1 if record["statut"] == "erreur" else 0)
