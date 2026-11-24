# Sources, licences et citations

## Données

| Source | Données utilisées | Accès et vérification | Licence / mention |
|---|---|---|---|
| Ministère de l'Économie, prix des carburants | Stations, prix, dates de mise à jour, ruptures, services, type route/autoroute | [Jeu data.gouv.fr](https://www.data.gouv.fr/datasets/prix-des-carburants-en-france-flux-instantane-v2-amelioree) ; [flux ZIP](https://donnees.roulez-eco.fr/opendata/instantane_ruptures) | Licence Ouverte 2.0 ; « Source : ministère de l'Économie — prix-carburants.gouv.fr, flux du 22/11/2026 » |
| OpenStreetMap | Objets `amenity=fuel` et enseignes OSM ; objets `shop=supermarket` (grandes surfaces, magasins bio exclus) pour la distance | [API Overpass](https://overpass-api.de/api/interpreter) ; [documentation](https://wiki.openstreetmap.org/wiki/FR:Overpass_API) | ODbL 1.0 ; « © les contributeurs d'OpenStreetMap » |
| IGN Géoplateforme | Géocodage inverse (code commune INSEE) | [Documentation officielle](https://ignf.github.io/cartes.gouv.fr-documentation/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/geocodage/) ; endpoint `/reverse/csv` | Licence Ouverte 2.0 ; « Source : IGN — Géoplateforme » |
| IGN ADMIN EXPRESS COG CARTO | Polygones communaux, population légale 2023, superficie | `pynsee.geodata.get_geodata("ADMINEXPRESS-COG-CARTO.LATEST:commune")` | Licence Ouverte 2.0 ; « Source : IGN — ADMIN EXPRESS COG CARTO » |
| INSEE Filosofi 2023 | Médiane communale du niveau de vie (euros) | Catalogue public consulté via `pynsee.melodi.get_catalog()`, jeu `DS_FILOSOFI_CC_2023_CSV_FR` | Licence Ouverte 2.0 ; les valeurs confidentielles restent manquantes |

Les prix et les enseignes ne couvrent pas les mêmes phénomènes : le flux est la source de prix,
tandis qu'OSM sert à compléter le nom de l'enseigne par proximité. Le niveau de vie est un
indicateur communal 2023, comparé ici à une coupe de prix 2026 ; cette comparaison est
écologique et non causale.

## Sources documentaires consultées

- [Consignes d'évaluation du cours Python pour la data science](https://pythonds.linogaliana.fr/content/annexes/evaluation.html).
- [Tutoriel Pandas sur les jointures](https://pythonds.linogaliana.fr/content/manipulation/02_pandas_joins.html).
- [Chapitre visualisation](https://pythonds.linogaliana.fr/content/visualisation/index.html).
- [Documentation pynsee](https://pynsee.readthedocs.io/), [Géoplateforme](https://data.gouv.fr/dataservices/api-geoplateforme-geocodage) et [Filosofi](https://www.insee.fr/fr/statistiques/7758831).
- Document de cadrage fourni (deux pages : sujet, sources et calendrier).

## Logiciels

- **pynsee** — Leclerc H., Galiana L. et contributeurs, [documentation et dépôt](https://github.com/InseeFrLab/pynsee), licence MIT.
- pandas, NumPy, GeoPandas, Shapely, Matplotlib, Requests, PyArrow, ReportLab, pytest : bibliothèques open source sous leurs licences respectives.

Les données brutes, les journaux et les sorties régénérables sont exclus du dépôt Git. Les données
peuvent être conservées localement ou sur un stockage S3/SSPCloud configuré par variables
d'environnement. Ne jamais versionner de secrets ni de jetons.
