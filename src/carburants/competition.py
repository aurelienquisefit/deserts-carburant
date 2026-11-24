"""Indicateurs de concurrence locale et de « déserts de carburant ».

Définitions retenues (paramétrables dans ``config.py``, discutées dans le rapport) :

- **concurrents à r km** d'une station, pour un carburant donné : nombre d'*autres*
  stations situées à moins de r km (vol d'oiseau) qui affichent un prix retenu
  (valide et frais) pour ce même carburant ;
- **distance au plus proche concurrent** : idem, en km ;
- **station isolée** : aucun concurrent à moins de ``ISOLATION_THRESHOLD_KM`` ;
- **écart au voisinage** : prix de la station moins prix moyen de ses concurrents
  à 5 km (NaN si aucun) ;
- **désert de carburant (commune)** : commune dont le centroïde est à plus de
  d km de la station la plus proche (d ∈ {5, 10, 15} km, analyse de sensibilité).
  On considère toutes les stations de métropole aux coordonnées valides, qu'elles
  affichent un prix frais ou non (la présence physique d'une station suffit).
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from .config import COMPETITION_RADII_KM, DESERT_THRESHOLDS_KM, ISOLATION_THRESHOLD_KM
from .geo import count_within, nearest_k, neighbor_mean


def fuel_competition(df: pd.DataFrame, radii_km: Sequence[float] = COMPETITION_RADII_KM,
                     isolation_km: float = ISOLATION_THRESHOLD_KM,
                     neighbor_radius_km: float = 5.0) -> pd.DataFrame:
    """Indicateurs de concurrence pour **un** carburant.

    ``df`` : une ligne par station vendant ce carburant, colonnes ``station_id``,
    ``lat``, ``lon``, ``prix`` (déjà filtrée sur ``prix_retenu`` et la métropole).
    """
    d = df.dropna(subset=["lat", "lon"]).reset_index(drop=True).copy()
    lat, lon = d["lat"].to_numpy(), d["lon"].to_numpy()
    counts = count_within(lat, lon, lat, lon, [r * 1000 for r in radii_km], exclude_self=True)
    for r in radii_km:
        d[f"n_concurrents_{r:g}km"] = counts[float(r * 1000)]
    dist, _ = nearest_k(lat, lon, lat, lon, k=1, exclude_self=True)
    d["dist_concurrent_km"] = np.where(np.isfinite(dist[:, 0]), dist[:, 0] / 1000, np.nan)
    d["station_isolee"] = ~(d["dist_concurrent_km"] <= isolation_km)
    d[f"prix_moyen_voisins_{neighbor_radius_km:g}km"] = neighbor_mean(
        lat, lon, d["prix"].to_numpy(), neighbor_radius_km * 1000)
    d["ecart_voisinage"] = d["prix"] - d[f"prix_moyen_voisins_{neighbor_radius_km:g}km"]
    return d


def competition_by_fuel(prices_stations: pd.DataFrame, fuels: Sequence[str], **kwargs) -> pd.DataFrame:
    """Applique ``fuel_competition`` à chaque carburant et empile les résultats."""
    parts = []
    for fuel in fuels:
        sub = prices_stations[prices_stations["carburant"] == fuel]
        if len(sub) < 2:
            continue
        parts.append(fuel_competition(sub, **kwargs))
    return pd.concat(parts, ignore_index=True) if parts else prices_stations.iloc[0:0].copy()


def commune_deserts(communes: pd.DataFrame, stations: pd.DataFrame,
                    thresholds_km: Sequence[float] = DESERT_THRESHOLDS_KM) -> pd.DataFrame:
    """Distance du centroïde de chaque commune à la station la plus proche.

    ``communes`` : ``code_commune``, ``centre_lat``, ``centre_lon``, ``population``.
    ``stations`` : ``lat``, ``lon`` (et ``code_commune`` si disponible).
    """
    c = communes.dropna(subset=["centre_lat", "centre_lon"]).reset_index(drop=True).copy()
    s = stations.dropna(subset=["lat", "lon"])
    dist, _ = nearest_k(c["centre_lat"], c["centre_lon"], s["lat"], s["lon"], k=1)
    c["dist_station_km"] = np.where(np.isfinite(dist[:, 0]), dist[:, 0] / 1000, np.nan)
    if "code_commune" in s.columns:
        n_by_commune = s.groupby("code_commune").size()
        c["n_stations_commune"] = c["code_commune"].map(n_by_commune).fillna(0).astype(int)
    for t in thresholds_km:
        c[f"desert_{t:g}km"] = c["dist_station_km"] > t
    return c


def desert_summary(deserts: pd.DataFrame, thresholds_km: Sequence[float] = DESERT_THRESHOLDS_KM) -> pd.DataFrame:
    """Nombre et part des communes / de la population en « désert » par seuil."""
    total_pop = deserts["population"].sum(min_count=1)
    rows = []
    for t in thresholds_km:
        flag = deserts[f"desert_{t:g}km"]
        pop = deserts.loc[flag, "population"].sum(min_count=1)
        rows.append({
            "seuil_km": t,
            "n_communes": int(flag.sum()),
            "part_communes": float(flag.mean()) if len(flag) else np.nan,
            "population": float(pop) if pd.notna(pop) else np.nan,
            "part_population": float(pop / total_pop) if pd.notna(pop) and total_pop else np.nan,
        })
    return pd.DataFrame(rows)


def distance_grande_surface(stations: pd.DataFrame, grandes_surfaces: pd.DataFrame) -> pd.DataFrame:
    """Distance (km) de chaque station à la grande surface la plus proche.

    ``stations`` : ``station_id``, ``lat``, ``lon`` ; ``grandes_surfaces`` : ``lat``, ``lon``.
    Calculée **par station** et non par carburant : la distance à un magasin ne
    dépend pas du produit vendu. Une station sans coordonnées, ou sans aucune
    grande surface de référence, reçoit NaN.
    """
    s = stations[["station_id", "lat", "lon"]].dropna(subset=["lat", "lon"]).reset_index(drop=True)
    g = grandes_surfaces.dropna(subset=["lat", "lon"])
    dist, _ = nearest_k(s["lat"], s["lon"], g["lat"], g["lon"], k=1)
    s["dist_grande_surface_km"] = np.where(np.isfinite(dist[:, 0]), dist[:, 0] / 1000, np.nan)
    return s[["station_id", "dist_grande_surface_km"]]


def mediane_ponderee(valeurs, poids) -> float:
    """Médiane où chaque valeur compte pour son poids (ici la population).

    Une médiane par commune dit ce qui est vrai pour une commune typique ; la médiane
    pondérée dit ce qui est vrai pour un habitant typique. Les deux ne se confondent
    pas : les communes peu peuplées sont nombreuses et souvent éloignées.
    """
    v = np.asarray(valeurs, dtype=float)
    w = np.asarray(poids, dtype=float)
    ok = np.isfinite(v) & np.isfinite(w) & (w > 0)
    v, w = v[ok], w[ok]
    if v.size == 0:
        return np.nan
    o = np.argsort(v)
    cumul = np.cumsum(w[o])
    return float(v[o][np.searchsorted(cumul, cumul[-1] / 2)])


def part_population_dans_rayon(distances, population, seuils_km: Sequence[float]) -> pd.DataFrame:
    """Part de la population vivant à au plus ``s`` km d'une station (ou d'une grande surface)."""
    d = np.asarray(distances, dtype=float)
    pop = np.asarray(population, dtype=float)
    total = np.nansum(pop)
    rows = []
    for s in seuils_km:
        dans = np.isfinite(d) & (d <= s)
        rows.append({"seuil_km": s, "part_population": float(pop[dans].sum() / total),
                     "part_communes": float(dans.mean())})
    return pd.DataFrame(rows)
