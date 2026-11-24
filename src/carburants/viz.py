"""Graphiques statiques (matplotlib) destinés au rapport PDF et au notebook.

Conventions graphiques (appliquées partout, pour que les figures se lisent
comme un ensemble) :

- palette catégorielle à ordre **fixe** (bleu, orange, vert d'eau) ; au plus
  trois séries par graphique, au-delà on passe en petits multiples ;
- échelle **séquentielle** à une seule teinte (bleu clair -> foncé) pour une
  grandeur, **divergente** bleu <-> rouge avec un gris neutre au centre pour
  un écart signé (bleu = moins cher que la référence, rouge = plus cher) ;
- un seul axe des ordonnées ; grille discrète ; texte en encre neutre (jamais
  dans la couleur de la série) ; légende dès deux séries + libellés directs ;
- chaque fonction renvoie une ``Figure`` ; ``save_figure`` l'enregistre en PNG.

Les cartes sont de simples nuages lon/lat avec correction d'aspect
(1/cos(latitude moyenne)), suffisantes pour la métropole.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")  # rendu sans écran (scripts, CI, SSPCloud)
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]          # emplacements catégoriels 1-3
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SEQ_BLUE = LinearSegmentedColormap.from_list("seq_bleu", ["#cde2fb", "#86b6ef", "#2a78d6", "#184f95", "#0d366b"])
DIVERGING = LinearSegmentedColormap.from_list("div_bleu_rouge", ["#1c5cab", "#86b6ef", "#f0efec", "#ef9a99", "#c23232"])

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold",
    "lines.linewidth": 2, "legend.frameon": False,
})


def save_figure(fig: plt.Figure, path: Path, dpi: int = 160) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return path


def _map_aspect(ax, lat: pd.Series) -> None:
    ax.set_aspect(1 / np.cos(np.radians(np.nanmean(lat))))
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.grid(False)


def price_histograms(df: pd.DataFrame, fuels: Sequence[str], value: str = "prix") -> plt.Figure:
    """Petits multiples : distribution des prix, un panneau par carburant."""
    fuels = [f for f in fuels if (df["carburant"] == f).any()]
    n = max(len(fuels), 1)
    fig, axes = plt.subplots(1, n, figsize=(3.2 * n, 2.8), sharey=False, squeeze=False)
    for ax, fuel in zip(axes[0], fuels):
        vals = df.loc[df["carburant"] == fuel, value].dropna()
        ax.hist(vals, bins=40, color=SERIES[0], edgecolor=SURFACE, linewidth=0.5)
        ax.axvline(vals.median(), color=INK_2, linewidth=1, linestyle="--")
        ax.set_title(f"{fuel} (n = {len(vals):,})".replace(",", " "))
        ax.set_xlabel("€ / litre")
    axes[0][0].set_ylabel("nombre de stations")
    fig.suptitle("Distribution des prix retenus (tiret : médiane)", color=INK, fontsize=10)
    fig.tight_layout()
    return fig


def gradient_plot(gradient: pd.DataFrame, fuels: Sequence[str], value_label: str) -> plt.Figure:
    """Médiane par classe de concurrence ; une ligne par carburant (≤ 3)."""
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    fuels = list(fuels)[:3]
    for color, fuel in zip(SERIES, fuels):
        sub = gradient[gradient["carburant"] == fuel]
        if sub.empty:
            continue
        x = np.arange(len(sub))
        ax.plot(x, sub["mediane"], color=color, marker="o", markersize=6,
                markeredgecolor=SURFACE, markeredgewidth=2, label=fuel)
        ax.annotate(fuel, (x[-1], sub["mediane"].iloc[-1]), xytext=(6, 0),
                    textcoords="offset points", va="center", color=INK_2)
        ax.set_xticks(x, sub["classe_concurrence"].astype(str))
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.set_xlabel("nombre de concurrents (même carburant) à moins de 5 km")
    ax.set_ylabel(value_label)
    ax.legend(loc="best")
    ax.set_title("Prix et densité de concurrence locale")
    fig.tight_layout()
    return fig


def gap_map(df: pd.DataFrame, value: str = "ecart_dep", title: str = "",
            clip: float = 0.15) -> plt.Figure:
    """Carte des stations colorées par un écart signé (échelle divergente)."""
    d = df.dropna(subset=["lat", "lon", value])
    fig, ax = plt.subplots(figsize=(6.0, 6.0))
    norm = TwoSlopeNorm(vmin=-clip, vcenter=0.0, vmax=clip)
    sc = ax.scatter(d["lon"], d["lat"], c=d[value].clip(-clip, clip), cmap=DIVERGING, norm=norm,
                    s=3, linewidths=0)
    cb = fig.colorbar(sc, ax=ax, shrink=0.7)
    cb.set_label("écart en €/L (bleu : moins cher, rouge : plus cher)")
    cb.outline.set_visible(False)
    _map_aspect(ax, d["lat"])
    ax.set_title(title)
    return fig


def desert_map(deserts: pd.DataFrame, stations: pd.DataFrame, threshold_km: float) -> plt.Figure:
    """Communes en « désert » (centroïde à plus de d km d'une station)."""
    flag = f"desert_{threshold_km:g}km"
    fig, ax = plt.subplots(figsize=(6.0, 6.0))
    s = stations.dropna(subset=["lat", "lon"])
    ax.scatter(s["lon"], s["lat"], s=1, color=AXIS, linewidths=0, label="station-service")
    d = deserts[deserts[flag]]
    ax.scatter(d["centre_lon"], d["centre_lat"], s=5, color=SERIES[1], linewidths=0,
               label=f"commune à plus de {threshold_km:g} km d'une station")
    _map_aspect(ax, s["lat"])
    ax.legend(loc="lower left", markerscale=4)
    ax.set_title(f"Déserts de carburant (seuil {threshold_km:g} km, vol d'oiseau)")
    return fig


def family_bars(table: pd.DataFrame, value: str = "mediane", label: str = "") -> plt.Figure:
    """Barres horizontales : une valeur par famille d'enseigne (une seule série)."""
    t = table.sort_values(value)
    fig, ax = plt.subplots(figsize=(6.0, 0.5 * len(t) + 1.2))
    ax.barh(t["famille_enseigne"].astype(str), t[value], color=SERIES[0], height=0.6)
    for y, (v, n) in enumerate(zip(t[value], t["n"])):
        ax.annotate(f"{v:+.3f} (n={n})", (v, y), xytext=(4 if v >= 0 else -4, 0),
                    textcoords="offset points", va="center", ha="left" if v >= 0 else "right",
                    color=INK_2)
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(label)
    ax.set_title("Écart médian au prix départemental, par famille d'enseigne")
    fig.tight_layout()
    return fig


def income_bars(table: pd.DataFrame, value: str = "mediane", label: str = "") -> plt.Figure:
    """Écart de prix médian par quartile de niveau de vie communal."""
    t = table.dropna(subset=[value]).sort_values("quartile_revenu")
    fig, ax = plt.subplots(figsize=(6.0, 3.4))
    ax.bar(t["quartile_revenu"].astype(str), t[value], color=SERIES[0], width=0.65)
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.set_xlabel("quartile communal de niveau de vie médian (Filosofi 2023)")
    ax.set_ylabel(label)
    ax.set_title("Écart au prix médian départemental selon le revenu communal")
    fig.tight_layout()
    return fig


def boxplot_groupes(groupes: dict[str, np.ndarray], label: str, title: str) -> plt.Figure:
    """Boîtes à moustaches d'un écart, un groupe par boîte (ex. désert / hors désert).

    Les valeurs aberrantes ne sont pas dessinées : la boîte résume la dispersion,
    les points isolés sont signalés dans la légende du notebook.
    """
    noms = list(groupes)
    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    boites = ax.boxplot([groupes[n] for n in noms], showfliers=False, patch_artist=True,
                        widths=0.5, medianprops={"color": INK, "linewidth": 1.5})
    ax.set_xticks(range(1, len(noms) + 1), noms)
    for patch, couleur in zip(boites["boxes"], SERIES):
        patch.set_facecolor(couleur)
        patch.set_alpha(0.35)
        patch.set_edgecolor(couleur)
    for trait in boites["whiskers"] + boites["caps"]:
        trait.set_color(INK_2)
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.set_ylabel(label)
    ax.set_title(title)
    fig.tight_layout()
    return fig


def courbe_population_cumulee(distances: pd.Series, population: pd.Series, label: str,
                              titre: str, xmax: float = 15.0) -> plt.Figure:
    """Part des communes et des habitants vivant à moins de x km de la station (ou du supermarché).

    Les deux courbes divergent : l'écart entre elles dit que les communes éloignées sont peu peuplées.
    Les lignes pointillées marquent la médiane par commune et la médiane pondérée par la population.
    """
    d = distances.to_numpy(dtype=float)
    p = population.to_numpy(dtype=float)
    ok = np.isfinite(d) & np.isfinite(p) & (p > 0)
    d, p = d[ok], p[ok]
    o = np.argsort(d)
    d, p = d[o], p[o]
    x = np.linspace(0, xmax, 300)
    part_communes = np.searchsorted(d, x, side="right") / len(d)
    cumul_pop = np.cumsum(p)
    part_pop = np.array([cumul_pop[np.searchsorted(d, xi, side="right") - 1] if np.searchsorted(d, xi, side="right") > 0 else 0.0
                         for xi in x]) / p.sum()

    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    ax.plot(x, part_communes, color=SERIES[1], label="communes")
    ax.plot(x, part_pop, color=SERIES[0], label="habitants")
    ax.axhline(0.5, color=AXIS, linewidth=1)
    med_commune = float(np.median(d))
    med_pondere = float(d[np.searchsorted(cumul_pop / p.sum(), 0.5)])  # sur les données, pas sur la grille
    ax.axvline(med_commune, color=SERIES[1], linestyle="--", linewidth=1)
    ax.axvline(med_pondere, color=SERIES[0], linestyle="--", linewidth=1)
    ax.annotate(f"médiane par commune : {med_commune:.1f} km", (med_commune, 0.5), xytext=(6, -14),
                textcoords="offset points", color=INK_2, fontsize=8)
    ax.annotate(f"médiane par habitant : {med_pondere:.1f} km", (med_pondere, 0.5), xytext=(6, 8),
                textcoords="offset points", color=INK_2, fontsize=8)
    ax.set_xlim(0, xmax)
    ax.set_ylim(0, 1)
    ax.set_xlabel(label)
    ax.set_ylabel("part cumulée")
    ax.legend(loc="lower right")
    ax.set_title(titre)
    fig.tight_layout()
    return fig


def barres_ecart_tranches(tranches: pd.DataFrame, label: str, titre: str) -> plt.Figure:
    """Écart médian par tranche de distance, en divergent bleu (moins cher) / rouge (plus cher).

    ``tranches`` : une ligne par tranche, colonnes ``tranche`` (libellé) et ``mediane_c`` (centimes par litre).
    """
    t = tranches.reset_index(drop=True)
    norme = TwoSlopeNorm(vmin=min(-1.0, t["mediane_c"].min()), vcenter=0.0, vmax=max(1.0, t["mediane_c"].max()))
    couleurs = [DIVERGING(norme(v)) for v in t["mediane_c"]]
    fig, ax = plt.subplots(figsize=(6.0, 3.4))
    ax.bar(t["tranche"].astype(str), t["mediane_c"], color=couleurs, width=0.65)
    for x, v in enumerate(t["mediane_c"]):
        ax.annotate(f"{v:+.1f}", (x, v), xytext=(0, 4 if v >= 0 else -10), textcoords="offset points",
                    ha="center", color=INK_2)
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.set_ylim(min(0.0, t["mediane_c"].min()) - 1.8, max(0.0, t["mediane_c"].max()) + 1.8)  # place pour les étiquettes
    ax.set_xlabel(label)
    ax.set_ylabel("écart médian (c/L)")
    ax.set_title(titre)
    fig.tight_layout()
    return fig
