"""Fonctions de collecte et de traitement pour l'analyse des déserts de carburant.

Les règles de collecte reprennent la logique du code écrit par
François Ndoumbe (dossier collecte/).
"""

import io
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import requests
from sklearn.neighbors import BallTree

URL_FLUX = "https://donnees.roulez-eco.fr/opendata/instantane"
URL_COMMUNES = (
    "https://geo.api.gouv.fr/communes"
    "?fields=code,nom,centre,population,surface,codeDepartement&format=json"
)
RAYON_TERRE_KM = 6371


def telecharger_stations_et_prix():
    """Télécharge le flux officiel des prix et renvoie (df_stations, df_prix)."""
    reponse = requests.get(URL_FLUX, timeout=120)
    reponse.raise_for_status()

    archive = zipfile.ZipFile(io.BytesIO(reponse.content))
    racine = ET.fromstring(archive.read(archive.namelist()[0]))

    stations, prix = [], []
    for pdv in racine.findall("pdv"):
        stations.append({
            "id": pdv.get("id"),
            "latitude": pdv.get("latitude"),
            "longitude": pdv.get("longitude"),
            "cp": pdv.get("cp"),
            "type_route": pdv.get("pop"),
            "ville": pdv.findtext("ville"),
        })
        for p in pdv.findall("prix"):
            prix.append({
                "id": pdv.get("id"),
                "carburant": p.get("nom"),
                "valeur": p.get("valeur"),
                "maj": p.get("maj"),
            })

    return pd.DataFrame(stations), pd.DataFrame(prix)


def telecharger_communes():
    """Télécharge les communes françaises depuis l'API Géo."""
    reponse = requests.get(URL_COMMUNES, timeout=120)
    reponse.raise_for_status()
    return pd.json_normalize(reponse.json())


def distance_plus_proche(df_points, df_cibles):
    """Distance en km et identifiant de la cible la plus proche, pour chaque point.

    Les deux tables doivent avoir des colonnes 'latitude' et 'longitude'
    en degrés décimaux, et df_cibles une colonne 'id'.
    La distance est calculée à vol d'oiseau (haversine).
    """
    coords_cibles = np.radians(df_cibles[["latitude", "longitude"]].values)
    coords_points = np.radians(df_points[["latitude", "longitude"]].values)

    arbre = BallTree(coords_cibles, metric="haversine")
    distances, indices = arbre.query(coords_points, k=1)

    return distances[:, 0] * RAYON_TERRE_KM, df_cibles["id"].values[indices[:, 0]]
    