"""Réglages utilisateur, stockés en JSON dans le dossier de données."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from .paths import config_path

WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

# Minutes disponibles par jour (0 = lundi). Modifiable dans Réglages.
DEFAULT_AVAILABILITY = {"0": 60, "1": 0, "2": 80, "3": 0, "4": 80, "5": 240, "6": 240}


@dataclass
class Settings:
    garmin_email: str = ""
    sex: str = "H"                 # "H" ou "F" (coefficients TRIMP)
    hr_max: int | None = None      # None = déduit des activités
    hr_rest: int | None = None     # None = médiane FC repos Garmin (30 j)
    lthr: int | None = None        # None = seuil lactique Garmin s'il existe
    zone_method: str = "auto"      # auto | lthr | reserve | fcmax
    availability: dict = field(default_factory=lambda: dict(DEFAULT_AVAILABILITY))
    strength_per_week: int = 2
    runs_per_week: int = 0         # 0 = automatique (selon la phase et l'habitude récente)
    long_run_day: int = -1         # -1 = automatique (jour le plus disponible du week-end)
    vo2_factor: float = 1.0        # facteur de correction de la VO2max effective
    history_days: int = 120        # historique santé récupéré à la première synchro
    auto_sync: bool = True
    demo: bool = False

    def avail(self, weekday: int) -> int:
        return int(self.availability.get(str(weekday), 0) or 0)

    def save(self) -> None:
        config_path().write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls) -> "Settings":
        p = config_path()
        if not p.exists():
            return cls()
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in raw.items() if k in known})
        merged = dict(DEFAULT_AVAILABILITY)
        merged.update({str(k): int(v or 0) for k, v in (s.availability or {}).items()})
        s.availability = merged
        return s
