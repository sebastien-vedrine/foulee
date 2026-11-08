"""Modèles de données partagés."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .metrics import equivalent_km


@dataclass
class Race:
    id: int | None
    name: str
    date: date
    distance_km: float
    elevation_m: float = 0.0
    kind: str = "trail"            # "route" ou "trail"
    priority: str = "A"            # A = objectif, B = préparation, C = plaisir
    technicity: int = 3            # 1..5 (trail)
    goal_s: int | None = None
    result_s: int | None = None
    notes: str = ""

    @property
    def kme(self) -> float:
        return equivalent_km(self.distance_km, self.elevation_m, self.kind)


@dataclass
class ActRec:
    """Activité résumée telle que l'utilise le coach."""
    date: date
    type: str
    name: str = ""
    duration_s: float = 0.0
    kme: float = 0.0
    trimp: float = 0.0
    intensity: str = "easy"        # hard | long | strength | easy | race
    family: str | None = None      # vo2 | seuil | cotes | allure (séances dures)
    simulated: bool = False
    meta: dict = field(default_factory=dict)
