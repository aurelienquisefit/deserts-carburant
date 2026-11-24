"""Enrichissement OpenStreetMap via l'API Overpass.

**Ce que l'on demande à OSM** : les objets étiquetés ``amenity=fuel`` en France
(nœuds, chemins et relations ; pour les deux derniers, ``out center`` fournit un
point central). Étiquettes exploitées (wiki OSM, « Tag:amenity=fuel ») :
``brand``, ``brand:wikidata``, ``name``, ``operator``, ``opening_hours``,
``self_service``, ``automated``, ``fuel:*``. Les supermarchés (``shop=supermarket``,
grandes surfaces) font l'objet d'une requête distincte (voir ``build_overpass_query``).

**Politique d'usage d'Overpass** respectée : *une* requête par type d'objet et par exécution,
dont le résultat est mis en cache (``data/raw/osm``) ; ``User-Agent`` explicite ;
``timeout`` déclaré dans la requête ; pas de parallélisme. Relancer le pipeline
réutilise le cache sauf ``--force``.

**Licence** : données © contributeurs OpenStreetMap, ODbL. Toute table dérivée
diffusée doit le mentionner (voir SOURCES.md).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .brands import classify_frame
from .config import OSM_MATCH_MAX_DISTANCE_M, OVERPASS_URL
from .geo import nearest_k
from .io_utils import atomic_write_text, to_iso, utc_now

OSM_TAGS = ["brand", "brand:wikidata", "name", "operator", "opening_hours",
            "self_service", "automated"]


def build_overpass_query(iso_code: str = "FR", timeout_s: int = 300,
                         cle: str = "amenity", valeur: str = "fuel") -> str:
    """Requête Overpass QL des objets ``cle=valeur`` d'un pays (code ISO 3166-1).

    Par défaut ``amenity=fuel`` (stations-service) ; ``shop=supermarket`` donne les
    supermarchés et hypermarchés, seul tag OSM qui couvre les deux.
    """
    return (
        f"[out:json][timeout:{int(timeout_s)}];\n"
        f'area["ISO3166-1"="{iso_code}"][admin_level=2]->.zone;\n'
        "(\n"
        f'  node["{cle}"="{valeur}"](area.zone);\n'
        f'  way["{cle}"="{valeur}"](area.zone);\n'
        f'  relation["{cle}"="{valeur}"](area.zone);\n'
        ");\n"
        "out center tags;\n"
    )


def fetch_overpass(session: requests.Session, cache_path: Path, query: str | None = None,
                   url: str = OVERPASS_URL, force: bool = False) -> dict:
    """Exécute la requête (une fois) et met la réponse JSON en cache."""
    cache_path = Path(cache_path)
    if cache_path.exists() and not force:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    query = query or build_overpass_query()
    requested_at = utc_now()
    resp = session.post(url, data={"data": query}, timeout=(10, 600))
    resp.raise_for_status()
    payload = resp.json()
    # On conserve la requête et l'horodatage avec la réponse (traçabilité).
    payload["_collecte"] = {"url": url, "requete": query, "horodatage_utc": to_iso(requested_at),
                            "osm_base": payload.get("osm3s", {}).get("timestamp_osm_base")}
    atomic_write_text(cache_path, json.dumps(payload, ensure_ascii=False))
    return payload


def parse_overpass_json(payload: dict) -> pd.DataFrame:
    """Convertit les ``elements`` Overpass en table (une ligne par objet OSM)."""
    rows = []
    for el in payload.get("elements", []):
        if el.get("type") == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center") or {}
            lat, lon = center.get("lat"), center.get("lon")
        tags = el.get("tags", {}) or {}
        row = {"osm_type": el.get("type"), "osm_id": el.get("id"), "osm_lat": lat, "osm_lon": lon}
        for t in OSM_TAGS:
            row[t] = tags.get(t)
        row["n_fuel_tags"] = sum(1 for k, v in tags.items() if k.startswith("fuel:") and v == "yes")
        rows.append(row)
    df = pd.DataFrame(rows, columns=["osm_type", "osm_id", "osm_lat", "osm_lon", *OSM_TAGS, "n_fuel_tags"])
    df = df.dropna(subset=["osm_lat", "osm_lon"])
    df["osm_key"] = df["osm_type"].astype(str) + "/" + df["osm_id"].astype(str)
    return classify_frame(df, columns=("brand", "name", "operator")).reset_index(drop=True)


def match_stations_to_osm(stations: pd.DataFrame, osm: pd.DataFrame,
                          max_distance_m: float = OSM_MATCH_MAX_DISTANCE_M) -> pd.DataFrame:
    """Apparie chaque station du flux à l'objet OSM ``amenity=fuel`` le plus proche.

    Règles :
    - appariement accepté si la distance est ≤ ``max_distance_m`` ;
    - ``match_ambigu`` : le 2ᵉ objet OSM le plus proche est lui aussi dans le
      seuil (deux stations voisines, p. ex. de part et d'autre d'une route) ;
    - ``osm_partage`` : un même objet OSM a été retenu pour plusieurs stations.

    Entrée : ``stations`` avec ``station_id``, ``lat``, ``lon`` (coordonnées valides).
    Sortie : une ligne par station, colonnes OSM vides si non appariée.
    """
    st = stations[["station_id", "lat", "lon"]].dropna().reset_index(drop=True)
    os_ = osm.reset_index(drop=True)
    dist, idx = nearest_k(st["lat"], st["lon"], os_["osm_lat"], os_["osm_lon"], k=2)
    best_d, best_i = dist[:, 0], idx[:, 0]
    matched = np.isfinite(best_d) & (best_d <= max_distance_m)

    out = pd.DataFrame({"station_id": st["station_id"],
                        "osm_distance_m": np.where(np.isfinite(best_d), best_d, np.nan),
                        "osm_apparie": matched,
                        "match_ambigu": matched & (dist[:, 1] <= max_distance_m)})
    cols = ["osm_key", "brand", "name", "operator", "enseigne", "famille_enseigne",
            "opening_hours", "self_service", "automated"]
    for c in cols:
        values = os_[c].to_numpy(dtype=object)[np.where(best_i >= 0, best_i, 0)] if len(os_) else None
        out[c] = np.where(matched, values, None) if values is not None else None
    out["enseigne"] = out["enseigne"].fillna("Inconnue")
    out["famille_enseigne"] = out["famille_enseigne"].fillna("inconnu")
    shared = out.loc[out["osm_apparie"], "osm_key"].value_counts()
    out["osm_partage"] = out["osm_key"].map(shared).fillna(0).astype(int) > 1
    return out
