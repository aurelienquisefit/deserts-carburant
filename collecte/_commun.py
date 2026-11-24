"""Initialisation commune aux scripts : rend ``src/`` importable sans installation
et configure la journalisation (console + fichier ``logs/pipeline.log``)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def setup_logging(name: str = "carburants") -> logging.Logger:
    (ROOT / "logs").mkdir(exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(name)s : %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt,
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(ROOT / "logs" / "pipeline.log", encoding="utf-8")])
    return logging.getLogger(name)
