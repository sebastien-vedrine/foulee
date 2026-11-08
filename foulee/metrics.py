"""Indicateurs d'entraînement inspirés de Runalyze.

Toutes les fonctions sont pures (aucun accès disque/réseau) pour être testables.
Références :
- TRIMP de Banister (FC moyenne, coefficients homme/femme).
- Modèle impulsion-réponse : fatigue (ATL, 7 j), forme (CTL, 42 j), équilibre TSB = CTL - ATL.
- Monotonie et contrainte de Foster sur 7 jours.
- VDOT de Daniels & Gilbert ; VO2max « effective » à partir de la FC (approche Runalyze).
- Kilomètre-effort (distance + D+/100) pour le trail.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

# ---------------------------------------------------------------------------
# Types d'activités
# ---------------------------------------------------------------------------

HARD_LABELS = {"LACTATE_THRESHOLD", "VO2MAX", "ANAEROBIC_CAPACITY", "SPRINT", "SPEED", "THRESHOLD"}


def is_run(type_key: str | None) -> bool:
    return bool(type_key) and "run" in type_key


def is_trail_like(type_key: str | None) -> bool:
    return bool(type_key) and (type_key in ("trail_running", "hiking", "mountaineering") or "trail" in type_key)


def is_strength(type_key: str | None) -> bool:
    return type_key in ("strength_training", "indoor_strength", "functional_training")


def km_effort(distance_m: float | None, elev_gain: float | None) -> float:
    """Kilomètre-effort : 1 km + 1 km par 100 m de D+."""
    return (distance_m or 0) / 1000 + (elev_gain or 0) / 100


# ---------------------------------------------------------------------------
# Charge
# ---------------------------------------------------------------------------

def trimp(duration_s: float | None, avg_hr: float | None, hr_rest: float, hr_max: float, sex: str = "H") -> float | None:
    """TRIMP de Banister à partir de la FC moyenne."""
    if not duration_s or not avg_hr or hr_max <= hr_rest:
        return None
    x = (avg_hr - hr_rest) / (hr_max - hr_rest)
    x = min(max(x, 0.0), 1.05)
    a, b = (0.64, 1.92) if sex != "F" else (0.86, 1.67)
    return duration_s / 60 * x * a * math.exp(b * x)


def activity_load(act: dict, hr_rest: float, hr_max: float, sex: str = "H") -> float:
    """TRIMP de l'activité, avec repli sur la charge Garmin puis sur la durée."""
    t = trimp(act.get("duration_s"), act.get("avg_hr"), hr_rest, hr_max, sex)
    if t is not None:
        return t
    if act.get("garmin_load"):
        return float(act["garmin_load"])
    return (act.get("duration_s") or 0) / 60 * 0.8


def ewma(values: list[float], tau: float, seed: float | None = None) -> list[float]:
    k = 1 - math.exp(-1 / tau)
    v = seed if seed is not None else 0.0
    out = []
    for x in values:
        v = v + k * (x - v)
        out.append(v)
    return out


@dataclass
class LoadSeries:
    days: list[date]
    trimp: list[float]
    atl: list[float]
    ctl: list[float]

    @property
    def tsb(self) -> list[float]:
        return [c - a for a, c in zip(self.atl, self.ctl)]

    def index(self, d: date) -> int | None:
        if not self.days or d < self.days[0] or d > self.days[-1]:
            return None
        return (d - self.days[0]).days

    def at(self, d: date) -> dict:
        i = self.index(d)
        if i is None:
            return {"atl": 0.0, "ctl": 0.0, "tsb": 0.0, "acwr": None}
        atl, ctl = self.atl[i], self.ctl[i]
        return {"atl": atl, "ctl": ctl, "tsb": ctl - atl, "acwr": (atl / ctl) if ctl > 5 else None}


def load_series(daily: dict[date, float], start: date, end: date, atl_days: int = 7, ctl_days: int = 42) -> LoadSeries:
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    values = [daily.get(d, 0.0) for d in days]
    # Amorçage sur la moyenne des 4 premières semaines pour éviter une forme nulle au départ.
    seed = sum(values[:28]) / max(1, min(28, len(values))) if values else 0.0
    return LoadSeries(days, values, ewma(values, atl_days, seed), ewma(values, ctl_days, seed))


def monotony_strain(last7: list[float]) -> tuple[float | None, float]:
    """Monotonie (moyenne/écart-type) et contrainte (somme x monotonie) sur 7 jours."""
    if len(last7) < 7:
        return None, 0.0
    mean = sum(last7) / 7
    var = sum((x - mean) ** 2 for x in last7) / 7
    sd = math.sqrt(var)
    if sd < 1e-6:
        return None, sum(last7)
    mono = min(mean / sd, 10.0)
    return mono, sum(last7) * mono


# ---------------------------------------------------------------------------
# VO2max / VDOT (Daniels & Gilbert)
# ---------------------------------------------------------------------------

