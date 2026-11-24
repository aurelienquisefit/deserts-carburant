"""Génération du rapport PDF (reportlab) à partir des sorties **calculées**.

Le texte méthodologique (ordre des étapes, choix, limites) est fixe ; toute
phrase chiffrée est produite par ``computed_findings`` à partir de
``outputs/tables/indicateurs.json``. Si ce fichier n'existe pas, le rapport est
explicitement marqué « préliminaire — aucune donnée chargée » et ne contient
aucun chiffre.

Les polices standard PDF (Helvetica) couvrent le Latin-1 : on évite donc les
symboles mathématiques (≤, →...) dans les textes.
"""

from __future__ import annotations

import math
from pathlib import Path
from xml.sax.saxutils import escape

from . import config as C
from .io_utils import read_json

TITLE = "Les déserts de carburant — La concurrence locale fait-elle le prix à la pompe ?"

QUESTION = (
    "Question : à un instant donné, les stations-service qui ont davantage de concurrents proches "
    "affichent-elles des prix plus bas, et où se situent les communes éloignées de toute station "
    "(« déserts de carburant ») ? Le projet privilégie la collecte, le nettoyage, l'analyse "
    "descriptive, la visualisation et la reproductibilité ; aucune modélisation n'est requise et la "
    "régression éventuelle n'est qu'un résumé descriptif."
)

STEPS = [
    ("1. Flux officiel des prix (XML)",
     "Téléchargement unique du ZIP « instantané » (mis en cache, horodaté, empreinte SHA-256), "
     "lecture en flux (iterparse) des balises pdv / prix / rupture, conversion des coordonnées "
     "(degrés x 100 000) et des prix (euros, ou millièmes dans les anciens fichiers)."),
    ("2. Nettoyage",
     "Doublons, coordonnées invalides, prix hors bornes [0,50 ; 3,50] EUR/L, prix non mis à jour "
     "depuis plus de 7 jours, exclusion de l'outre-mer (prix administrés). Chaque filtre est compté "
     "dans un journal de qualité au lieu d'être appliqué silencieusement."),
    ("3. Enrichissement OpenStreetMap (Overpass)",
     "Une requête amenity=fuel pour la France et une requête shop=supermarket pour les grandes surfaces, "
     "mises en cache. Le flux officiel ne contient pas "
     "l'enseigne : elle est récupérée par appariement au plus proche objet OSM à moins de 150 m, "
     "puis classée en familles (grande distribution, pétroliers, indépendants reconnus, autre, inconnu)."),
    ("4. Géocodage IGN (Géoplateforme)",
     "Géocodage inverse par lots CSV pour obtenir le code commune INSEE de chaque station "
     "(le flux ne donne qu'un code postal). Lots mis en cache : une reprise ne renvoie que les lots manquants."),
    ("5. Contexte communal INSEE (pynsee)",
     "ADMIN EXPRESS via pynsee fournit les limites, la population communale 2023, la superficie et le "
     "centroïde. Le catalogue pynsee permet aussi de récupérer la médiane 2023 du niveau de vie "
     "(Filosofi, en euros) ; les valeurs confidentielles restent manquantes."),
    ("6. Indicateurs de concurrence et déserts",
     "Pour chaque carburant : nombre de concurrents à 1, 3, 5 et 10 km (vol d'oiseau), distance au plus "
     "proche concurrent, écart au prix moyen des voisins à 5 km, écart au prix médian départemental. "
     "Désert : commune dont le centroïde est à plus de 5, 10 ou 15 km de la station la plus proche."),
    ("7. Analyse descriptive et figures",
     "Gradients de prix par classe de concurrence, comparaisons par famille d'enseigne, type de route et "
     "densité, corrélations de Spearman, régression descriptive (écarts-types HC1), cartes."),
    ("8. Collecte horaire (optionnelle, opt-in)",
     "Script désactivé par défaut, au plus une capture par heure, déduplication par empreinte, verrou, "
     "journal JSONL horodaté ; stockage local ignoré par Git ou S3 (SSPCloud) configuré par variables "
     "d'environnement. Seule cette collecte permettrait une analyse temporelle (panel)."),
]

