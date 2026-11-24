"""Utilitaires d'entrées/sorties : écritures atomiques, hachage, JSONL.

Pourquoi des écritures atomiques ? Un script interrompu (Ctrl-C, coupure réseau)
ne doit jamais laisser un fichier à moitié écrit qui serait ensuite pris pour
un résultat valide : on écrit dans un fichier temporaire du même dossier puis on
le renomme (``os.replace`` est atomique sur un même système de fichiers).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


def utc_now() -> datetime:
    """Horodatage courant, explicitement en UTC (jamais d'heure « naïve »)."""
    return datetime.now(timezone.utc)


def to_iso(ts: datetime) -> str:
    """ISO 8601 en UTC, à la seconde, suffixe 'Z'."""
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compact_ts(ts: datetime) -> str:
    """Horodatage compact utilisable dans un nom de fichier : 20260101T120000Z."""
    return ts.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk_size), b""):
            h.update(block)
    return h.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> Path:
    """Écrit ``data`` dans ``path`` de manière atomique."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return path


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> Path:
    return atomic_write_bytes(path, text.encode(encoding))


def write_json(path: Path, obj: Any) -> Path:
    return atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_parquet(df: pd.DataFrame, path: Path) -> Path:
    """Sauvegarde Parquet atomique (le format conserve les types, contrairement au CSV)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    try:
        df.to_parquet(tmp, index=False)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return path


def append_jsonl(path: Path, record: dict) -> None:
    """Ajoute une ligne JSON à un journal. Une ligne = un événement, jamais réécrit."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    """Lit un journal JSONL ; ignore les lignes corrompues (ex. écriture interrompue)."""
    path = Path(path)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def should_skip(outputs: Iterable[Path], force: bool) -> bool:
    """Règle d'idempotence commune aux scripts : on saute l'étape si toutes ses
    sorties existent déjà, sauf si ``--force`` est demandé."""
    outputs = list(outputs)
    return (not force) and len(outputs) > 0 and all(Path(p).exists() for p in outputs)
