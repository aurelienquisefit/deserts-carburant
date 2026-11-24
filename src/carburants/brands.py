"""Normalisation des enseignes (issues d'OSM) et classification en familles.

L'enseigne n'est pas dans le flux officiel : elle provient des étiquettes OSM
``brand`` / ``name`` / ``operator``. Les libellés OSM sont hétérogènes
(« E.Leclerc », « Leclerc », « E. Leclerc Drive »...) : on les ramène à une forme
canonique par une liste ordonnée de motifs, puis à une famille :

- ``grande_distribution`` : stations adossées à un hyper/supermarché, réputées
  pratiquer des prix bas (produit d'appel) ;
- ``petrolier`` : réseaux des compagnies pétrolières ;
- ``independant`` : réseaux explicitement reconnus comme indépendants ;
- ``inconnu`` : aucune information.
- ``autre`` : libellé présent mais non reconnu par les règles.

Cette typologie est un **choix d'analyse** discutable (cf. rapport), pas une
nomenclature officielle.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

# (motif sur le libellé normalisé, enseigne canonique, famille). L'ordre compte :
# « carrefour market » doit être testé avant « carrefour ».
BRAND_RULES: list[tuple[str, str, str]] = [
    (r"\bleclerc\b", "E.Leclerc", "grande_distribution"),
    (r"\bcarrefour (market|contact|express)\b", "Carrefour Market/Contact", "grande_distribution"),
    (r"\bcarrefour\b", "Carrefour", "grande_distribution"),
    (r"\bintermarche\b", "Intermarché", "grande_distribution"),
    (r"\bauchan\b", "Auchan", "grande_distribution"),
    (r"\b(super|hyper|systeme) u\b|^u$|\bu express\b", "Système U", "grande_distribution"),
    (r"\bcasino\b|\bgeant\b", "Casino/Géant", "grande_distribution"),
    (r"\bcora\b", "Cora", "grande_distribution"),
    (r"\bnetto\b", "Netto", "grande_distribution"),
    (r"\blidl\b", "Lidl", "grande_distribution"),
    (r"\bspar\b|\bvival\b", "Spar/Vival", "grande_distribution"),
    (r"\btotal ?energies\b|\btotal access\b|\btotal\b|\belan\b", "TotalEnergies", "petrolier"),
    (r"\besso\b", "Esso", "petrolier"),
    (r"\bbp\b", "BP", "petrolier"),
    (r"\bshell\b", "Shell", "petrolier"),
    (r"\bagip\b|\beni\b", "Eni/Agip", "petrolier"),
    (r"\bavia\b", "Avia", "independant"),
    (r"\bdyneff\b", "Dyneff", "independant"),
    (r"\bneste\b", "Neste", "independant"),
    (r"\b(station )?independant(e)?\b|\bsans enseigne\b", "Indépendant", "independant"),
]

_COMPILED = [(re.compile(p), b, f) for p, b, f in BRAND_RULES]


def normalize_label(label: object) -> str:
    """Minuscules, sans accents, ponctuation remplacée par des espaces."""
    if label is None or (isinstance(label, float) and pd.isna(label)) or label is pd.NA:
        return ""
    s = unicodedata.normalize("NFKD", str(label))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def classify_brand(*labels: object) -> tuple[str, str]:
    """Renvoie (enseigne canonique, famille) à partir de libellés candidats.

    Les libellés sont essayés dans l'ordre donné (typiquement ``brand`` puis
    ``name`` puis ``operator``) ; le premier qui correspond à une règle gagne.
    Un libellé non vide mais non reconnu donne (« Autre », « autre ») : l'absence
    de correspondance à une enseigne connue ne suffit pas à conclure qu'elle est
    indépendante.
    """
    first_non_empty = ""
    for label in labels:
        norm = normalize_label(label)
        if not norm:
            continue
        first_non_empty = first_non_empty or norm
        for pattern, brand, family in _COMPILED:
            if pattern.search(norm):
                return brand, family
    if first_non_empty:
        return "Autre", "autre"
    return "Inconnue", "inconnu"


def classify_frame(df: pd.DataFrame, columns: tuple[str, ...] = ("brand", "name", "operator")) -> pd.DataFrame:
    """Applique ``classify_brand`` ligne à ligne ; ajoute ``enseigne`` et ``famille_enseigne``."""
    present = [c for c in columns if c in df.columns]
    result = [classify_brand(*(row[c] for c in present)) for _, row in df[present].iterrows()]
    out = df.copy()
    out["enseigne"] = [r[0] for r in result]
    out["famille_enseigne"] = [r[1] for r in result]
    return out
