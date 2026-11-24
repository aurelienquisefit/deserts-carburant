"""Calculs de distances et de voisinages, en NumPy pur.

Choix : la distance de grand cercle (haversine) sur une sphère de rayon
6 371 km. L'erreur par rapport à l'ellipsoïde (< 0,5 %) est négligeable pour des
rayons de 1 à 15 km. Les distances sont « à vol d'oiseau » : une distance
routière serait plus pertinente pour un automobiliste mais demanderait un
calculateur d'itinéraires (limite discutée dans le rapport).

Pour ~11 000 stations, la matrice complète ferait 121 millions de paires ; on la
calcule donc **par blocs** de lignes pour borner la mémoire.
"""

from __future__ import annotations

from typing import Iterator, Sequence

import numpy as np

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Distance haversine en mètres (diffusion NumPy : scalaires ou tableaux)."""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(x, dtype=float)) for x in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _distance_blocks(q_lat, q_lon, r_lat, r_lon, chunk_size: int) -> Iterator[tuple[int, int, np.ndarray]]:
    """Génère (début, fin, matrice des distances bloc × référence)."""
    q_lat = np.asarray(q_lat, dtype=float)
    q_lon = np.asarray(q_lon, dtype=float)
    r_lat = np.asarray(r_lat, dtype=float)
    r_lon = np.asarray(r_lon, dtype=float)
    for start in range(0, len(q_lat), chunk_size):
        stop = min(start + chunk_size, len(q_lat))
        d = haversine_m(q_lat[start:stop, None], q_lon[start:stop, None], r_lat[None, :], r_lon[None, :])
        yield start, stop, d


def count_within(q_lat, q_lon, r_lat, r_lon, radii_m: Sequence[float],
                 exclude_self: bool = False, chunk_size: int = 512) -> dict[float, np.ndarray]:
    """Nombre de points de référence à une distance ≤ r de chaque point requête.

    ``exclude_self=True`` suppose que requêtes et références sont **le même
    ensemble dans le même ordre** : le point i n'est pas compté comme son propre
    voisin (deux stations distinctes au même endroit restent comptées).
    """
    n = len(np.asarray(q_lat))
    counts = {float(r): np.zeros(n, dtype=int) for r in radii_m}
    for start, stop, d in _distance_blocks(q_lat, q_lon, r_lat, r_lon, chunk_size):
        if exclude_self:
            rows = np.arange(stop - start)
            d[rows, start + rows] = np.inf
        for r in counts:
            counts[r][start:stop] = (d <= r).sum(axis=1)
    return counts


def neighbor_mean(lat, lon, values, radius_m: float, chunk_size: int = 512) -> np.ndarray:
    """Moyenne de ``values`` chez les voisins à ≤ ``radius_m`` (soi-même exclu).

    Même ensemble pour requêtes et références. NaN si aucun voisin. Sert à
    calculer l'écart de prix d'une station à ses concurrents immédiats.
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    out = np.full(n, np.nan)
    valid = np.isfinite(values)
    for start, stop, d in _distance_blocks(lat, lon, lat, lon, chunk_size):
        rows = np.arange(stop - start)
        d[rows, start + rows] = np.inf
        mask = (d <= radius_m) & valid[None, :]
        cnt = mask.sum(axis=1)
        sums = (mask * np.where(valid, values, 0.0)[None, :]).sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[start:stop] = np.where(cnt > 0, sums / np.maximum(cnt, 1), np.nan)
    return out


def nearest_k(q_lat, q_lon, r_lat, r_lon, k: int = 1, exclude_self: bool = False,
              chunk_size: int = 512) -> tuple[np.ndarray, np.ndarray]:
    """k plus proches voisins : renvoie (distances en m, indices), triés par distance.

    Si moins de k références sont disponibles, les colonnes manquantes valent
    ``inf`` (distance) et ``-1`` (indice).
    """
    n = len(np.asarray(q_lat))
    n_ref = len(np.asarray(r_lat))
    dist = np.full((n, k), np.inf)
    idx = np.full((n, k), -1, dtype=int)
    if n == 0 or n_ref == 0:
        return dist, idx
    kk = min(k, n_ref)
    for start, stop, d in _distance_blocks(q_lat, q_lon, r_lat, r_lon, chunk_size):
        if exclude_self:
            rows = np.arange(stop - start)
            d[rows, start + rows] = np.inf
        if kk < n_ref:
            part = np.argpartition(d, kk - 1, axis=1)[:, :kk]
        else:
            part = np.tile(np.arange(n_ref), (stop - start, 1))
        part_d = np.take_along_axis(d, part, axis=1)
        order = np.argsort(part_d, axis=1)
        dist[start:stop, :kk] = np.take_along_axis(part_d, order, axis=1)
        idx[start:stop, :kk] = np.take_along_axis(part, order, axis=1)
    # une distance infinie (soi-même exclu, aucun autre point) n'a pas d'indice valide
    idx[~np.isfinite(dist)] = -1
    return dist, idx
