"""Reconstruction d'un panel de prix à partir des captures horaires.

Un panel n'existe **que si des captures ont réellement été accumulées** par
``collect.py``. ``temporal_feasibility`` dit explicitement si la couverture est
suffisante ; le rapport et le notebook s'appuient sur ce diagnostic au lieu de
supposer un historique.

Deux représentations :

- ``load_snapshot_prices`` : l'empilement brut (station × carburant × capture) ;
- ``price_change_events`` : les **changements de prix** effectifs, obtenus en
  dédupliquant sur (station, carburant, maj, prix) : un même prix vu dans 24
  captures successives ne compte qu'une fois.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd

from .cleaning import convert_price, parse_local_datetime


def load_snapshot_prices(storage, prefix: str = "prix/") -> pd.DataFrame:
    keys = [k for k in storage.list(prefix) if k.endswith(".parquet")]
    if not keys:
        return pd.DataFrame(columns=["station_id", "carburant", "maj", "prix", "capture_utc"])
    frames = [pd.read_parquet(io.BytesIO(storage.read_bytes(k))) for k in keys]
    df = pd.concat(frames, ignore_index=True)
    df["prix"] = convert_price(df["valeur_raw"])
    df["maj"] = parse_local_datetime(df["maj_raw"])
    df["capture_utc"] = pd.to_datetime(df["capture_utc"], utc=True)
    return df.drop(columns=["valeur_raw", "maj_raw"])


def snapshot_coverage(snap: pd.DataFrame) -> dict:
    """Combien de captures, sur quelle durée, à quel rythme."""
    times = pd.Series(sorted(pd.to_datetime(snap["capture_utc"], utc=True).dropna().unique()))
    if times.empty:
        return {"n_captures": 0, "premiere_utc": None, "derniere_utc": None,
                "duree_heures": 0.0, "intervalle_median_heures": None}
    gaps = times.diff().dropna().dt.total_seconds() / 3600
    return {"n_captures": int(len(times)),
            "premiere_utc": times.iloc[0].isoformat(), "derniere_utc": times.iloc[-1].isoformat(),
            "duree_heures": float((times.iloc[-1] - times.iloc[0]).total_seconds() / 3600),
            "intervalle_median_heures": float(gaps.median()) if len(gaps) else None}


def temporal_feasibility(coverage: dict, min_captures: int = 24, min_span_hours: float = 72) -> tuple[bool, str]:
    n, span = coverage.get("n_captures", 0), coverage.get("duree_heures", 0.0)
    if n == 0:
        return False, ("Aucune capture horaire n'a été collectée : aucune analyse temporelle "
                       "n'est possible ; les résultats sont une coupe transversale unique.")
    if n < min_captures or span < min_span_hours:
        return False, (f"Seulement {n} capture(s) sur {span:.1f} h : couverture insuffisante "
                       f"(seuil : {min_captures} captures et {min_span_hours:.0f} h) ; "
                       "toute lecture temporelle serait anecdotique.")
    return True, f"{n} captures sur {span:.1f} h : analyse temporelle descriptive possible."


def price_change_events(snap: pd.DataFrame) -> pd.DataFrame:
    """Une ligne par changement de prix (station, carburant), avec la variation."""
    d = snap.dropna(subset=["station_id", "carburant", "prix"]).sort_values("capture_utc")
    d = d.drop_duplicates(subset=["station_id", "carburant", "maj", "prix"], keep="first")
    d = d.sort_values(["station_id", "carburant", "maj"])
    d["prix_precedent"] = d.groupby(["station_id", "carburant"])["prix"].shift(1)
    d["variation"] = d["prix"] - d["prix_precedent"]
    d["sens"] = np.sign(d["variation"])
    return d.reset_index(drop=True)
