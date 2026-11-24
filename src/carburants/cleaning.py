"""Nettoyage des tables issues du flux XML.

Principe : on **n'efface rien silencieusement**. Chaque règle ajoute une colonne
booléenne (``coord_valide``, ``prix_valide``, ``prix_frais``...) et le
``QualityLog`` enregistre combien de lignes chaque filtre retire. Ces comptages,
calculés sur les données réellement chargées, alimentent le rapport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from .config import MAX_PRICE_AGE_DAYS, METRO_BBOX, PRICE_MAX_EUR, PRICE_MIN_EUR


# ---------------------------------------------------------------------------
# Journal de qualité
# ---------------------------------------------------------------------------
@dataclass
class QualityLog:
    steps: list[dict] = field(default_factory=list)

    def record(self, step: str, n_before: int, n_after: int, comment: str = "") -> None:
        self.steps.append({"etape": step, "n_avant": int(n_before), "n_apres": int(n_after),
                           "n_retires": int(n_before - n_after), "commentaire": comment})

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.steps, columns=["etape", "n_avant", "n_apres", "n_retires", "commentaire"])


# ---------------------------------------------------------------------------
# Conversions élémentaires (pures, testées unitairement)
# ---------------------------------------------------------------------------
def to_float(series: pd.Series) -> pd.Series:
    """Chaîne -> float ; accepte la virgule décimale ; valeurs illisibles -> NaN."""
    # astype(str) : None/NaN deviennent "None"/"nan", que to_numeric convertit en NaN.
    # On évite volontairement les types « nullables » pour garder des float64 simples.
    s = series.astype(str).str.strip().str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce").astype(float)


def convert_coordinate(series: pd.Series) -> pd.Series:
    """Coordonnée brute -> degrés décimaux WGS84.

    Le flux code les degrés × 100 000 (« 4620114 » = 46.20114°). Une valeur dont
    la valeur absolue dépasse 360 ne peut pas être un angle en degrés : on la
    divise donc par 100 000. Une valeur déjà en degrés est laissée telle quelle.
    Zéro est traité comme manquant (valeur par défaut observée dans ce type de flux).
    """
    v = to_float(series)
    v = v.where(v.abs() <= 360, v / 100_000)
    return v.where(v != 0)


def convert_price(series: pd.Series) -> pd.Series:
    """Prix brut -> euros par litre (gère euros « 1.799 » et millièmes « 1799 »)."""
    v = to_float(series)
    return v.where(v <= 100, v / 1000)


def parse_local_datetime(series: pd.Series) -> pd.Series:
    """Date de mise à jour -> datetime naïf en heure locale française.

    Formats acceptés : « 2024-01-02 07:28:00 », « 2024-01-02T07:28:00 » et,
    s'il y en a, un suffixe de fuseau (converti en heure de Paris puis rendu naïf).
    """
    s = series.astype("string").str.strip()
    parsed = pd.to_datetime(s, errors="coerce", utc=False, format="mixed")
    if isinstance(parsed.dtype, pd.DatetimeTZDtype):
        parsed = parsed.dt.tz_convert("Europe/Paris").dt.tz_localize(None)
    return parsed


def departement_from_cp(cp: pd.Series) -> pd.Series:
    """Code département *approximatif* tiré du code postal.

    Approximation documentée : le code postal ne coïncide pas toujours avec le
    département (communes limitrophes, Cedex). Le code commune INSEE issu du
    géocodage IGN reste la référence ; ceci sert seulement de contrôle.
    Corse : 200xx-201xx -> 2A, 202xx-206xx -> 2B. Outre-mer : 97x.
    """
    cp = cp.astype("string").str.strip().str.zfill(5)
    prefix = cp.str[:2]
    # astype(str) : "<NA>" -> NaN, pour obtenir un float64 simple (np.where refuse pd.NA)
    num = pd.to_numeric(cp.astype(str), errors="coerce").to_numpy(dtype=float)
    corse = pd.Series(np.where(num < 20200, "2A", "2B"), index=cp.index, dtype="string")
    dep = prefix.mask(prefix.eq("20").fillna(False), corse)
    dep = dep.mask(prefix.eq("97").fillna(False), cp.str[:3])
    return dep


def in_metropole(lat: pd.Series, lon: pd.Series, bbox: dict = METRO_BBOX) -> pd.Series:
    return (lat.between(bbox["lat_min"], bbox["lat_max"]) &
            lon.between(bbox["lon_min"], bbox["lon_max"]))


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
def clean_stations(raw: pd.DataFrame, log: QualityLog | None = None) -> pd.DataFrame:
    """Nettoie la table des points de vente.

    Colonnes ajoutées : ``lat``, ``lon``, ``cp`` (5 caractères), ``dep_cp``,
    ``outre_mer``, ``coord_valide``, ``metropole``, ``type_route``.
    """
    log = log or QualityLog()
    df = raw.copy()
    n0 = len(df)
    # identifiant gardé en ``str`` simple (type identique à celui de la table des prix
    # pour que les jointures ne dépendent pas des types « nullables » de pandas)
    df = df.dropna(subset=["station_id"])
    df["station_id"] = df["station_id"].astype(str).str.strip()
    df = df.drop_duplicates(subset="station_id", keep="first")
    log.record("stations: identifiant manquant ou doublon", n0, len(df))

    df["lat"] = convert_coordinate(df["latitude_raw"])
    df["lon"] = convert_coordinate(df["longitude_raw"])
    df["cp"] = df["cp"].astype("string").str.strip().str.zfill(5)
    df["dep_cp"] = departement_from_cp(df["cp"])
    df["outre_mer"] = df["dep_cp"].str.startswith("97").fillna(False).astype(bool)
    df["coord_valide"] = df["lat"].between(-90, 90) & df["lon"].between(-180, 180)
    df["metropole"] = (~df["outre_mer"]) & in_metropole(df["lat"], df["lon"])
    df["type_route"] = df["pop"].map({"R": "route", "A": "autoroute"}).fillna("inconnu")
    df["automate_24_24"] = df["automate_24_24"].astype(str).eq("1")

    log.record("stations: coordonnées invalides (signalées, non retirées)", len(df),
               int(df["coord_valide"].sum()), "à corriger éventuellement par géocodage d'adresse")
    log.record("stations: hors métropole (outre-mer ou hors emprise)", len(df),
               int(df["metropole"].sum()), "prix d'outre-mer administrés : exclus de l'analyse")
    return df.drop(columns=["latitude_raw", "longitude_raw"])


def clean_prices(raw: pd.DataFrame, reference_time: datetime,
                 max_age_days: float = MAX_PRICE_AGE_DAYS,
                 price_min: float = PRICE_MIN_EUR, price_max: float = PRICE_MAX_EUR,
                 log: QualityLog | None = None) -> pd.DataFrame:
    """Nettoie la table des prix.

    ``reference_time`` est l'instant de téléchargement du flux, exprimé en heure
    locale française *naïve* (même convention que ``maj``). L'âge d'un prix est
    ``reference_time - maj``.

    Colonnes ajoutées : ``prix`` (€/L), ``maj``, ``age_jours``, ``prix_valide``,
    ``prix_frais``, ``prix_retenu`` (= valide ET frais).
    """
    log = log or QualityLog()
    df = raw.copy()
    n0 = len(df)
    df["carburant"] = df["carburant"].astype("string").str.strip()
    df = df.dropna(subset=["station_id", "carburant"])
    log.record("prix: station ou carburant manquant", n0, len(df))

    df["prix"] = convert_price(df["valeur_raw"])
    df["maj"] = parse_local_datetime(df["maj_raw"])

    # Doublons (station, carburant) : on garde la mise à jour la plus récente.
    n1 = len(df)
    df = (df.sort_values("maj", ascending=False, na_position="last")
            .drop_duplicates(subset=["station_id", "carburant"], keep="first"))
    log.record("prix: doublons (station, carburant)", n1, len(df), "garde la mise à jour la plus récente")

    ref = pd.Timestamp(reference_time)
    if ref.tzinfo is not None:
        ref = ref.tz_convert("Europe/Paris").tz_localize(None)
    df["age_jours"] = (ref - df["maj"]).dt.total_seconds() / 86400

    df["prix_valide"] = df["prix"].between(price_min, price_max)
    # tolérance d'1 h pour une date « future » (décalage d'horloge)
    df["prix_frais"] = df["age_jours"].between(-1 / 24, max_age_days)
    df["prix_retenu"] = df["prix_valide"] & df["prix_frais"]

    log.record(f"prix: hors bornes [{price_min}; {price_max}] €/L", len(df), int(df["prix_valide"].sum()))
    log.record(f"prix: non mis à jour depuis plus de {max_age_days} jours", int(df["prix_valide"].sum()),
               int(df["prix_retenu"].sum()))
    return df.drop(columns=["valeur_raw", "maj_raw"]).reset_index(drop=True)


def clean_ruptures(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["debut"] = parse_local_datetime(df["debut_raw"])
    df["fin"] = parse_local_datetime(df["fin_raw"])
    df["en_cours"] = df["fin"].isna()
    return df.drop(columns=["debut_raw", "fin_raw"])
