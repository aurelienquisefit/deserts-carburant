# Les déserts de carburant : la concurrence locale fait-elle le prix à la pompe ?

Projet du cours « Python pour la data science » (ENSAE). Le notebook principal, `notebooks/rapport_collectif_final.ipynb`,
répond à deux questions :

1. **Où sont les déserts de carburant**, c'est-à-dire les communes éloignées de toute station, et combien d'habitants sont concernés ?
2. **La concurrence locale fait-elle le prix à la pompe ?** Les stations ayant plus de concurrents proches affichent-elles des prix plus bas ?

L'analyse est **descriptive** : elle mesure des liaisons conditionnelles et ne tire pas d'effet causal.

Auteurs de la version d'origine : Aurélien Quisefit et François Ndoumbe.

---

## 1. Contenu du dépôt

```
.
├── README.md                     ce fichier
├── requirements.txt              dépendances Python
├── requirements-lock.txt         versions exactes utilisées pour la référence (facultatif)
├── collecte/                     code de collecte et son explication (voir collecte/Explication_des_fichiers_de_collecte.pdf)
└── notebooks/
    ├── rapport_collectif_final.ipynb   le notebook : analyse, graphes et conclusion
    └── fonctions.py                    fonctions de téléchargement (flux officiel, API Géo)
```

Le notebook importe aussi le package `carburants` et lit quelques caches. Ils ne sont **pas** dans ce dépôt (voir section 3).

## 2. Prérequis

- Python 3.12 (version utilisée pour la référence ; 3.10 ou plus récent devrait convenir).
- Une connexion Internet : le notebook télécharge le flux officiel et interroge deux API à chaque exécution.
- Environ 1 Go d'espace disque pour l'environnement Python.

## 3. Structure attendue

Le notebook est dans `notebooks/` et cherche `src/` **un niveau au-dessus**. Il faut donc cette structure :

```
projet/
├── src/carburants/                          package Python (fourni avec le projet ENSAE)
├── data/
│   ├── raw/osm/overpass_grandes_surfaces_fr.json     grandes surfaces (OpenStreetMap)
│   ├── interim/osm_match.parquet                     enseignes des stations (OpenStreetMap)
│   ├── interim/communes.parquet                      revenu médian communal (INSEE, Filosofi 2023)
│   └── snapshots/                                    captures horaires (facultatif)
├── outputs/figures/                          créé automatiquement
└── notebooks/
    ├── rapport_collectif_final.ipynb
    └── fonctions.py                          doit être dans le même dossier que le notebook
```

Les données ne sont pas versionnées dans Git (trop lourdes, et soumises à licence). Pour les obtenir :
- dans le projet ENSAE, lancer `make all` à la racine ;
- ou récupérer les trois fichiers `data/` auprès du groupe (partage S3, voir le README du projet).

Le notebook vérifie la présence des trois caches au démarrage et s'arrête avec un message explicite si l'un manque.

## 4. Installation

Depuis la racine du projet :

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Pour reproduire exactement les résultats de référence, installer plutôt `requirements-lock.txt`.

## 5. Lancer le notebook

Option A, avec Jupyter : ouvrir `notebooks/rapport_collectif_final.ipynb`, puis *Kernel → Restart & Run All*.

Option B, en ligne de commande, depuis la racine du projet :

```bash
jupyter nbconvert --to notebook --execute --inplace notebooks/rapport_collectif_final.ipynb
```

Le notebook prend quelques minutes, surtout à cause des téléchargements. Il écrit ses graphes dans `outputs/figures/` (préfixe `collectif_`).

## 6. Sources

| Donnée | Origine | Accès dans le notebook |
|---|---|---|
| Stations, prix, ruptures | Ministère de l'Économie, flux instantané | téléchargé à chaque exécution |
| Communes (population, superficie, centre) | API Géo | téléchargé à chaque exécution |
| Noms des départements | API Géo | téléchargé à chaque exécution |
| Enseignes des stations | OpenStreetMap | cache `data/interim/osm_match.parquet` |
| Grandes surfaces | OpenStreetMap (`shop=supermarket`) | cache `data/raw/osm/` |
| Revenu médian communal | INSEE, Filosofi 2023 | cache `data/interim/communes.parquet` |

Licences : Licence Ouverte 2.0 pour les données du ministère, de l'IGN et de l'INSEE ; ODbL pour OpenStreetMap.
Détails et citations dans `SOURCES.md` du projet.

**Attention : les résultats dépendent du jour du téléchargement.** Le flux des prix change chaque jour, donc les chiffres
peuvent différer de ceux de la conclusion. Les résultats de référence sont ceux du **24/11/2026**.

## 7. Méthode en bref

- **Concurrence** : nombre de stations vendant du gazole à moins de 5 km (vol d'oiseau).
- **Écart de prix** : prix de la station moins la médiane du gazole dans son département.
- **Quatre modèles emboîtés** (erreurs-types HC1) pour l'écart de la station la plus proche de chaque commune :
  - M0 : concurrence, enseigne et autoroute ;
  - M1 : M0 + densité ;
  - M2 : M1 + distance au supermarché le plus proche ;
  - M3 : M2 + désert (plus de 10 km d'une station).
- **Population pondérée** : médiane de la distance pour un habitant typique, par opposition à une commune typique.

## 8. Limites

- **Corrélations, pas effets causaux.** Les modèles décrivent des liaisons conditionnelles.
- **Une seule journée de flux.** Les coefficients varient d'un jour à l'autre ; le signe et l'ordre de grandeur sont restés stables.
- **Distances à vol d'oiseau**, mesurées depuis le centre de la commune.
- **Enseignes** issues d'un cache OpenStreetMap : les stations apparues depuis ne sont pas identifiées et sont exclues des modèles.
- **Grandes surfaces** : OpenStreetMap ne distingue pas hypermarchés et supermarchés.
- **Revenu** de 2023, comparé à des prix du jour.
- **Dimension temporelle** : la collecte horaire n'a pas encore produit assez de captures (seuil : 24 captures sur 72 h).
  Tant que ce seuil n'est pas atteint, le notebook n'en tire aucune conclusion.

## 9. Dépannage

| Message | Cause probable | Solution |
|---|---|---|
| `Caches du projet absents` | structure de `data/` incomplète | voir la section 3 |
| `ModuleNotFoundError: fonctions` | `fonctions.py` n'est pas dans le dossier du notebook | le placer dans `notebooks/` |
| `ModuleNotFoundError: carburants` | `src/` introuvable | vérifier la structure de la section 3 |
| `HTTPError: 502` ou `ConnectionError` | serveur temporairement indisponible | relancer le notebook ; les étapes déjà faites ne sont pas refaites |
| Une étape marquée `echec` dans le tableau d'état | un service externe n'a pas répondu | relancer ; ne pas exploiter un résultat incomplet |
