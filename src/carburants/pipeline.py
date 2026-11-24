"""Orchestration des étapes, partagée par les scripts (``scripts/0*.py``) et le notebook.

Ordre des étapes (chacune lit les sorties de la précédente sur disque) :

1. ``etape_flux``       télécharger le flux officiel (cache) puis le parser et nettoyer ;
2. ``etape_osm``        interroger Overpass (cache) et apparier enseignes ;
3. ``etape_geocodage``  géocodage inverse IGN -> code commune ;
4. ``etape_insee``      contexte communal (pynsee) ;
5. ``etape_dataset``    assembler la table analytique + concurrence + déserts ;
6. ``etape_analyse``    tables, figures et indicateurs chiffrés (JSON).

Idempotence : chaque étape saute son calcul si ses sorties existent
(``force=False``) ; les téléchargements sont mis en cache ; les écritures sont
atomiques. Les étapes 2 à 4 sont **facultatives** : si leurs sorties manquent,
l'étape 5 continue en le consignant dans ``journal_qualite.json`` (l'enseigne
vaut alors « Inconnue », le département provient du code postal, etc.).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from .analysis import (add_departement_gap, describe_prices, descriptive_regression,
                       gradient_distance_gs, gradient_table, spearman_by_fuel)
from .cleaning import QualityLog, clean_prices, clean_ruptures, clean_stations
from .competition import commune_deserts, competition_by_fuel, desert_summary, distance_grande_surface
from .flux import download_flux, parse_flux_xml, read_xml_from_zip
from .io_utils import read_json, should_skip, to_iso, utc_now, write_json, write_parquet

log = logging.getLogger("carburants")


def flux_reference_time() -> datetime:
    """Instant de téléchargement du flux (métadonnées), à défaut date du fichier."""
    if C.FLUX_META.exists():
        return datetime.strptime(read_json(C.FLUX_META)["downloaded_at_utc"],
                                 "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    log.warning("Métadonnées absentes : date de modification du ZIP utilisée comme référence.")
    return datetime.fromtimestamp(C.FLUX_ZIP.stat().st_mtime, tz=timezone.utc)


# ---------------------------------------------------------------------------
# 1. Flux officiel
# ---------------------------------------------------------------------------
def etape_flux(session=None, force_download: bool = False, force: bool = False) -> dict:
    C.ensure_dirs()
    # Téléchargement seulement si le cache est absent ou si on le demande.
    if force_download or not C.FLUX_ZIP.exists():
        if session is None:
            from .http_client import make_session
            session = make_session()
        download_flux(session, C.FLUX_ZIP, C.FLUX_META, force=True)
    outputs = [C.STATIONS_PARQUET, C.PRICES_PARQUET, C.RUPTURES_PARQUET]
    # Un nouveau téléchargement invalide forcément les tables dérivées.
    if should_skip(outputs, force=force or force_download):
        log.info("Étape flux : sorties présentes, rien à refaire.")
        return {"statut": "deja_fait"}

    tables = parse_flux_xml(read_xml_from_zip(C.FLUX_ZIP))
    qlog = QualityLog()
    ref = flux_reference_time()
    ref_local = pd.Timestamp(ref).tz_convert("Europe/Paris").tz_localize(None)
    stations = clean_stations(tables.stations, qlog)
    prices = clean_prices(tables.prices, ref_local.to_pydatetime(), log=qlog)
    ruptures = clean_ruptures(tables.ruptures)
    write_parquet(stations, C.STATIONS_PARQUET)
    write_parquet(prices, C.PRICES_PARQUET)
    write_parquet(ruptures, C.RUPTURES_PARQUET)
    write_json(C.INTERIM_DIR / "journal_qualite_flux.json",
               {"reference_utc": to_iso(ref), "etapes": qlog.steps})
    return {"statut": "fait", "n_stations": len(stations), "n_prix": len(prices)}


# ---------------------------------------------------------------------------
# 2. OpenStreetMap
# ---------------------------------------------------------------------------
def etape_osm(session=None, force_download: bool = False, force: bool = False) -> dict:
    from .osm import fetch_overpass, match_stations_to_osm, parse_overpass_json

    if should_skip([C.OSM_PARQUET, C.OSM_MATCH_PARQUET], force) and not force_download:
        return {"statut": "deja_fait"}
    if session is None:
        from .http_client import make_session
        session = make_session()
    payload = fetch_overpass(session, C.OSM_JSON, force=force_download)
    osm = parse_overpass_json(payload)
    stations = pd.read_parquet(C.STATIONS_PARQUET)
    stations = stations[stations["coord_valide"]]
    match = match_stations_to_osm(stations, osm)
    write_parquet(osm, C.OSM_PARQUET)
    write_parquet(match, C.OSM_MATCH_PARQUET)
    return {"statut": "fait", "n_osm": len(osm), "taux_appariement": float(match["osm_apparie"].mean())}


# ---------------------------------------------------------------------------
# 3. Géocodage IGN
# ---------------------------------------------------------------------------
def etape_grandes_surfaces(session=None, force_download: bool = False, force: bool = False) -> dict:
    """Supermarchés et hypermarchés d'OSM (``shop=supermarket``), pour la distance des stations.

    Une requête Overpass distincte de celle des stations-service, mise en cache comme elle.
    Le tag OSM ne distingue pas hypermarchés et supermarchés : la variable mesure donc
    la distance à une grande surface au sens large.
    """
    from .osm import build_overpass_query, fetch_overpass, parse_grandes_surfaces

    if should_skip([C.GS_PARQUET], force) and not force_download:
        return {"statut": "deja_fait"}
    if session is None:
        from .http_client import make_session
        session = make_session()
    payload = fetch_overpass(session, C.GS_JSON, query=build_overpass_query(cle="shop", valeur="supermarket"),
                             force=force_download)
    gs = parse_grandes_surfaces(payload)
    write_parquet(gs, C.GS_PARQUET)
    return {"statut": "fait", "n_grandes_surfaces": len(gs)}


def etape_geocodage(session=None, force: bool = False) -> dict:
    from .geocoding import reverse_geocode

    if should_skip([C.GEOCODE_PARQUET], force):
        return {"statut": "deja_fait"}
    if session is None:
        from .http_client import make_session
        session = make_session()
    stations = pd.read_parquet(C.STATIONS_PARQUET)
    stations = stations[stations["coord_valide"]]
    geo = reverse_geocode(session, stations, cache_dir=C.INTERIM_DIR / "geocodage_lots")
    write_parquet(geo, C.GEOCODE_PARQUET)
    return {"statut": "fait", "n": len(geo), "part_code_commune": float(geo["inv_citycode"].notna().mean())}


# ---------------------------------------------------------------------------
# 4. INSEE (pynsee)
# ---------------------------------------------------------------------------
def etape_insee(force: bool = False) -> dict:
    from .http_client import make_session
    from .insee import (add_income_quartiles, communes_table, download_filosofi_zip,
                        fetch_communes_geodata, read_filosofi_income_zip)

    if should_skip([C.COMMUNES_PARQUET], force):
        return {"statut": "deja_fait"}
    C.ensure_dirs()
    gdf = fetch_communes_geodata(update=force)
    log.info("Colonnes reçues de la couche communes : %s", list(gdf.columns))
    communes = communes_table(gdf)
    session = make_session()
    filosofi_zip = download_filosofi_zip(session, C.INSEE_FILOSOFI_ZIP, force=force)
    income = read_filosofi_income_zip(filosofi_zip)
    communes = communes.merge(income, on="code_commune", how="left", validate="one_to_one")
    communes = add_income_quartiles(communes)
    write_parquet(communes, C.COMMUNES_PARQUET)
    return {
        "statut": "fait",
        "n_communes": len(communes),
        "n_revenus_disponibles": int(communes["revenu_median_eur"].notna().sum()),
        "annee_revenu": 2023,
        "colonnes_source": list(map(str, gdf.columns)),
    }


# ---------------------------------------------------------------------------
# 5. Table analytique
# ---------------------------------------------------------------------------
def _dep_from_commune(code: pd.Series) -> pd.Series:
    code = code.astype("string")
    return code.str[:3].where(code.str.startswith("97").fillna(False), code.str[:2])


def assemble_dataset(stations: pd.DataFrame, prices: pd.DataFrame,
                     osm_match: pd.DataFrame | None, geocode: pd.DataFrame | None,
                     communes: pd.DataFrame | None) -> tuple[pd.DataFrame, dict]:
    """Fonction pure (testable) : joint les sources disponibles au niveau station."""
    sources = {"osm": osm_match is not None, "geocodage_ign": geocode is not None,
               "insee": communes is not None}
    st = stations.copy()
    if osm_match is not None:
        st = st.merge(osm_match[["station_id", "enseigne", "famille_enseigne", "osm_apparie",
                                 "osm_distance_m", "match_ambigu"]], on="station_id", how="left")
    for col, default in (("enseigne", "Inconnue"), ("famille_enseigne", "inconnu")):
        st[col] = st[col].fillna(default) if col in st else default
    if geocode is not None:
        st = st.merge(geocode[["station_id", "inv_citycode"]], on="station_id", how="left")
        st["code_commune"] = st["inv_citycode"].astype("string")
    else:
        st["code_commune"] = pd.Series(pd.NA, index=st.index, dtype="string")
    st["dep"] = _dep_from_commune(st["code_commune"]).fillna(st["dep_cp"])
    if communes is not None:
        context_columns = ["code_commune", "population", "densite", "classe_densite"]
        context_columns.extend(
            c for c in ("revenu_median_eur", "annee_revenu", "quartile_revenu")
            if c in communes.columns
        )
        ctx = communes[context_columns].copy()
        ctx["code_commune"] = ctx["code_commune"].astype("string")  # même type des deux côtés
        st = st.merge(ctx, on="code_commune", how="left")

    long = prices[prices["prix_retenu"]].merge(st, on="station_id", how="inner")
    long = long[long["metropole"]]
    return long, sources


def etape_dataset(force: bool = False) -> dict:
    if should_skip([C.DATASET_PARQUET], force):
        return {"statut": "deja_fait"}
    stations = pd.read_parquet(C.STATIONS_PARQUET)
    prices = pd.read_parquet(C.PRICES_PARQUET)
    opt = lambda p: pd.read_parquet(p) if Path(p).exists() else None  # noqa: E731
    osm_match, geocode, communes = opt(C.OSM_MATCH_PARQUET), opt(C.GEOCODE_PARQUET), opt(C.COMMUNES_PARQUET)

    long, sources = assemble_dataset(stations, prices, osm_match, geocode, communes)
    comp = competition_by_fuel(long, C.MAIN_FUELS)
    comp = add_departement_gap(comp)
    gs = pd.read_parquet(C.GS_PARQUET) if C.GS_PARQUET.exists() else None
    if gs is not None:
        dist = distance_grande_surface(stations[stations["coord_valide"]], gs)
        comp = comp.merge(dist, on="station_id", how="left")
    else:
        comp["dist_grande_surface_km"] = np.nan
    write_parquet(comp, C.DATASET_PARQUET)

    report = {"sources_disponibles": sources, "n_lignes_station_carburant": int(len(comp)),
              "n_stations": int(comp["station_id"].nunique()) if len(comp) else 0}
    coverage = {}
    if osm_match is not None:
        coverage["osm"] = {
            "n_objets": int(len(pd.read_parquet(C.OSM_PARQUET))) if C.OSM_PARQUET.exists() else None,
            "n_stations_appariees": int(osm_match["osm_apparie"].sum()),
            "taux_appariement": float(osm_match["osm_apparie"].mean()) if len(osm_match) else None,
            "n_appariements_ambigus": int(osm_match["match_ambigu"].sum()),
        }
    if geocode is not None:
        coverage["geocodage_ign"] = {
            "n_stations_geocodees": int(geocode["inv_citycode"].notna().sum()),
            "n_stations": int(len(geocode)),
            "taux_geocodage": float(geocode["inv_citycode"].notna().mean()) if len(geocode) else None,
        }
    if communes is not None:
        n_income = int(communes["revenu_median_eur"].notna().sum()) if "revenu_median_eur" in communes else 0
        coverage["insee"] = {
            "n_communes": int(len(communes)),
            "n_revenus_medians_disponibles": n_income,
            "taux_revenu_disponible": float(n_income / len(communes)) if len(communes) else None,
            "annee_revenu": 2023 if "annee_revenu" in communes else None,
        }
    if gs is not None:
        coverage["grandes_surfaces"] = {
            "n_points": int(len(gs)),
            "n_stations_avec_distance": int(comp.drop_duplicates("station_id")["dist_grande_surface_km"].notna().sum()),
        }
    report["couverture_sources"] = coverage
    if communes is not None:
        metro_communes = communes[~communes["code_commune"].astype(str).str.startswith("97")]
        metro_stations = stations[stations["metropole"]]
        if geocode is not None:
            metro_stations = metro_stations.merge(
                geocode[["station_id", "inv_citycode"]].rename(columns={"inv_citycode": "code_commune"}),
                on="station_id", how="left")
        deserts = commune_deserts(metro_communes, metro_stations)
        write_parquet(deserts, C.COMMUNE_DESERTS_PARQUET)
        report["n_communes"] = int(len(deserts))
    write_json(C.QUALITY_JSON, report)
    return {"statut": "fait", **report}


# ---------------------------------------------------------------------------
# 6. Analyse descriptive
# ---------------------------------------------------------------------------
def _round(x, nd=4):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def etape_analyse(fuels_plot=("Gazole", "E10", "SP98")) -> dict:
    """Produit tables CSV, figures PNG et ``indicateurs.json``.

    Toutes les valeurs écrites sont **calculées** sur les fichiers présents ;
    rien n'est saisi à la main. Le JSON contient aussi la provenance (date du
    flux, sources disponibles, couverture des captures horaires).
    """
    from . import viz
    from .panel import load_snapshot_prices, snapshot_coverage, temporal_feasibility
    from .storage import storage_from_env

    C.ensure_dirs()
    df = pd.read_parquet(C.DATASET_PARQUET)
    T, F = C.TABLES_DIR, C.FIGURES_DIR
    metrics: dict = {"genere_utc": to_iso(utc_now())}
    if C.FLUX_META.exists():
        metrics["flux"] = read_json(C.FLUX_META)
    if C.QUALITY_JSON.exists():
        metrics["qualite"] = read_json(C.QUALITY_JSON)
    flux_q = C.INTERIM_DIR / "journal_qualite_flux.json"
    if flux_q.exists():
        metrics["nettoyage"] = read_json(flux_q)

    by_fuel = describe_prices(df, "carburant")
    by_fuel.to_csv(T / "prix_par_carburant.csv", index=False)
    metrics["prix_par_carburant"] = by_fuel.round(4).to_dict(orient="records")

    grad_prix = gradient_table(df, value="prix")
    grad_ecart = gradient_table(df, value="ecart_dep")
    grad_prix.to_csv(T / "gradient_prix.csv", index=False)
    grad_ecart.to_csv(T / "gradient_ecart_dep.csv", index=False)
    metrics["gradient_ecart_dep"] = grad_ecart.round(4).astype({"classe_concurrence": str}).to_dict(orient="records")

    correlations = [spearman_by_fuel(df, "n_concurrents_5km", "ecart_dep"),
                    spearman_by_fuel(df, "dist_concurrent_km", "ecart_dep")]
    if "revenu_median_eur" in df.columns and df["revenu_median_eur"].notna().any():
        correlations.append(spearman_by_fuel(df, "revenu_median_eur", "ecart_dep"))
    if "dist_grande_surface_km" in df.columns and df["dist_grande_surface_km"].notna().any():
        correlations.append(spearman_by_fuel(df, "dist_grande_surface_km", "ecart_dep"))
    rho = pd.concat(correlations, ignore_index=True)
    rho.to_csv(T / "correlations_spearman.csv", index=False)
    metrics["spearman"] = rho.round(4).to_dict(orient="records")

    iso = (df.groupby(["carburant", "station_isolee"])["ecart_dep"]
             .agg(n="count", mediane="median").reset_index())
    iso.to_csv(T / "isolement.csv", index=False)
    metrics["isolement"] = iso.round(4).to_dict(orient="records")

    for col, name in (("famille_enseigne", "famille"), ("type_route", "route"), ("classe_densite", "densite")):
        if col in df.columns and df[col].notna().any():
            t = describe_prices(df, ["carburant", col], value="ecart_dep")
            t.to_csv(T / f"ecart_par_{name}.csv", index=False)
            metrics[f"ecart_par_{name}"] = t.round(4).astype({col: str}).to_dict(orient="records")
    if "quartile_revenu" in df.columns and df["quartile_revenu"].notna().any():
        t = describe_prices(df, ["carburant", "quartile_revenu"], value="ecart_dep")
        t.to_csv(T / "ecart_par_revenu.csv", index=False)
        metrics["ecart_par_revenu"] = t.round(4).astype({"quartile_revenu": str}).to_dict(orient="records")
    if "dist_grande_surface_km" in df.columns and df["dist_grande_surface_km"].notna().any():
        t = gradient_distance_gs(df, value="ecart_dep")
        t.to_csv(T / "ecart_par_distance_gs.csv", index=False)
        metrics["ecart_par_distance_gs"] = t.round(4).astype({"classe_distance_gs": str}).to_dict(orient="records")

    reg = pd.concat([descriptive_regression(df, f) for f in fuels_plot], ignore_index=True)
    reg.to_csv(T / "regression_descriptive.csv", index=False)
    metrics["regression_descriptive"] = reg.round(5).to_dict(orient="records")

    # Figures
    viz.save_figure(viz.price_histograms(df, fuels_plot), F / "01_distribution_prix.png")
    viz.save_figure(viz.gradient_plot(grad_ecart, fuels_plot, "écart médian au prix départemental (€/L)"),
                    F / "02_gradient_concurrence.png")
    gazole = df[df["carburant"] == "Gazole"]
    if not gazole.empty:
        viz.save_figure(viz.gap_map(gazole, title="Gazole : écart au prix médian départemental"),
                        F / "03_carte_ecart_gazole.png")
    fam = df[df["carburant"] == "Gazole"]
    if not fam.empty:
        t = describe_prices(fam, "famille_enseigne", value="ecart_dep")
        viz.save_figure(viz.family_bars(t, label="€/L (Gazole)"), F / "04_familles_enseigne.png")
    if "quartile_revenu" in df.columns and df["quartile_revenu"].notna().any():
        gazole_revenu = df[df["carburant"] == "Gazole"]
        t = describe_prices(gazole_revenu, "quartile_revenu", value="ecart_dep")
        viz.save_figure(
            viz.income_bars(t, label="écart médian au prix départemental (€/L)"),
            F / "05_revenu.png",
        )

    if C.COMMUNE_DESERTS_PARQUET.exists():
        deserts = pd.read_parquet(C.COMMUNE_DESERTS_PARQUET)
        summ = desert_summary(deserts)
        summ.to_csv(T / "deserts_synthese.csv", index=False)
        metrics["deserts"] = summ.round(4).to_dict(orient="records")
        stations = pd.read_parquet(C.STATIONS_PARQUET)
        viz.save_figure(viz.desert_map(deserts, stations[stations["metropole"]], C.DEFAULT_DESERT_KM),
                        F / "06_carte_deserts.png")

    # Captures horaires : diagnostic explicite de faisabilité temporelle
    try:
        snap = load_snapshot_prices(storage_from_env(C.SNAPSHOT_DIR))
        cov = snapshot_coverage(snap)
    except Exception as exc:  # stockage S3 non configuré, etc.
        cov = {"n_captures": 0, "erreur": f"{type(exc).__name__}: {exc}"}
    ok, message = temporal_feasibility(cov)
    metrics["captures_horaires"] = {**cov, "analyse_temporelle_possible": ok, "diagnostic": message}

    write_json(C.METRICS_JSON, metrics)
    return metrics
