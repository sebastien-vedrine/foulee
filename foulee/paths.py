"""Emplacements des fichiers de l'application (données, jetons Garmin, ressources)."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("FOULEE_HOME")
    if override:
        p = Path(override)
    elif os.environ.get("APPDATA"):
        p = Path(os.environ["APPDATA"]) / "Foulee"
    else:
        p = Path.home() / ".foulee"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path(demo: bool = False) -> Path:
    return data_dir() / ("demo.sqlite" if demo else "foulee.sqlite")


def token_dir() -> Path:
    p = data_dir() / "garmin"
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return data_dir() / "config.json"


def resource(rel: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent.parent
    return root / rel
