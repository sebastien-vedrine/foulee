"""Progression : comparaison des sorties d'un même type et meilleurs temps.

Chaque sortie de course est rangée dans un type de séance (footing, tempo, seuil, VO2max, sortie longue)
d'après l'effet d'entraînement principal calculé par la montre, sinon d'après l'intensité déduite par Foulée.

Mesures par sortie : FC moyenne, allure ajustée à la pente (calculée par Garmin) et efficacité,
c'est-à-dire la distance parcourue par battement cardiaque (vitesse ajustée / FC moyenne). À FC égale,
une efficacité qui monte veut dire que tu cours plus vite : c'est le signe le plus fiable de progrès
aérobie, à comparer entre séances du même type (la chaleur et la durée la font aussi varier).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean

from . import metrics as M

CATEGORIES = {
    "footing": "Footing",
    "tempo": "Tempo",
    "seuil": "Seuil",
    "vo2": "VO2max",
    "longue": "Sortie longue",
}
CATEGORY_HINTS = {
    "footing": "sorties d'endurance fondamentale et de récupération",
    "tempo": "sorties soutenues, effet principal « tempo » sur la montre",
    "seuil": "sorties au seuil lactique",
    "vo2": "fractionné court et intense (VO2max, capacité anaérobie, vitesse)",
    "longue": "sorties de plus de 1 h 40 à allure d'endurance, ou de plus de 2 h 30",
}
HARD_VO2 = {"VO2MAX", "ANAEROBIC_CAPACITY", "SPEED", "SPRINT"}
MIN_DURATION_S = 15 * 60
MIN_HR = 100          # en dessous, FC moyenne de course presque toujours faussée (capteur décroché)
COMPARE_DAYS = 120
COMPARE_MAX = 10
RECENT_DAYS = 42
RECORDS = [("1 km", "best_1000", 1000), ("5 km", "best_5000", 5000), ("10 km", "best_10000", 10000),
           ("Semi-marathon", "best_21098", 21097.5), ("Marathon", "best_42195", 42195)]


def category(a: dict) -> str | None:
    """Type de séance d'une sortie de course, None pour les autres activités et les sorties trop courtes."""
    t = a.get("type") or ""
    if not (M.is_run(t) or M.is_trail_like(t)) or a.get("is_race"):
        return None
    dur = a.get("moving_s") or a.get("duration_s") or 0
    if dur < MIN_DURATION_S:
        return None
    label = (a.get("te_label") or "").upper()
    if dur >= 150 * 60:
        return "longue"
    if label in HARD_VO2:
        return "vo2"
    if label == "LACTATE_THRESHOLD":
        return "seuil"
    if label == "TEMPO":
        return "tempo"
    if dur >= 100 * 60:
        return "longue"
    if label in ("AEROBIC_BASE", "RECOVERY"):
        return "footing"
    intensity = a.get("intensity")
    if intensity == "hard":
        return "vo2" if a.get("family") == "vo2" else "seuil"
    if intensity == "long":
        return "longue"
    return "footing"


def adjusted_speed(a: dict) -> float | None:
    """Vitesse ajustée à la pente en m/min (Garmin), sinon vitesse réelle si le parcours est presque plat."""
    if a.get("gap_speed"):
        return a["gap_speed"] * 60
    dist = a.get("distance_m") or 0
    dur = a.get("moving_s") or a.get("duration_s") or 0
    if dist <= 0 or dur <= 0 or (a.get("elev_gain") or 0) / (dist / 1000) > 10:
        return None
    return dist / dur * 60


@dataclass
class RunPoint:
    id: int
    day: date
    category: str
    name: str
    hr: float | None
    speed: float | None          # m/min, ajustée à la pente
    duration_s: float
    distance_m: float

    @property
    def efficiency(self) -> float | None:
        """Mètres parcourus par battement cardiaque."""
        if self.speed and self.hr:
            return self.speed / self.hr
        return None


def points(activities: list[dict]) -> list[RunPoint]:
    out = []
    for a in activities:
        cat = category(a)
        if cat is None:
            continue
        hr = a.get("avg_hr") if (a.get("avg_hr") or 0) >= MIN_HR else None
        out.append(RunPoint(a["id"], date.fromisoformat(a["date"]), cat, a.get("name") or "", hr,
                            adjusted_speed(a), a.get("moving_s") or a.get("duration_s") or 0, a.get("distance_m") or 0))
    out.sort(key=lambda p: (p.day, p.id))
    return out


def signed(x: float, d: int = 1) -> str:
    """Nombre signé au format français (+3,2 ; −1,5)."""
    return ("+" if x >= 0 else "−") + M.fr(abs(x), d)


def _avg(vals) -> float | None:
    vals = [v for v in vals if v is not None]
    return mean(vals) if vals else None


@dataclass
class Comparison:
    point: RunPoint
    peers: list[RunPoint]
    hr: float | None
    speed: float | None
    efficiency: float | None
    rank: int | None              # rang de l'efficacité de la sortie parmi elle-même et ses pairs (1 = meilleure)
    ranked: int

    @property
    def label(self) -> str:
        return CATEGORIES[self.point.category]

    @property
    def hr_delta(self) -> float | None:
        return self.point.hr - self.hr if self.point.hr and self.hr else None

    @property
    def pace_delta_s(self) -> float | None:
        """Écart d'allure en s/km (négatif = plus rapide que d'habitude)."""
        if self.point.speed and self.speed:
            return 60000 / self.point.speed - 60000 / self.speed
        return None

    @property
    def eff_delta_pct(self) -> float | None:
        e = self.point.efficiency
        return (e / self.efficiency - 1) * 100 if e and self.efficiency else None


