"""Collecte horaire **opt-in** des prix instantanés.

Pourquoi ? Le flux « instantané » ne donne que l'état courant : pour étudier la
dynamique des prix (réactions entre concurrents, cycles), il faut en
accumuler des captures successives. Ce module n'est **jamais** lancé
automatiquement : il faut l'activer explicitement (option ``--activer`` du
script ou variable ``CARBURANTS_COLLECT_ENABLED=1``) et le planifier soi-même
(cron, service planifié SSPCloud — voir README).

Garanties :

- **au plus une capture par intervalle** (55 min par défaut), vérifiée à partir
  du journal : relancer le script trop tôt n'interroge pas le serveur ;
- **déduplication** : si le fichier reçu est identique (même SHA-256) à la
  dernière capture stockée, rien n'est réécrit ;
- **verrou** : deux exécutions simultanées ne peuvent pas se chevaucher ;
- **journal JSONL** (``logs/collecte.jsonl``) : une ligne par tentative, avec
  horodatage UTC, statut, empreinte, taille, en-têtes HTTP, comptages, durée ;
- **sobriété** : par défaut on stocke une version Parquet compacte des prix
  (quelques Mo) ; le ZIP brut n'est gardé que sur demande (``keep_raw``) et
  jamais dans Git (``data/snapshots`` est ignoré par ``.gitignore``).
"""

from __future__ import annotations

import io
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from .config import COLLECT_ENV_FLAG, COLLECT_MIN_INTERVAL_MINUTES, FLUX_INSTANTANE_URL
from .flux import parse_flux_xml, read_xml_from_zip
from .io_utils import append_jsonl, compact_ts, read_jsonl, sha256_bytes, to_iso, utc_now

STORED, UNCHANGED, TOO_SOON, ERROR, LOCKED = "stocke", "inchange", "ignore_trop_tot", "erreur", "verrouille"

FetchFn = Callable[[], tuple[bytes, dict]]


def collection_enabled(cli_flag: bool, env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return bool(cli_flag) or env.get(COLLECT_ENV_FLAG) == "1"


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def last_record(records: list[dict], statuses: tuple[str, ...]) -> dict | None:
    for rec in reversed(records):
        if rec.get("statut") in statuses:
            return rec
    return None


class LockError(RuntimeError):
    pass


@contextmanager
def file_lock(lock_path: Path, stale_after_s: float = 2 * 3600):
    """Verrou par création exclusive de fichier ; un verrou plus vieux que
    ``stale_after_s`` (processus tué) est considéré comme abandonné."""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists() and time.time() - lock_path.stat().st_mtime > stale_after_s:
        lock_path.unlink(missing_ok=True)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise LockError(f"Collecte déjà en cours (verrou {lock_path})") from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def snapshot_tables(content: bytes, snapshot_time: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Version compacte d'une capture : prix bruts + attributs des stations,
    avec la colonne ``capture_utc`` (instant de la capture)."""
    tables = parse_flux_xml(read_xml_from_zip(content))
    ts = pd.Timestamp(snapshot_time).tz_convert("UTC")
    prices = tables.prices.copy()
    prices["capture_utc"] = ts
    stations = tables.stations.copy()
    stations["capture_utc"] = ts
    return prices, stations


def _to_parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def collect_once(storage, log_path: Path, fetch: FetchFn, now: datetime | None = None,
                 min_interval_minutes: float = COLLECT_MIN_INTERVAL_MINUTES,
                 keep_raw: bool = False, lock_path: Path | None = None) -> dict:
    """Effectue (au plus) une capture et renvoie l'enregistrement de journal."""
    now = now or utc_now()
    lock_path = lock_path or Path(log_path).with_suffix(".lock")
    base = {"horodatage_utc": to_iso(now), "source": FLUX_INSTANTANE_URL}
    try:
        with file_lock(lock_path):
            record = _collect_locked(storage, log_path, fetch, now, min_interval_minutes, keep_raw, base)
    except LockError as exc:
        record = {**base, "statut": LOCKED, "message": str(exc)}
    append_jsonl(log_path, record)
    return record


def _collect_locked(storage, log_path, fetch, now, min_interval_minutes, keep_raw, base) -> dict:
    records = read_jsonl(log_path)
    last_ok = last_record(records, (STORED, UNCHANGED))
    if last_ok is not None:
        elapsed = now - parse_iso(last_ok["horodatage_utc"])
        if elapsed < timedelta(minutes=min_interval_minutes):
            return {**base, "statut": TOO_SOON, "derniere_capture_utc": last_ok["horodatage_utc"],
                    "minutes_depuis": round(elapsed.total_seconds() / 60, 1)}

    t0 = time.monotonic()
    try:
        content, meta = fetch()
    except Exception as exc:  # erreur réseau, HTTP, contenu invalide : journalisée, non fatale
        return {**base, "statut": ERROR, "erreur": f"{type(exc).__name__}: {exc}"}

    digest = sha256_bytes(content)
    http_meta = {k: meta.get(k) for k in ("http_status", "last_modified", "etag")}
    last_stored = last_record(records, (STORED,))
    if last_stored is not None and last_stored.get("sha256") == digest:
        return {**base, "statut": UNCHANGED, "sha256": digest, "taille_octets": len(content), **http_meta}

    ts, day = compact_ts(now), now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    keys = {}
    try:
        prices, stations = snapshot_tables(content, now)
    except Exception as exc:
        return {**base, "statut": ERROR, "erreur": f"lecture XML : {type(exc).__name__}: {exc}",
                "sha256": digest}
    keys["prix"] = storage.write_bytes(f"prix/date={day}/prix_{ts}.parquet", _to_parquet_bytes(prices))
    keys["stations"] = storage.write_bytes(f"stations/date={day}/stations_{ts}.parquet",
                                           _to_parquet_bytes(stations))
    if keep_raw:
        keys["brut"] = storage.write_bytes(f"brut/date={day}/instantane_{ts}.zip", content)
    return {**base, "statut": STORED, "sha256": digest, "taille_octets": len(content), **http_meta,
            "n_pdv": int(len(stations)), "n_prix": int(len(prices)), "fichiers": keys,
            "duree_s": round(time.monotonic() - t0, 2)}
