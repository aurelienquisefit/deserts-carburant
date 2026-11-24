"""Flux officiel des prix des carburants (format XML).

Schéma du fichier (décrit d'après la documentation du flux, puis vérifié sur 500
stations de la capture du 22/11/2026 ; inventaire réel avec
``scripts/inspecter_schema_flux.py``, voir ``docs/validation.md``) ::

    <pdv_liste>
      <pdv id="1000001" latitude="4620114" longitude="519791" cp="01000" pop="R">
        <adresse>596 AVENUE DE TREVOUX</adresse>
        <ville>SAINT-DENIS-LES-BOURG</ville>
        <horaires automate-24-24="1">
          <jour id="1" nom="Lundi" ferme="">
            <horaire ouverture="06.00" fermeture="22.00"/>
          </jour>
          ...
        </horaires>
        <services><service>Lavage automatique</service>...</services>
        <prix nom="Gazole" id="1" maj="2024-01-02 07:28:00" valeur="1.799"/>
        <rupture id="3" nom="E85" debut="2024-01-01 10:00:00" fin="" type="temporaire"/>
        <fermeture type="T" debut="..." fin="..."/>
      </pdv>
      ...
    </pdv_liste>

Points d'attention (traités dans ``cleaning.py``) :

- ``latitude``/``longitude`` sont en degrés × 100 000 (format « PTV_GEODECIMAL ») ;
- ``valeur`` est en euros (« 1.799 ») dans les fichiers récents, mais en millièmes
  d'euro (« 1799 ») dans les anciens fichiers : les deux sont acceptés ;
- ``maj`` est une date locale (heure française) sans fuseau explicite ;
- ``pop`` vaut ``R`` (route) ou ``A`` (autoroute) ;
- le flux ne contient **pas** l'enseigne de la station (d'où l'enrichissement OSM)
  ni le code commune INSEE (d'où le géocodage IGN).
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from .config import FLUX_INSTANTANE_URL
from .http_client import DEFAULT_TIMEOUT
from .io_utils import atomic_write_bytes, sha256_bytes, to_iso, utc_now, write_json


@dataclass
class FluxTables:
    """Les trois tables extraites d'un fichier XML (format « long »)."""

    stations: pd.DataFrame   # une ligne par point de vente
    prices: pd.DataFrame     # une ligne par (point de vente, carburant)
    ruptures: pd.DataFrame   # une ligne par rupture déclarée


