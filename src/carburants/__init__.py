"""Package du projet « Les déserts de carburant ».

Organisation (une étape = un module, sans effet de bord à l'import) :

- ``config``      : chemins, URL des sources, seuils de nettoyage ;
- ``io_utils``    : écritures atomiques, hachage, journaux JSONL ;
- ``http``        : session HTTP polie (User-Agent, retries, limitation de débit) ;
- ``flux``        : téléchargement et lecture du flux XML officiel des prix ;
- ``cleaning``    : nettoyage des stations et des prix ;
- ``brands``      : normalisation et classification des enseignes ;
- ``osm``         : requête Overpass et appariement stations ↔ OpenStreetMap ;
- ``geo``         : distances (haversine) et voisinages ;
- ``geocoding``   : géocodage inverse IGN (Géoplateforme) ;
- ``insee``       : contexte communal (pynsee) ;
- ``competition`` : indicateurs de concurrence locale et déserts de carburant ;
- ``analysis``    : statistiques descriptives ;
- ``viz``         : graphiques matplotlib ;
- ``storage``     : stockage local ou S3 (SSPCloud) ;
- ``collect``     : collecte horaire *opt-in* des prix instantanés ;
- ``panel``       : reconstruction d'un panel à partir des captures.
"""

__version__ = "0.1.0"
