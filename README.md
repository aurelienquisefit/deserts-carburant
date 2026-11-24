# Les déserts de carburant en France

Projet du cours « Python pour la data science » (ENSAE). Le notebook `notebooks/rapport.ipynb` répond à
deux questions :

1. **Où se situent les déserts de carburant**, c'est-à-dire les communes éloignées de toute station, et combien
   d'habitants sont concernés ?
2. **La concurrence locale fait-elle le prix à la pompe ?** Les stations entourées de plus de concurrents affichent-elles
   des prix plus bas ?

L'analyse est descriptive : elle décrit des liaisons conditionnelles et n'établit pas d'effet causal.

*Auteurs : Aurélien Quisefit et François Moussinga.*

---

## 1. Contenu du dépôt

```
.
├── README.md                              le présent document
├── SOURCES.md                             sources, licences et citations
├── requirements.txt                       dépendances Python
├── collecte/                              modules de la chaîne de collecte, fournis à titre documentaire (non nécessaires au notebook)
├── notebooks/
│   ├── rapport.ipynb      analyse, graphes et conclusion
│   └── fonctions.py                       téléchargement du flux officiel et des API Géo
└── src/carburants/                        fonctions de calcul utilisées par le notebook
```

## 2. Prérequis

- Python 3.12 (3.10 ou plus récent devrait convenir).
- Une connexion Internet : le notebook télécharge le flux officiel des prix et interroge l'API Géo.
- Les données locales décrites à la section 3.

## 3. Données

Le dépôt contient les trois fichiers dérivés nécessaires au notebook, dans `data/interim/` :

```
data/interim/
├── osm_match.parquet               enseignes des stations (appariement OpenStreetMap)
├── communes.parquet                communes : population, superficie, revenu médian (INSEE, Filosofi 2023)
└── osm_grandes_surfaces.parquet    supermarchés et hypermarchés (OpenStreetMap, magasins bio exclus)
```

Ces fichiers sont produits par la chaîne de collecte décrite dans `collecte/`. Le flux officiel des prix et les listes
de communes sont téléchargés par le notebook lui-même. Le dossier `outputs/` est créé automatiquement.

Le notebook vérifie la présence de ces trois fichiers au démarrage et s'arrête avec un message explicite s'il en manque un.
Il recherche le dossier `src/` au niveau supérieur de `notebooks/` : le dépôt doit donc être conservé dans cette structure.

## 4. Installation

Depuis la racine du dépôt :

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Le fichier `requirements.txt` ne liste que les bibliothèques nécessaires au notebook. Les résultats dépendent surtout des
données du jour, et très peu des versions installées.

## 5. Exécution

Avec Jupyter : ouvrir `notebooks/rapport.ipynb`, puis *Kernel → Restart & Run All*.

En ligne de commande :

```bash
jupyter nbconvert --to notebook --execute --inplace notebooks/rapport.ipynb
```

Le calcul dure quelques minutes, principalement à cause des téléchargements. Les graphes sont enregistrés dans
`outputs/figures/`, sous le préfixe `collectif_`.

## 6. Sources

| Donnée | Origine | Accès dans le notebook |
|---|---|---|
| Stations, prix, ruptures | Ministère de l'Économie, flux instantané | téléchargé à chaque exécution |
| Communes (population, superficie, centre) | API Géo | téléchargé à chaque exécution |
| Noms des départements | API Géo | téléchargé à chaque exécution |
| Enseignes des stations | OpenStreetMap | fichier local `data/interim/osm_match.parquet` |
| Grandes surfaces | OpenStreetMap (`shop=supermarket`) | fichier local `data/interim/osm_grandes_surfaces.parquet` |
| Revenu médian communal | INSEE, Filosofi 2023 | fichier local `data/interim/communes.parquet` |

Licences : Licence Ouverte 2.0 pour les données du ministère, de l'IGN et de l'INSEE ; ODbL pour OpenStreetMap. Détails et
citations dans `SOURCES.md`.

Les résultats de référence sont ceux du 24 novembre 2026. Le flux des prix étant mis à jour chaque jour, les chiffres
obtenus à une autre date peuvent différer.

## 7. Méthodologie

- **Unité d'observation : la station.** C'est à ce niveau que le prix est fixé, et c'est à ce niveau que varient le nombre
  de concurrents, l'enseigne, l'accès autoroutier et la distance au supermarché.
- **Concurrence.** Nombre de stations vendant du gazole à moins de 5 km à vol d'oiseau, introduit sous la forme
  ln(1 + n).
- **Écart de prix.** Prix de la station moins la médiane départementale du gazole.
- **Modèles.** Quatre modèles emboîtés, estimés par moindres carrés ordinaires avec erreurs-types HC1 :
  - M0 : concurrence, enseigne et autoroute ;
  - M1 : M0 et densité de la population desservie ;
  - M2 : M1 et distance au supermarché le plus proche ;
  - M3 : M2 et desserte d'un désert (plus de 10 km d'une station).
- **Vérifications de robustesse.** Le notebook réestime M3 avec une pondération par la population desservie (« M3 pop. »),
  puis sur les seules stations dont l'enseigne est appariée (« M3 appar. »).
- **Population pondérée.** La médiane pondérée par la population décrit ce que vit un habitant typique, à distinguer de
  ce que vit une commune typique.

## 8. Limites

- **Corrélations, non effets causaux.** Les modèles décrivent des liaisons conditionnelles, sans établir de causalité.
- **Une seule journée de flux.** Les coefficients varient d'un jour à l'autre ; l'interprétation doit en tenir compte.
- **Distances à vol d'oiseau**, mesurées depuis le centre de la commune.
- **Enseignes issues d'OpenStreetMap.** Les stations apparues après la constitution du cache ne sont pas appariées et sortent
  des modèles.
- **Grandes surfaces.** OpenStreetMap ne distingue pas hypermarchés et supermarchés.
- **Revenu de 2023**, comparé à des prix du jour.
- **Dimension temporelle.** À la date de référence, le seuil d'analyse temporelle (24 captures sur 72 h) n'est pas atteint.
  Aucune conclusion temporelle n'est donc tirée.

## 9. Dépannage

| Message ou symptôme | Cause probable | Solution |
|---|---|---|
| `Caches absents` | un fichier de `data/interim/` manque | vérifier la section 3 |
| `ModuleNotFoundError: fonctions` | `fonctions.py` n'est pas dans le dossier du notebook | le placer dans `notebooks/` |
| `ModuleNotFoundError: carburants` | `src/carburants/` introuvable | vérifier la structure de la section 3 |
| `HTTPError: 502` ou `ConnectionError` | un service externe est temporairement indisponible | relancer le notebook |
