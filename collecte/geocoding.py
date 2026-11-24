"""Géocodage IGN (Géoplateforme, service « géocodage »).

Usage dans le projet : le flux ne fournit qu'un code **postal** ; or le contexte
INSEE est indexé par code **commune** (COG). On obtient ce dernier par
*géocodage inverse* des coordonnées de chaque station (``result_citycode``).
Le géocodage direct d'adresse est prévu en secours, mais le pipeline ne l'appelle
pas encore : sur la capture du 22/11/2026, 332 stations ont des coordonnées valides
sans code commune après le géocodage inverse.

Interface utilisée : les points d'accès par lot ``/reverse/csv`` et
``/search/csv`` (même convention que l'ancienne API Adresse) :

- entrée : un CSV envoyé en ``multipart/form-data`` dans le champ ``data`` ;
- inverse : colonnes ``lat`` et ``lon`` ;
- direct : paramètres ``columns`` (colonnes à concaténer) et ``postcode`` ;
- sortie : le CSV d'entrée + colonnes ``result_*`` (``result_citycode``,
  ``result_label``, ``result_score``, ``result_distance``...).

Politique d'usage : le service est limité en débit par IP ; on envoie des lots
séquentiels (5 000 lignes), espacés d'au moins une seconde, et chaque lot est mis
en cache sur disque sous un nom dérivé de son contenu : une reprise après
interruption ne renvoie que les lots manquants (idempotence).

Validé sur la capture du 22/11/2026 (voir ``docs/validation.md``) : 9 493 codes
commune sur 9 825 stations.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import requests

from .config import IGN_REVERSE_CSV_URL, IGN_SEARCH_CSV_URL
from .http_client import RateLimiter
from .io_utils import atomic_write_bytes, sha256_bytes

RESULT_COLUMNS = ["result_citycode", "result_city", "result_postcode", "result_label",
                  "result_score", "result_distance", "result_type"]


def _post_csv(session: requests.Session, url: str, csv_bytes: bytes, form: list[tuple[str, str]]) -> bytes:
    files = {"data": ("lot.csv", csv_bytes, "text/csv")}
    resp = session.post(url, files=files, data=form, timeout=(10, 600))
    resp.raise_for_status()
    return resp.content


def _batched_csv_service(session: requests.Session, df: pd.DataFrame, url: str,
                         form: list[tuple[str, str]], cache_dir: Path, batch_size: int,
                         min_interval_s: float) -> pd.DataFrame:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    limiter = RateLimiter(min_interval_s)
    parts = []
    for start in range(0, len(df), batch_size):
        chunk = df.iloc[start:start + batch_size]
        csv_bytes = chunk.to_csv(index=False).encode("utf-8")
        cache_file = cache_dir / f"lot_{sha256_bytes(csv_bytes + url.encode())[:16]}.csv"
        if cache_file.exists():
            content = cache_file.read_bytes()
        else:
            limiter.wait()
            content = _post_csv(session, url, csv_bytes, form)
            atomic_write_bytes(cache_file, content)
        parts.append(pd.read_csv(io.BytesIO(content), dtype=str))
    if not parts:
        return pd.DataFrame(columns=[*df.columns, *RESULT_COLUMNS])
    return pd.concat(parts, ignore_index=True)


def reverse_geocode(session: requests.Session, stations: pd.DataFrame, cache_dir: Path,
                    batch_size: int = 5000, min_interval_s: float = 1.0,
                    url: str = IGN_REVERSE_CSV_URL) -> pd.DataFrame:
    """Géocodage inverse : (station_id, lat, lon) -> code commune INSEE."""
    payload = stations[["station_id", "lat", "lon"]].dropna().copy()
    result = _batched_csv_service(session, payload, url, [("lat", "lat"), ("lon", "lon")],
                                  cache_dir, batch_size, min_interval_s)
    return tidy_geocoding_result(result, prefix="inv")


def geocode_addresses(session: requests.Session, stations: pd.DataFrame, cache_dir: Path,
                      batch_size: int = 5000, min_interval_s: float = 1.0,
                      url: str = IGN_SEARCH_CSV_URL) -> pd.DataFrame:
    """Géocodage direct (adresse + ville, filtré par code postal)."""
    payload = stations[["station_id", "adresse", "ville", "cp"]].copy()
    form = [("columns", "adresse"), ("columns", "ville"), ("postcode", "cp")]
    result = _batched_csv_service(session, payload, url, form, cache_dir, batch_size, min_interval_s)
    return tidy_geocoding_result(result, prefix="dir")


def tidy_geocoding_result(result: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Sélectionne et type les colonnes utiles ; renomme avec un préfixe
    (``inv_`` pour inverse, ``dir_`` pour direct) afin de pouvoir comparer les deux."""
    out = pd.DataFrame({"station_id": result["station_id"].astype(str)})
    for col in RESULT_COLUMNS:
        out[f"{prefix}_{col.removeprefix('result_')}"] = result[col] if col in result.columns else None
    for num in ("score", "distance"):
        name = f"{prefix}_{num}"
        out[name] = pd.to_numeric(out[name], errors="coerce")
    code = f"{prefix}_citycode"
    out[code] = out[code].astype("string").str.strip().str.zfill(5).replace({"00000": pd.NA})
    if "latitude" in result.columns and "longitude" in result.columns:  # position du résultat
        out[f"{prefix}_lat"] = pd.to_numeric(result["latitude"], errors="coerce")
        out[f"{prefix}_lon"] = pd.to_numeric(result["longitude"], errors="coerce")
    return out.drop_duplicates(subset="station_id")