CODE_GUIDE = [
    {"ordre": "1", "etape": "Paramètres, chemins et URL", "fichiers": "src/carburants/config.py"},
    {"ordre": "2", "etape": "Téléchargement et lecture du flux XML", "fichiers": "src/carburants/flux.py ; scripts/01_telecharger_flux.py"},
    {"ordre": "3", "etape": "Conversion, fraîcheur et journal qualité", "fichiers": "src/carburants/cleaning.py"},
    {"ordre": "4", "etape": "Enseignes et appariement spatial OSM", "fichiers": "src/carburants/osm.py ; src/carburants/brands.py ; scripts/02_enrichir_osm.py"},
    {"ordre": "5", "etape": "Code commune IGN et contexte INSEE/Filosofi", "fichiers": "src/carburants/geocoding.py ; src/carburants/insee.py ; scripts/03_geocoder_ign.py ; scripts/04_contexte_insee.py"},
    {"ordre": "6", "etape": "Distances, concurrence et déserts", "fichiers": "src/carburants/geo.py ; src/carburants/competition.py"},
    {"ordre": "7", "etape": "Jointures, tableaux et figures", "fichiers": "src/carburants/pipeline.py ; src/carburants/analysis.py ; src/carburants/viz.py ; scripts/05_construire_dataset.py ; scripts/06_analyser.py"},
    {"ordre": "8", "etape": "Collecte temporelle et rapport", "fichiers": "src/carburants/collect.py ; src/carburants/panel.py ; src/carburants/report.py ; scripts/collecter_instantane.py ; scripts/07_generer_rapport.py"},
]

LIMITS = [
    "Coupe instantanée : sans captures répétées, on observe des corrélations à une date, pas des "
    "réactions de prix ni des effets causaux de la concurrence.",
    "Endogénéité de l'implantation : les stations s'installent là où la demande est forte ; la densité de "
    "concurrents reflète aussi la densité de population, le trafic et le type d'enseigne.",
    "Distances à vol d'oiseau : elles sous-estiment l'éloignement réel en montagne ou le long des côtes.",
    "Enseigne issue d'OSM : couverture et exactitude variables selon les contributeurs ; appariement "
    "spatial pouvant échouer pour des stations voisines (indicateur d'ambiguïté conservé).",
    "Désert défini depuis le centroïde de la commune (et non depuis les habitants) ; une commune étendue "
    "peut être mal décrite. Les stations frontalières étrangères ne sont pas prises en compte.",
    "Prix déclarés par les exploitants : retards de mise à jour possibles (filtre de fraîcheur à 7 jours).",
    "Le niveau de vie communal de Filosofi porte sur 2023, tandis que les prix sont une coupe instantanée "
    "de 2026 ; les résultats par revenu sont descriptifs, écologiques et portent sur des années différentes.",
    "Classes de densité simplifiées, non conformes à la grille communale de densité officielle.",
]


