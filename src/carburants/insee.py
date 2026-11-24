"""Contexte communal : population, superficie, densité et niveau de vie.

Sources mobilisées par ``pynsee`` :

- ``pynsee.geodata.get_geodata`` : couches IGN *ADMIN EXPRESS COG CARTO*
  (polygones des communes) servies par la Géoplateforme. La version vérifiée
  contient le code commune, la population municipale 2023 et la superficie ;
- le catalogue public ``pynsee.melodi`` : fichier communal Filosofi 2023,
  médiane du niveau de vie en euros.

Les valeurs confidentielles du revenu restent manquantes. Le jeu Filosofi est
un téléchargement public consulté dans le catalogue pynsee ; aucun jeton API
n'est requis.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import requests

from .http_client import DEFAULT_TIMEOUT
from .io_utils import atomic_write_bytes

COMMUNE_LAYER = "ADMINEXPRESS-COG-CARTO.LATEST:commune"
CODE_CANDIDATES = ("code_insee", "insee_com", "INSEE_COM", "codgeo", "CODGEO")
NAME_CANDIDATES = ("nom_officiel", "nom", "nom_com", "NOM", "NOM_COM", "libgeo")
POP_CANDIDATES = ("population", "POPULATION", "pmun", "PMUN")
DEP_CANDIDATES = ("code_insee_du_departement", "insee_dep", "INSEE_DEP", "dep")

# Classes de densité *simplifiées* (hab./km²). Ce n'est PAS la grille communale
# de densité officielle de l'INSEE (fondée sur des carreaux de 1 km²) ; ces
# seuils servent seulement à stratifier les statistiques descriptives.
DENSITY_BINS = [0, 25, 100, 500, 2000, np.inf]
DENSITY_LABELS = ["< 25", "25–100", "100–500", "500–2000", "2000 et plus"]


def pick_column(df: pd.DataFrame, candidates: Sequence[str], what: str, required: bool = True) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    if required:
        raise KeyError(f"Colonne « {what} » introuvable ; colonnes disponibles : {list(df.columns)}")
    return None


def density_class(density: pd.Series) -> pd.Series:
    return pd.cut(density, bins=DENSITY_BINS, labels=DENSITY_LABELS, right=False)


def fetch_communes_geodata(layer: str = COMMUNE_LAYER, update: bool = False):
    """Télécharge les polygones communaux via pynsee (WGS84 demandé)."""
    from pynsee.geodata import get_geodata  # import local : dépendance lourde

    try:
        gdf = get_geodata(layer, update=update, crs="EPSG:4326")
    except TypeError:  # anciennes versions sans argument ``crs``
        gdf = get_geodata(layer)
    return gdf


def communes_table(gdf) -> pd.DataFrame:
    """Polygones communaux -> table attributaire (code, nom, pop, superficie,
    densité, centroïde WGS84). Superficie et centroïde calculés en Lambert-93
    (EPSG:2154, projection métrique officielle pour la métropole)."""
    import geopandas as gpd

    gdf = gpd.GeoDataFrame(gdf).copy()
    if gdf.crs is None:
        raise ValueError("Couche sans système de coordonnées : impossible de calculer les surfaces.")
    code = pick_column(gdf, CODE_CANDIDATES, "code commune")
    name = pick_column(gdf, NAME_CANDIDATES, "nom de commune", required=False)
    pop = pick_column(gdf, POP_CANDIDATES, "population", required=False)
    dep = pick_column(gdf, DEP_CANDIDATES, "département", required=False)

    proj = gdf.to_crs(2154)
    centroids = gpd.GeoSeries(proj.geometry.centroid, crs=2154).to_crs(4326)
    out = pd.DataFrame({
        "code_commune": gdf[code].astype(str).str.zfill(5).to_numpy(),
        "nom_commune": gdf[name].to_numpy() if name else None,
        "dep": gdf[dep].astype(str).to_numpy() if dep else gdf[code].astype(str).str[:2].to_numpy(),
        "population": pd.to_numeric(gdf[pop], errors="coerce").to_numpy() if pop else np.nan,
        "superficie_km2": (proj.geometry.area / 1e6).to_numpy(),
        "centre_lat": centroids.y.to_numpy(),
        "centre_lon": centroids.x.to_numpy(),
    })
    return add_density(out)


def add_density(communes: pd.DataFrame) -> pd.DataFrame:
    out = communes.copy()
    area = out["superficie_km2"].where(out["superficie_km2"] > 0)
    out["densite"] = out["population"] / area
    out["classe_densite"] = density_class(out["densite"])
    return out


FILOSOFI_CATALOG_ID = "DS_FILOSOFI_CC_2023_CSV_FR"


def download_filosofi_zip(session: requests.Session, dest: Path, force: bool = False) -> Path:
    """Télécharge le fichier communal Filosofi 2023 indiqué par le catalogue pynsee."""
    dest = Path(dest)
    if dest.exists() and not force:
        return dest

    from pynsee.melodi import get_catalog

    catalog = get_catalog(silent=True)
    matches = catalog.loc[catalog["id"].astype(str).eq(FILOSOFI_CATALOG_ID), "accessURL"]
    if len(matches) != 1 or not str(matches.iloc[0]).startswith("https://"):
        raise ValueError(f"Jeu Filosofi absent ou URL ambiguë dans le catalogue pynsee : {FILOSOFI_CATALOG_ID}")
    response = session.get(matches.iloc[0], timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    content = response.content
    if not zipfile.is_zipfile(io.BytesIO(content)):
        raise ValueError("Le téléchargement Filosofi n'est pas une archive ZIP valide.")
    atomic_write_bytes(dest, content)
    return dest


def read_filosofi_income_zip(source: Path | bytes) -> pd.DataFrame:
    """Extrait la médiane 2023 du niveau de vie pour chaque commune diffusable.

    Les valeurs confidentielles ou absentes restent manquantes : elles ne sont
    ni imputées ni remplacées par une valeur nulle.
    """
    buffer = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    with zipfile.ZipFile(buffer) as archive:
        files = [name for name in archive.namelist() if name.lower().endswith("_data.csv")]
        if len(files) != 1:
            raise ValueError(f"Archive Filosofi attendue avec un seul *_data.csv, trouvé : {files}")
        with archive.open(files[0]) as stream:
            data = pd.read_csv(
                stream,
                sep=";",
                usecols=["GEO", "GEO_OBJECT", "FILOSOFI_MEASURE", "TIME_PERIOD", "OBS_VALUE"],
                dtype={"GEO": "string", "GEO_OBJECT": "string", "FILOSOFI_MEASURE": "string"},
            )

    data = data[
        data["GEO_OBJECT"].eq("COM")
        & data["FILOSOFI_MEASURE"].eq("MED_SL")
        & pd.to_numeric(data["TIME_PERIOD"], errors="coerce").eq(2023)
    ].dropna(subset=["GEO"]).copy()
    data["code_commune"] = data["GEO"].astype("string").str.strip().str.zfill(5)
    data["revenu_median_eur"] = pd.to_numeric(data["OBS_VALUE"], errors="coerce")
    data["annee_revenu"] = 2023
    result = data[["code_commune", "revenu_median_eur", "annee_revenu"]]
    if result["code_commune"].duplicated().any():
        raise ValueError("Le fichier Filosofi contient plusieurs médianes 2023 pour une commune.")
    return result.reset_index(drop=True)


def add_income_quartiles(communes: pd.DataFrame) -> pd.DataFrame:
    """Classe les communes par quartile de revenu médian (distribution communale)."""
    out = communes.copy()
    values = pd.to_numeric(out["revenu_median_eur"], errors="coerce")
    valid = values.notna()
    out["quartile_revenu"] = pd.Series(pd.NA, index=out.index, dtype="string")
    if valid.sum() < 4:
        return out
    codes = pd.qcut(values.loc[valid], q=4, labels=False, duplicates="drop")
    labels = ["Q1 (bas)", "Q2", "Q3", "Q4 (haut)"][:int(codes.max()) + 1]
    out.loc[valid, "quartile_revenu"] = codes.astype(int).map(dict(enumerate(labels))).astype("string")
    return out


def assign_commune_spatial(stations: pd.DataFrame, communes_gdf) -> pd.DataFrame:
    """Rattache chaque station à la commune dont le polygone la contient
    (jointure spatiale) : contrôle indépendant du géocodage inverse IGN."""
    import geopandas as gpd

    code = pick_column(communes_gdf, CODE_CANDIDATES, "code commune")
    pts = gpd.GeoDataFrame(stations[["station_id"]].copy(),
                           geometry=gpd.points_from_xy(stations["lon"], stations["lat"]), crs=4326)
    polys = gpd.GeoDataFrame(communes_gdf[[code, "geometry"]]).to_crs(4326)
    joined = gpd.sjoin(pts, polys, how="left", predicate="within")
    joined = joined.drop_duplicates(subset="station_id")
    return pd.DataFrame({"station_id": joined["station_id"].to_numpy(),
                         "code_commune_spatial": joined[code].astype("string").str.zfill(5).to_numpy()})