def vo2_at_speed(v_m_min: float) -> float:
    return -4.60 + 0.182258 * v_m_min + 0.000104 * v_m_min * v_m_min


def speed_at_vo2(vo2: float) -> float:
    """Vitesse (m/min) correspondant à une consommation d'O2 donnée."""
    a, b, c = 0.000104, 0.182258, -4.60 - vo2
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def pct_vo2max_for_duration(t_min: float) -> float:
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def vdot_from_race(dist_m: float, time_s: float) -> float:
    t = time_s / 60
    return vo2_at_speed(dist_m / t) / pct_vo2max_for_duration(t)


def race_time_from_vdot(vdot: float, dist_m: float) -> float:
    """Temps (s) prédit par la table de Daniels pour une distance plate."""
    lo, hi = dist_m / 10.0, dist_m / 1.0  # bornes : 10 m/s .. 1 m/s
    for _ in range(80):
        mid = (lo + hi) / 2
        if vdot_from_race(dist_m, mid) > vdot:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def effective_vo2max(act: dict, hr_max: float, factor: float = 1.0) -> float | None:
    """VO2max estimée sur une sortie à partir de l'allure (corrigée du dénivelé) et de la FC.

    %VO2max ≈ (%FCmax − 0.2812) / 0.7305 (relation utilisée par Runalyze).
    Distance équivalente plat : +10 m par mètre de D+, −4 m par mètre de D−.
    """
    if not is_run(act.get("type")):
        return None
    dur = act.get("moving_s") or act.get("duration_s")
    dist = act.get("distance_m")
    hr = act.get("avg_hr")
    if not dur or not dist or not hr or not hr_max or dur < 15 * 60 or dist < 2000 or dur > 3 * 3600:
        return None
    gain, loss = act.get("elev_gain") or 0, act.get("elev_loss") or 0
    if gain / (dist / 1000) > 60:  # trop raide : majoritairement de la marche
        return None
    hr_pct = hr / hr_max
    if hr_pct < 0.60 or hr_pct > 1.02:
        return None
    d_eq = max(dist + 10 * gain - 4 * loss, dist * 0.8)
    v = d_eq / (dur / 60)
    pct = (hr_pct - 0.2812) / 0.7305
    val = vo2_at_speed(v) / pct * factor
    return val if 20 <= val <= 90 else None


def vo2max_shape(points: list[tuple[date, float, float]], day: date, window: int = 30) -> float | None:
    """Moyenne pondérée par la durée (plafonnée à 1 h 30) des VO2max effectives des `window` derniers jours."""
    sel = [(v, min(w, 5400)) for d, v, w in points if day - timedelta(days=window) < d <= day]
    if not sel:
        return None
    if len(sel) >= 4:  # écarte les sorties atypiques (chaleur, capteur, terrain)
        med = median(v for v, _ in sel)
        sel = [(v, w) for v, w in sel if abs(v - med) <= 0.12 * med] or sel
    tot = sum(w for _, w in sel)
    return sum(v * w for v, w in sel) / tot if tot else None


# ---------------------------------------------------------------------------
# Endurance (inspirée de la « forme marathon » de Runalyze)
# ---------------------------------------------------------------------------

def endurance_targets(vo2max: float, race_kme: float) -> tuple[float, float]:
    """(km-effort hebdo cible, km-effort de sortie longue cible) pour une course."""
    scale = min(max((race_kme / 42.2) ** 0.4, 0.5), 1.5)
    week = min(max(vo2max ** 1.135 * scale, 20), 130)
    long_run = min(12 + 0.45 * race_kme, 45)
    return week, long_run


def endurance_shape(daily_kme: dict[date, float], long_runs: list[tuple[date, float]], day: date,
                    vo2max: float, race_kme: float) -> dict:
    target_week, target_long = endurance_targets(vo2max, race_kme)
    # Volume : 26 semaines, poids décroissant avec l'ancienneté
    num = den = 0.0
    for w in range(26):
        end = day - timedelta(days=7 * w)
        vol = sum(daily_kme.get(end - timedelta(days=i), 0.0) for i in range(7))
        weight = 26 - w
        num += vol * weight
        den += weight
    week_avg = num / den if den else 0.0
    # Sorties longues : 70 derniers jours
    pts = 0.0
    for d, kme in long_runs:
        age = (day - d).days
        if 0 <= age < 70 and kme >= 0.5 * target_long:
            pts += min(kme / target_long, 1.3) ** 2 * (1 - age / 70)
    long_score = min(pts / 2.0, 1.0)
    vol_score = min(week_avg / target_week, 1.0)
    return {
        "shape": 2 / 3 * vol_score + 1 / 3 * long_score,
        "week_avg": week_avg, "target_week": target_week,
        "long_score": long_score, "target_long": target_long,
    }