# ---------------------------------------------------------------------------
# Téléchargement
# ---------------------------------------------------------------------------
def fetch_flux_bytes(session: requests.Session, url: str = FLUX_INSTANTANE_URL) -> tuple[bytes, dict]:
    """Télécharge le ZIP du flux et renvoie (contenu, métadonnées HTTP).

    Lève une ``ValueError`` si la réponse n'est pas un ZIP (page d'erreur HTML...).
    """
    resp = session.get(url, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    content = resp.content
    if not content.startswith(b"PK"):
        raise ValueError(f"Réponse inattendue (pas un ZIP) depuis {url} : {content[:80]!r}")
    meta = {
        "url": url,
        "http_status": resp.status_code,
        "last_modified": resp.headers.get("Last-Modified"),
        "etag": resp.headers.get("ETag"),
        "content_length": len(content),
        "sha256": sha256_bytes(content),
    }
    return content, meta


def download_flux(session: requests.Session, dest_zip: Path, dest_meta: Path,
                  url: str = FLUX_INSTANTANE_URL, force: bool = False) -> Path:
    """Télécharge le flux une fois et le met en cache (idempotent).

    Sans ``force``, un fichier déjà présent est réutilisé : relancer le pipeline
    ne sollicite pas le serveur et reproduit exactement les mêmes résultats.
    """
    dest_zip = Path(dest_zip)
    if dest_zip.exists() and not force:
        return dest_zip
    downloaded_at = utc_now()
    content, meta = fetch_flux_bytes(session, url)
    atomic_write_bytes(dest_zip, content)
    meta["downloaded_at_utc"] = to_iso(downloaded_at)
    write_json(dest_meta, meta)
    return dest_zip


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------
def read_xml_from_zip(zip_source: Path | bytes) -> bytes:
    """Renvoie les octets de l'unique fichier XML contenu dans l'archive."""
    buffer = io.BytesIO(zip_source) if isinstance(zip_source, (bytes, bytearray)) else zip_source
    with zipfile.ZipFile(buffer) as zf:
        xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if len(xml_names) != 1:
            raise ValueError(f"L'archive devrait contenir exactement un XML, trouvé : {xml_names}")
        return zf.read(xml_names[0])


def _text(elem: ET.Element, tag: str) -> str | None:
    child = elem.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def parse_flux_xml(xml_bytes: bytes) -> FluxTables:
    """Parse le XML en flux (``iterparse``) pour limiter la mémoire.

    Les valeurs sont gardées **brutes** (chaînes) : toute conversion est faite
    dans ``cleaning.py`` pour que chaque règle soit explicite et testée.
    L'encodage (ISO-8859-1) est lu dans la déclaration XML par le parseur.
    """
    stations, prices, ruptures = [], [], []
    for _event, elem in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        if elem.tag != "pdv":
            continue
        sid = elem.get("id")
        horaires = elem.find("horaires")
        services = elem.find("services")
        stations.append({
            "station_id": sid,
            "latitude_raw": elem.get("latitude"),
            "longitude_raw": elem.get("longitude"),
            "cp": elem.get("cp"),
            "pop": elem.get("pop"),
            "adresse": _text(elem, "adresse"),
            "ville": _text(elem, "ville"),
            "automate_24_24": horaires.get("automate-24-24") if horaires is not None else None,
            "services": "|".join(s.text.strip() for s in services.findall("service") if s.text)
            if services is not None else "",
            "fermeture_type": elem.find("fermeture").get("type") if elem.find("fermeture") is not None else None,
        })
        for p in elem.findall("prix"):
            if p.get("nom") is None and p.get("valeur") is None:
                continue  # balise <prix/> vide rencontrée dans certains fichiers
            prices.append({
                "station_id": sid,
                "carburant": p.get("nom"),
                "carburant_id": p.get("id"),
                "maj_raw": p.get("maj"),
                "valeur_raw": p.get("valeur"),
            })
        for r in elem.findall("rupture"):
            ruptures.append({
                "station_id": sid,
                "carburant": r.get("nom"),
                "carburant_id": r.get("id"),
                "debut_raw": r.get("debut"),
                "fin_raw": r.get("fin"),
                "type": r.get("type"),
            })
        elem.clear()  # libère la mémoire du sous-arbre déjà traité

    return FluxTables(
        stations=pd.DataFrame(stations, columns=[
            "station_id", "latitude_raw", "longitude_raw", "cp", "pop", "adresse", "ville",
            "automate_24_24", "services", "fermeture_type"]),
        prices=pd.DataFrame(prices, columns=["station_id", "carburant", "carburant_id", "maj_raw", "valeur_raw"]),
        ruptures=pd.DataFrame(ruptures, columns=["station_id", "carburant", "carburant_id",
                                                 "debut_raw", "fin_raw", "type"]),
    )


def describe_schema(xml_bytes: bytes, max_pdv: int = 200) -> dict:
    """Inventaire empirique du schéma : balises et attributs réellement observés
    sur les ``max_pdv`` premiers points de vente. Sert à vérifier la description
    ci-dessus sur un vrai fichier plutôt que de la supposer."""
    tags: dict[str, set] = {}
    n = 0
    for _event, elem in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
        if elem.tag == "pdv":
            for sub in elem.iter():
                tags.setdefault(sub.tag, set()).update(sub.attrib.keys())
            n += 1
            elem.clear()
            if n >= max_pdv:
                break
    return {"n_pdv_inspectes": n, "balises": {k: sorted(v) for k, v in sorted(tags.items())}}
