"""Stockage des captures : disque local (défaut) ou S3 (SSPCloud / MinIO).

Choix du stockage par variables d'environnement, **jamais** par des secrets
écrits dans le code :

==========================  ===============================================
``CARBURANTS_STORAGE``      ``local`` (défaut) ou ``s3``
``CARBURANTS_S3_BUCKET``    nom du bucket (sur le SSPCloud : votre identifiant)
``CARBURANTS_S3_PREFIX``    préfixe, p. ex. ``diffusion/carburants`` (défaut ``carburants``)
``AWS_ACCESS_KEY_ID``       \
``AWS_SECRET_ACCESS_KEY``    > injectées automatiquement dans les services SSPCloud
``AWS_SESSION_TOKEN``       /  (jetons temporaires) ; lues par s3fs/botocore
``AWS_S3_ENDPOINT``         ``minio.lab.sspcloud.fr`` sur le SSPCloud
==========================  ===============================================

Les deux classes exposent la même interface minimale (``write_bytes``,
``read_bytes``, ``exists``, ``list``, ``uri``), ce qui permet de tester la
collecte avec ``LocalStorage`` dans un dossier temporaire.
"""

from __future__ import annotations

import os
from pathlib import Path

from .io_utils import atomic_write_bytes


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError(f"Clé hors du dossier de stockage : {key}")
        return p

    def write_bytes(self, key: str, data: bytes) -> str:
        atomic_write_bytes(self._path(key), data)
        return self.uri(key)

    def read_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def list(self, prefix: str = "") -> list[str]:
        base = self.root
        if not base.exists():
            return []
        keys = [p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()]
        return sorted(k for k in keys if k.startswith(prefix) and not Path(k).name.startswith("."))

    def uri(self, key: str) -> str:
        return str(self.root / key)


class S3Storage:
    """Stockage S3 via ``s3fs`` (dépendance optionnelle : ``pip install s3fs``)."""

    def __init__(self, bucket: str, prefix: str = "carburants", fs=None):
        if fs is None:
            import s3fs  # import local : optionnel

            endpoint = os.environ.get("AWS_S3_ENDPOINT")
            client_kwargs = {}
            if endpoint:
                client_kwargs["endpoint_url"] = endpoint if endpoint.startswith("http") else f"https://{endpoint}"
            fs = s3fs.S3FileSystem(client_kwargs=client_kwargs)  # identifiants lus dans l'environnement
        self.fs = fs
        self.bucket = bucket.strip("/")
        self.prefix = prefix.strip("/")

    def _full(self, key: str) -> str:
        return "/".join(x for x in (self.bucket, self.prefix, key.lstrip("/")) if x)

    def write_bytes(self, key: str, data: bytes) -> str:
        with self.fs.open(self._full(key), "wb") as f:
            f.write(data)
        return self.uri(key)

    def read_bytes(self, key: str) -> bytes:
        with self.fs.open(self._full(key), "rb") as f:
            return f.read()

    def exists(self, key: str) -> bool:
        return bool(self.fs.exists(self._full(key)))

    def list(self, prefix: str = "") -> list[str]:
        root = self._full("")
        base = self._full(prefix)
        try:
            found = self.fs.find(base if self.fs.isdir(base) else root)
        except FileNotFoundError:
            return []
        keys = [f[len(root):].lstrip("/") for f in found]
        return sorted(k for k in keys if k.startswith(prefix))

    def uri(self, key: str) -> str:
        return f"s3://{self._full(key)}"


def storage_from_env(default_root: Path) -> LocalStorage | S3Storage:
    kind = os.environ.get("CARBURANTS_STORAGE", "local").lower()
    if kind == "s3":
        bucket = os.environ.get("CARBURANTS_S3_BUCKET")
        if not bucket:
            raise RuntimeError("CARBURANTS_STORAGE=s3 mais CARBURANTS_S3_BUCKET n'est pas défini.")
        return S3Storage(bucket, os.environ.get("CARBURANTS_S3_PREFIX", "carburants"))
    if kind != "local":
        raise ValueError(f"CARBURANTS_STORAGE inconnu : {kind!r} (attendu : local ou s3)")
    return LocalStorage(default_root)
