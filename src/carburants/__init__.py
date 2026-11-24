"""Package du projet « Les déserts de carburant ».

Organisation (une étape = un module, sans effet de bord à l'import) :

- ``config``      : chemins, URL des sources, seuils de nettoyage ;
- ``io_utils``    : écritures atomiques, hachage, journaux JSONL ;
- ``cleaning``    : nettoyage des stations et des prix ;
- ``brands``      : normalisation et classification des enseignes ;
- ``osm``         : requête Overpass et appariement stations ↔ OpenStreetMap ;
- ``geo``         : distances (haversine) et voisinages ;
- ``competition`` : indicateurs de concurrence locale et déserts de carburant ;
- ``analysis``    : statistiques descriptives et régressions ;
- ``viz``         : graphiques matplotlib ;
- ``storage``     : stockage local ou S3 ;
- ``panel``       : reconstruction d'un panel à partir des captures.
"""

__version__ = "0.1.0"