def compare(pts: list[RunPoint], activity_id: int, days: int = COMPARE_DAYS, n: int = COMPARE_MAX) -> Comparison | None:
    """Compare une sortie aux N précédentes du même type sur les derniers mois."""
    target = next((p for p in pts if p.id == activity_id), None)
    if target is None:
        return None
    lo = target.day - timedelta(days=days)
    peers = [p for p in pts if p.category == target.category and p.id != target.id and lo <= p.day <= target.day
             and (p.day, p.id) < (target.day, target.id)][-n:]
    if len(peers) < 2:
        return None
    effs = [p.efficiency for p in peers if p.efficiency]
    rank = None
    if target.efficiency and effs:
        rank = 1 + sum(1 for e in effs if e > target.efficiency)
    return Comparison(target, peers, _avg(p.hr for p in peers), _avg(p.speed for p in peers), _avg(effs) if effs else None,
                      rank, len(effs) + 1)


@dataclass
class Trend:
    category: str
    recent: list[RunPoint]
    before: list[RunPoint]

    @property
    def label(self) -> str:
        return CATEGORIES[self.category]

    def _m(self, pts, attr):
        return _avg(getattr(p, attr) for p in pts)

    @property
    def ready(self) -> bool:
        return (len([p for p in self.recent if p.efficiency]) >= 2 and len([p for p in self.before if p.efficiency]) >= 2)

    @property
    def eff_pct(self) -> float | None:
        a, b = self._m(self.recent, "efficiency"), self._m(self.before, "efficiency")
        return (a / b - 1) * 100 if self.ready and a and b else None

    @property
    def hr(self) -> tuple[float | None, float | None]:
        return self._m(self.before, "hr"), self._m(self.recent, "hr")

    @property
    def speed(self) -> tuple[float | None, float | None]:
        return self._m(self.before, "speed"), self._m(self.recent, "speed")

    def sentence(self) -> str:
        pct = self.eff_pct
        if pct is None:
            return ""
        hr_now = self.hr[1]
        e_before, e_now = self._m(self.before, "efficiency"), self._m(self.recent, "efficiency")
        gain = 60000 / (e_before * hr_now) - 60000 / (e_now * hr_now) if hr_now else 0
        if abs(pct) < 1.5:
            return f"{self.label} : efficacité stable ({signed(pct)} %)."
        way = "plus vite" if gain > 0 else "moins vite"
        return (f"{self.label} : efficacité {signed(pct)} %, soit environ {abs(gain):.0f} s/km {way} "
                f"à {hr_now:.0f} bpm qu'avant.")


def trend(pts: list[RunPoint], cat: str, today: date, recent_days: int = RECENT_DAYS,
          before_days: int = 3 * RECENT_DAYS) -> Trend:
    """Dernières semaines comparées à la période précédente (par défaut 6 semaines vs les 18 d'avant)."""
    cut = today - timedelta(days=recent_days)
    lo = cut - timedelta(days=before_days)
    mine = [p for p in pts if p.category == cat]
    return Trend(cat, [p for p in mine if cut < p.day <= today], [p for p in mine if lo < p.day <= cut])


def rolling_efficiency(pts: list[RunPoint], cat: str, window: int = RECENT_DAYS) -> list[tuple[date, float]]:
    """Moyenne glissante de l'efficacité sur la fenêtre, à chaque sortie du type."""
    mine = [p for p in pts if p.category == cat and p.efficiency]
    out = []
    for p in mine:
        win = [q.efficiency for q in mine if p.day - timedelta(days=window) < q.day <= p.day]
        if len(win) >= 2:
            out.append((p.day, mean(win)))
    return out


@dataclass
class Record:
    label: str
    distance_m: float
    best_s: float | None = None
    best_day: date | None = None
    best_name: str = ""
    recent_s: float | None = None
    recent_day: date | None = None

    @property
    def gap_pct(self) -> float | None:
        if self.best_s and self.recent_s:
            return (self.recent_s / self.best_s - 1) * 100
        return None


def records(activities: list[dict], today: date, recent_days: int = 90) -> list[Record]:
    """Meilleurs temps sur 1 km, 5 km… extraits des sorties (meilleur passage mesuré par la montre)."""
    out = []
    for name, key, dist in RECORDS:
        rec = Record(name, dist)
        for a in activities:
            t = a.get(key)
            if not t or t <= 0:
                continue
            d = date.fromisoformat(a["date"])
            if rec.best_s is None or t < rec.best_s:
                rec.best_s, rec.best_day, rec.best_name = t, d, a.get("name") or ""
            if (today - d).days <= recent_days and (rec.recent_s is None or t < rec.recent_s):
                rec.recent_s, rec.recent_day = t, d
        if rec.best_s:
            out.append(rec)
    return out


def best_by_month(activities: list[dict], key: str) -> list[tuple[date, float]]:
    """Meilleur temps du mois sur une distance (pour le graphique)."""
    best: dict[date, float] = {}
    for a in activities:
        t = a.get(key)
        if not t or t <= 0:
            continue
        d = date.fromisoformat(a["date"])
        m = date(d.year, d.month, 15)
        if m not in best or t < best[m]:
            best[m] = t
    return sorted(best.items())