# ---------------------------------------------------------------------------
# Pronostics
# ---------------------------------------------------------------------------

TECHNICITY_FACTORS = {1: 1.10, 2: 1.20, 3: 1.30, 4: 1.42, 5: 1.55}
TECHNICITY_LABELS = {1: "Roulant", 2: "Peu technique", 3: "Technique", 4: "Très technique", 5: "Alpin"}


def equivalent_km(dist_km: float, elev_m: float, kind: str) -> float:
    if kind == "trail":
        return dist_km + elev_m / 100
    return dist_km + elev_m * 4 / 1000


def predict_race(vdot: float, dist_km: float, elev_m: float, kind: str, technicity: int = 3,
                 shape: float = 1.0, personal_factor: float = 1.0) -> float:
    """Temps prédit (s). Ajuste la VDOT selon l'endurance au-delà de 15 km-équivalent."""
    eq = equivalent_km(dist_km, elev_m, kind)
    adj = vdot
    if eq > 15:
        adj = vdot * (1 - 0.10 * (1 - min(max(shape, 0), 1)) * min(1.0, (eq - 15) / 27))
    if eq <= 42.195:
        t = race_time_from_vdot(adj, eq * 1000)
    else:
        t = race_time_from_vdot(adj, 42195) * (eq / 42.195) ** 1.15
    if kind == "trail":
        t *= TECHNICITY_FACTORS.get(int(technicity or 3), 1.30) * personal_factor
    return t


def base_trail_time(vdot: float, dist_km: float, elev_m: float, shape: float, technicity: int) -> float:
    return predict_race(vdot, dist_km, elev_m, "trail", technicity, shape, 1.0)


# ---------------------------------------------------------------------------
# Zones et allures
# ---------------------------------------------------------------------------

ZONE_NAMES = ["Z1 Récupération", "Z2 Endurance", "Z3 Tempo", "Z4 Seuil", "Z5 VO2max"]


def hr_zones(hr_max: float, lthr: float | None = None, method: str = "auto",
             hr_rest: float | None = None) -> list[tuple[str, int, int]]:
    """Zones FC.

    auto : %FC seuil (Friel) si le seuil est connu, sinon %FC de réserve (Karvonen).
    lthr : %FC seuil ; reserve : %FC de réserve ; fcmax : %FCmax (zones Garmin par défaut).
    """
    if method in ("auto", "lthr") and lthr:
        b = [0.70, 0.81, 0.90, 0.94, 1.00]
        bounds = [x * lthr for x in b] + [hr_max]
    elif method in ("auto", "reserve") and hr_rest:
        b = [0.50, 0.60, 0.70, 0.80, 0.90, 1.00]
        bounds = [hr_rest + x * (hr_max - hr_rest) for x in b]
    else:
        b = [0.50, 0.60, 0.70, 0.80, 0.90, 1.00]
        bounds = [x * hr_max for x in b]
    out = []
    for i in range(5):
        lo = round(bounds[i])
        hi = round(bounds[i + 1]) - 1 if i < 4 else round(hr_max)
        out.append((ZONE_NAMES[i], lo, hi))
    return out


def pace_str(v_m_min: float | None) -> str:
    if not v_m_min or v_m_min <= 0:
        return "–"
    s = 1000 / v_m_min * 60
    return f"{int(s // 60)}:{int(round(s % 60)):02d}/km".replace(":60", ":59")


def training_paces(vdot: float) -> dict[str, tuple[float, float]]:
    """Allures d'entraînement (m/min, bornes lente/rapide) selon Daniels."""
    def v(p):
        return speed_at_vo2(vdot * p)
    return {
        "Endurance (E)": (v(0.62), v(0.70)),
        "Marathon (M)": (v(0.79), v(0.82)),
        "Seuil (T)": (v(0.86), v(0.89)),
        "Intervalles (I)": (v(0.96), v(0.99)),
    }


# ---------------------------------------------------------------------------
# Aides
# ---------------------------------------------------------------------------

def fr(x: float | None, d: int = 1) -> str:
    """Nombre au format français : virgule décimale, espace fine pour les milliers."""
    if x is None:
        return "–"
    s = f"{x:,.{d}f}"
    return s.replace(",", "\u202f").replace(".", ",")


def fmt_duration(seconds: float | None, with_seconds: bool = False) -> str:
    if seconds is None:
        return "–"
    s = int(round(seconds))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    if with_seconds and h == 0:
        return f"{m}:{sec:02d}"
    if with_seconds:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{h} h {m:02d}" if h else f"{m} min"


def robust_hr_max(max_hrs: list[float]) -> float | None:
    vals = sorted(v for v in max_hrs if v and 120 < v < 230)
    if not vals:
        return None
    # 2e valeur la plus haute pour écarter un artefact capteur isolé
    return vals[-2] if len(vals) > 3 else vals[-1]


def safe_median(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return median(vals) if vals else None
