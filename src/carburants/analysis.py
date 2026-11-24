"""Statistiques descriptives sur la relation concurrence locale ↔ prix.

Stratégie descriptive (pas de modélisation obligatoire) :

1. distribution des prix par carburant ;
2. prix médian par classe de nombre de concurrents (gradient brut) ;
3. même chose sur l'**écart au prix médian départemental**, pour neutraliser une
   partie des différences géographiques (fiscalité identique, mais coûts
   logistiques et niveaux de demande différents selon les territoires) ;
4. comparaison par famille d'enseigne (grande distribution vs pétroliers),
   facteur de confusion majeur : les hypermarchés sont en zone dense ;
5. corrélations de rang (Spearman), robustes aux valeurs extrêmes ;
6. *optionnel* : une régression linéaire descriptive (MCO, écarts-types HC1),
   interprétée comme une corrélation conditionnelle et **non** comme un effet causal.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

COMPETITION_BINS = [-0.5, 0.5, 1.5, 2.5, 5.5, 10.5, np.inf]
COMPETITION_LABELS = ["0", "1", "2", "3–5", "6–10", "> 10"]


def describe_prices(df: pd.DataFrame, by: Sequence[str] | str, value: str = "prix") -> pd.DataFrame:
    """Effectif, moyenne, quantiles et écart-type de ``value`` par groupe."""
    g = df.groupby(by, observed=True)[value]
    out = g.agg(n="count", moyenne="mean", ecart_type="std", mediane="median")
    out["p10"] = g.quantile(0.10)
    out["p90"] = g.quantile(0.90)
    return out.reset_index()


def competition_class(n_competitors: pd.Series) -> pd.Series:
    return pd.cut(n_competitors, bins=COMPETITION_BINS, labels=COMPETITION_LABELS)


def add_departement_gap(df: pd.DataFrame, dep_col: str = "dep") -> pd.DataFrame:
    """Ajoute ``ecart_dep`` = prix − médiane (carburant × département)."""
    out = df.copy()
    med = out.groupby(["carburant", dep_col], observed=True)["prix"].transform("median")
    out["ecart_dep"] = out["prix"] - med
    return out


def spearman_by_fuel(df: pd.DataFrame, x: str, y: str, min_n: int = 30) -> pd.DataFrame:
    """Corrélation de Spearman entre ``x`` et ``y`` pour chaque carburant."""
    rows = []
    for fuel, sub in df.groupby("carburant", observed=True):
        sub = sub[[x, y]].dropna()
        rho = sub[x].rank().corr(sub[y].rank()) if len(sub) >= min_n else np.nan
        rows.append({"carburant": fuel, "n": len(sub), "variable_x": x, "variable_y": y, "rho_spearman": rho})
    return pd.DataFrame(rows)


def ols_hc1(y: np.ndarray, X: np.ndarray, names: Sequence[str]) -> pd.DataFrame:
    """MCO avec constante déjà incluse dans X ; écarts-types robustes HC1.

    Implémentation NumPy volontairement explicite (pédagogique) :
    β = (X'X)⁻¹X'y ; V = n/(n−k) (X'X)⁻¹ X' diag(e²) X (X'X)⁻¹.
    """
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    n, k = X.shape
    if n <= k:
        raise ValueError("Pas assez d'observations pour estimer le modèle.")
    xtx_inv = np.linalg.pinv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    resid = y - X @ beta
    meat = (X * resid[:, None] ** 2).T @ X
    cov = xtx_inv @ meat @ xtx_inv * n / (n - k)
    se = np.sqrt(np.diag(cov))
    return pd.DataFrame({"variable": list(names), "coef": beta, "ecart_type_hc1": se,
                         "t": beta / se, "n_obs": n})


def descriptive_regression(df: pd.DataFrame, fuel: str, competition_col: str = "n_concurrents_5km") -> pd.DataFrame:
    """ecart_dep ~ log(1+concurrents) + famille d'enseigne + autoroute, pour un carburant."""
    sub = df[(df["carburant"] == fuel)].dropna(subset=["ecart_dep", competition_col])
    if sub.empty:
        return pd.DataFrame()
    cols = {"constante": np.ones(len(sub)),
            "log1p_concurrents": np.log1p(sub[competition_col].to_numpy(dtype=float))}
    if "famille_enseigne" in sub:
        for fam in ("grande_distribution", "independant", "inconnu", "autre"):
            cols[f"famille_{fam}"] = (sub["famille_enseigne"] == fam).to_numpy(dtype=float)
    if "type_route" in sub:
        cols["autoroute"] = (sub["type_route"] == "autoroute").to_numpy(dtype=float)
    # retire les indicatrices constantes (sinon colinéarité avec la constante)
    cols = {k: v for k, v in cols.items() if k == "constante" or np.ptp(v) > 0}
    X = np.column_stack(list(cols.values()))
    res = ols_hc1(sub["ecart_dep"].to_numpy(), X, list(cols.keys()))
    res.insert(0, "carburant", fuel)
    return res


def gradient_table(df: pd.DataFrame, competition_col: str = "n_concurrents_5km",
                   value: str = "prix") -> pd.DataFrame:
    """Statistiques de ``value`` par carburant × classe de concurrence."""
    d = df.copy()
    d["classe_concurrence"] = competition_class(d[competition_col])
    return describe_prices(d, ["carburant", "classe_concurrence"], value=value)


DISTANCE_GS_BINS = [-np.inf, 1, 3, 5, 10, np.inf]  # km, bornes incluses à droite
DISTANCE_GS_LABELS = ["≤ 1 km", "1–3 km", "3–5 km", "5–10 km", "> 10 km"]


def gradient_distance_gs(df: pd.DataFrame, value: str = "ecart_dep") -> pd.DataFrame:
    """Statistiques de ``value`` par carburant × tranche de distance à la grande surface."""
    d = df.copy()
    d["classe_distance_gs"] = pd.cut(d["dist_grande_surface_km"], bins=DISTANCE_GS_BINS,
                                     labels=DISTANCE_GS_LABELS)
    return describe_prices(d, ["carburant", "classe_distance_gs"], value=value)


def r_carre(y: np.ndarray, X: np.ndarray) -> float:
    """Part de la variance de ``y`` expliquée par le modèle MCO (X contient déjà la constante).

    Un R² faible n'invalide pas une corrélation conditionnelle : il dit seulement qu'une grande
    part des écarts tient à des facteurs non observés (demande, état de la station, timing des prix).
    """
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    beta = np.linalg.pinv(X.T @ X) @ X.T @ y
    resid = y - X @ beta
    return float(1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean())))