# ---------------------------------------------------------------------------
# Phrases chiffrées : uniquement à partir des indicateurs calculés
# ---------------------------------------------------------------------------
def _num(x):
    """Valeur numérique exploitable, ou None (None, NaN, texte)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _fmt(x, nd=3):
    x = _num(x)
    return "n.d." if x is None else f"{x:+.{nd}f}".replace(".", ",")


def computed_findings(metrics: dict) -> list[str]:
    """Constats rédigés automatiquement à partir de ``indicateurs.json``.

    Aucun constat n'est produit pour une grandeur absente : on ne comble jamais
    un manque par une valeur supposée.
    """
    out: list[str] = []
    grad = metrics.get("gradient_ecart_dep") or []
    for fuel in ("Gazole", "E10", "SP98"):
        rows = {r["classe_concurrence"]: r for r in grad if r.get("carburant") == fuel}
        lo, hi = rows.get("0"), rows.get("> 10")
        if lo and hi and _num(lo.get("mediane")) is not None and _num(hi.get("mediane")) is not None:
            out.append(
                f"{fuel} : écart médian au prix départemental de {_fmt(lo['mediane'])} EUR/L pour les "
                f"stations sans concurrent à 5 km (n = {lo['n']}) contre {_fmt(hi['mediane'])} EUR/L pour "
                f"celles qui en ont plus de 10 (n = {hi['n']}).")
    for r in metrics.get("spearman") or []:
        if r.get("variable_x") == "n_concurrents_5km" and _num(r.get("rho_spearman")) is not None:
            out.append(f"{r['carburant']} : corrélation de Spearman entre nombre de concurrents à 5 km et "
                       f"écart au prix départemental = {_fmt(r['rho_spearman'], 2)} (n = {r['n']}).")
    for r in metrics.get("deserts") or []:
        if _num(r.get("part_population")) is not None and _num(r.get("part_communes")) is not None:
            out.append(f"Seuil {r['seuil_km']:g} km : {r['n_communes']} communes en désert "
                       f"({100 * r['part_communes']:.1f} % des communes, "
                       f"{100 * r['part_population']:.2f} % de la population)".replace(".", ",") + ".")
    route_rows = metrics.get("ecart_par_route") or []
    gazole_route = {r.get("type_route"): r for r in route_rows if r.get("carburant") == "Gazole"}
    road, motorway = gazole_route.get("route"), gazole_route.get("autoroute")
    if road and motorway and _num(road.get("mediane")) is not None and _num(motorway.get("mediane")) is not None:
        difference = motorway["mediane"] - road["mediane"]
        out.append(
            "Gazole : l'écart médian au prix départemental est de "
            f"{_fmt(road['mediane'])} EUR/L sur route (n = {road['n']}) contre "
            f"{_fmt(motorway['mediane'])} EUR/L sur autoroute (n = {motorway['n']}), "
            f"soit {_fmt(difference)} EUR/L d'écart descriptif."
        )
    family_rows = metrics.get("ecart_par_famille") or []
    gazole_family = {r.get("famille_enseigne"): r for r in family_rows if r.get("carburant") == "Gazole"}
    supermarket = gazole_family.get("grande_distribution")
    oil_company = gazole_family.get("petrolier")
    if (supermarket and oil_company and _num(supermarket.get("mediane")) is not None
            and _num(oil_company.get("mediane")) is not None):
        out.append(
            "Gazole : l'écart médian au prix départemental est de "
            f"{_fmt(supermarket['mediane'])} EUR/L pour les grandes surfaces "
            f"(n = {supermarket['n']}) contre {_fmt(oil_company['mediane'])} EUR/L "
            f"pour les pétroliers (n = {oil_company['n']}). Les stations non classées "
            "ne sont pas assimilées à des indépendants."
        )
    density_rows = metrics.get("ecart_par_densite") or []
    gazole_density = {r.get("classe_densite"): r for r in density_rows if r.get("carburant") == "Gazole"}
    low_density, mid_density = gazole_density.get("< 25"), gazole_density.get("500–2000")
    if (low_density and mid_density and _num(low_density.get("mediane")) is not None
            and _num(mid_density.get("mediane")) is not None):
        out.append(
            "Gazole : l'écart médian au prix départemental est de "
            f"{_fmt(low_density['mediane'])} EUR/L dans les communes de moins de 25 hab./km² "
            f"(n = {low_density['n']}) contre {_fmt(mid_density['mediane'])} EUR/L "
            f"dans celles de 500 à 2 000 hab./km² (n = {mid_density['n']})."
        )
    income = metrics.get("ecart_par_revenu") or []
    gazole_income = {r.get("quartile_revenu"): r for r in income if r.get("carburant") == "Gazole"}
    low, high = gazole_income.get("Q1 (bas)"), gazole_income.get("Q4 (haut)")
    if low and high and _num(low.get("mediane")) is not None and _num(high.get("mediane")) is not None:
        out.append(
            "Gazole : l'écart médian au prix départemental est de "
            f"{_fmt(low['mediane'])} EUR/L en communes du quartile de niveau de vie le plus bas "
            f"(n = {low['n']}) contre {_fmt(high['mediane'])} EUR/L dans le quartile le plus élevé "
            f"(n = {high['n']}). Cette comparaison est descriptive, pas causale."
        )
    cap = metrics.get("captures_horaires")
    if cap:
        out.append("Captures horaires : " + cap.get("diagnostic", "diagnostic indisponible."))
    return out


# ---------------------------------------------------------------------------
# Construction du PDF
# ---------------------------------------------------------------------------
def _table(rows: list[dict], columns: list[str], styles, max_rows: int = 30):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    data = [[Paragraph(f"<b>{escape(c)}</b>", styles["BodyText"]) for c in columns]]
    for r in rows[:max_rows]:
        cells = []
        for c in columns:
            v = r.get(c)
            v = f"{v:.4g}" if isinstance(v, float) else ("" if v is None else str(v))
            cells.append(Paragraph(escape(v), styles["BodyText"]))
        data.append(cells)
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c3c2b7")),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0efec")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def build_report(output: Path = C.REPORT_DIR / "rapport.pdf", metrics_path: Path = C.METRICS_JSON,
                 figures_dir: Path = C.FIGURES_DIR) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    P = lambda txt, st="BodyText": Paragraph(escape(txt), styles[st])  # noqa: E731
    metrics = read_json(metrics_path) if Path(metrics_path).exists() else None

    story = [P(TITLE, "Title"),
             P("Projet pédagogique ENSAE — Python pour la data science", "Heading3")]
    if metrics is None:
        story.append(P("RAPPORT PRÉLIMINAIRE : aucune donnée n'a été chargée (fichier "
                       "outputs/tables/indicateurs.json absent). Ce document ne contient aucun résultat "
                       "chiffré ; exécuter le pipeline (make all) puis régénérer le rapport.", "Heading4"))
    else:
        flux = metrics.get("flux", {})
        story.append(P(f"Données : flux téléchargé le {flux.get('downloaded_at_utc', 'n.d.')} (UTC), "
                       f"empreinte SHA-256 {str(flux.get('sha256', 'n.d.'))[:16]}... ; rapport généré le "
                       f"{metrics.get('genere_utc')} (UTC)."))
    story += [Spacer(1, 0.4 * cm), P("Question et périmètre", "Heading2"), P(QUESTION),
              P("Ordre des étapes et choix", "Heading2")]
    for title, text in STEPS:
        story += [P(title, "Heading4"), P(text)]
    story += [P("Guide de lecture du code", "Heading2"),
              P("Lire les composants dans cet ordre pour suivre les données depuis les sources "
                "jusqu'aux résultats :"),
              _table(CODE_GUIDE, ["ordre", "etape", "fichiers"], styles)]

    story.append(P("Résultats", "Heading2"))
    if metrics is None:
        story.append(P("Aucun résultat : les données n'ont pas encore été collectées dans ce dépôt."))
    else:
        nett = (metrics.get("nettoyage") or {}).get("etapes")
        if nett:
            story += [P("Journal de nettoyage", "Heading3"),
                      _table(nett, ["etape", "n_avant", "n_apres", "n_retires"], styles)]
        q = metrics.get("qualite", {})
        if q:
            story.append(P(f"Sources effectivement disponibles : {q.get('sources_disponibles')}."))
            coverage = q.get("couverture_sources", {})
            osm = coverage.get("osm", {})
            ign = coverage.get("geocodage_ign", {})
            insee = coverage.get("insee", {})
            if osm:
                story.append(P(
                    f"OSM : {osm.get('n_stations_appariees', 0)} stations appariées sur le réseau "
                    f"({100 * osm.get('taux_appariement', 0):.1f} %, sur {osm.get('n_objets', 0)} objets) ; "
                    f"{osm.get('n_appariements_ambigus', 0)} appariements potentiellement ambigus."
                ))
            if ign:
                story.append(P(
                    f"Géocodage IGN : {ign.get('n_stations_geocodees', 0)} codes commune renseignés sur "
                    f"{ign.get('n_stations', 0)} stations ({100 * ign.get('taux_geocodage', 0):.1f} %)."
                ))
            if insee:
                story.append(P(
                    f"INSEE : revenu médian disponible pour {insee.get('n_revenus_medians_disponibles', 0)} "
                    f"communes sur {insee.get('n_communes', 0)} ({100 * insee.get('taux_revenu_disponible', 0):.1f} %), "
                    f"millésime {insee.get('annee_revenu', 'n.d.')}."
                ))
        if metrics.get("prix_par_carburant"):
            story += [P("Prix retenus par carburant (EUR/L)", "Heading3"),
                      _table(metrics["prix_par_carburant"],
                             ["carburant", "n", "moyenne", "mediane", "p10", "p90", "ecart_type"], styles)]
        for i, (fname, caption) in enumerate([
                ("01_distribution_prix.png", "Distribution des prix"),
                ("02_gradient_concurrence.png", "Écart au prix départemental selon la concurrence"),
                ("03_carte_ecart_gazole.png", "Carte des écarts (Gazole)"),
                ("04_familles_enseigne.png", "Familles d'enseigne"),
                ("05_revenu.png", "Écarts de prix selon le niveau de vie communal"),
                ("06_carte_deserts.png", "Déserts de carburant (10 km)")]):
            path = Path(figures_dir) / fname
            if path.exists():
                img = Image(str(path))
                ratio = img.imageHeight / img.imageWidth
                img.drawWidth, img.drawHeight = 15 * cm, 15 * cm * ratio
                story += [Spacer(1, 0.3 * cm), img, P(f"Figure {i + 1} : {caption}.", "Italic")]
        if metrics.get("spearman"):
            story += [P("Corrélations de rang", "Heading3"),
                      _table(metrics["spearman"], ["carburant", "variable_x", "n", "rho_spearman"], styles)]
        if metrics.get("deserts"):
            story += [P("Déserts de carburant", "Heading3"),
                      _table(metrics["deserts"], ["seuil_km", "n_communes", "part_communes",
                                                  "population", "part_population"], styles)]
        if metrics.get("ecart_par_revenu"):
            story += [P("Écarts par quartile de niveau de vie communal", "Heading3"),
                      _table(metrics["ecart_par_revenu"],
                             ["carburant", "quartile_revenu", "n", "mediane"], styles)]
        if metrics.get("regression_descriptive"):
            story += [P("Régression descriptive (corrélations conditionnelles, non causales)", "Heading3"),
                      _table(metrics["regression_descriptive"],
                             ["carburant", "variable", "coef", "ecart_type_hc1", "n_obs"], styles)]
        story.append(P("Constats calculés", "Heading2"))
        for s in computed_findings(metrics) or ["Aucun constat calculable avec les sources disponibles."]:
            story.append(P("- " + s))

    story += [P("Analyses temporelles", "Heading2"),
              P((metrics or {}).get("captures_horaires", {}).get(
                  "diagnostic", "Diagnostic temporel absent : "
                                "seules des analyses en coupe instantanée sont possibles."))]
    story.append(P("Limites", "Heading2"))
    story += [P("- " + s) for s in LIMITS]
    story += [P("Sources", "Heading2"),
              P("Prix des carburants : ministère de l'Économie (Licence Ouverte 2.0). OpenStreetMap : "
                "contributeurs OSM (ODbL). INSEE et IGN (ADMIN EXPRESS, Géoplateforme) : Licence Ouverte 2.0, "
                "via pynsee. Détails dans SOURCES.md.")]

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp.pdf")
    SimpleDocTemplate(str(tmp), pagesize=A4, title=TITLE, leftMargin=2 * cm, rightMargin=2 * cm,
                      topMargin=2 * cm, bottomMargin=2 * cm).build(story)
    tmp.replace(output)
    return output
