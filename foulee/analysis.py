"""Assemble les données stockées en indicateurs prêts à afficher."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median

from . import metrics as M
from .coach import CoachContext, Phase, Suggestion, compute_phase, plan_days
from .config import Settings
from .db import Database
from .form import FormReport, assess as assess_form
from .models import ActRec, Race
from .readiness import Readiness, compute as compute_readiness


def classify(a: dict, hr_max: float, zones) -> tuple[str, str | None]:
    """Intensité d'une activité pour le coach : (hard|long|strength|easy|race, famille)."""
    t = a.get("type") or ""
    if M.is_strength(t):
        return "strength", None
    if a.get("is_race"):
        return "race", None
    dur = a.get("duration_s") or 0
    kme = M.km_effort(a.get("distance_m"), a.get("elev_gain"))
    label = (a.get("te_label") or "").upper()
    high_zone = (a.get("z4") or 0) + (a.get("z5") or 0)
    run_like = M.is_run(t) or M.is_trail_like(t)
    if run_like and (label in M.HARD_LABELS or (a.get("te_anaero") or 0) >= 2.0 or high_zone >= 10 * 60):
        if label == "LACTATE_THRESHOLD":
            fam = "seuil"
        elif M.is_trail_like(t) or (a.get("elev_gain") or 0) / max(kme, 1) > 25:
            fam = "cotes"
        else:
            fam = "vo2" if label in ("VO2MAX", "ANAEROBIC_CAPACITY", "SPRINT", "SPEED") else "seuil"
        return "hard", fam
    if run_like and (dur >= 100 * 60 or kme >= 20):
        return "long", None
    return "easy", None


@dataclass
class RaceView:
    race: Race
    days_to: int
    prognosis_s: float | None
    shape: dict | None
    phase: str


@dataclass
class Analysis:
    settings: Settings
    today: date
    activities: list[dict] = field(default_factory=list)
    daily: dict = field(default_factory=dict)
    races: list[Race] = field(default_factory=list)
    hr_max: float = 185
    hr_rest: float = 55
    lthr: float | None = None
    zones: list = field(default_factory=list)
    load: M.LoadSeries | None = None
    vo2_points: list = field(default_factory=list)
    vo2max: float | None = None
    vo2max_garmin: float | None = None
    paces: dict | None = None
    readiness: Readiness | None = None
    readiness_hist: dict = field(default_factory=dict)
    form: FormReport | None = None
    phase: Phase | None = None
    plan: list[Suggestion] = field(default_factory=list)
    race_views: list[RaceView] = field(default_factory=list)
    personal_trail_factor: float = 1.0
    monotony: float | None = None
    strain: float = 0.0
    snapshots: dict = field(default_factory=dict)
    last_sync: str | None = None
    hr_max_auto: bool = True

    @property
    def has_data(self) -> bool:
        return bool(self.activities or self.daily)

    @property
    def suggestion(self) -> Suggestion | None:
        return self.plan[0] if self.plan else None

    def load_at(self, d: date) -> dict:
        return self.load.at(d) if self.load else {"atl": 0, "ctl": 0, "tsb": 0, "acwr": None}

    def daily_kme(self) -> dict[date, float]:
        out: dict[date, float] = {}
        for a in self.activities:
            if M.is_run(a["type"]) or M.is_trail_like(a["type"]):
                d = date.fromisoformat(a["date"])
                out[d] = out.get(d, 0.0) + a["kme"]
        return out

    def long_runs(self) -> list[tuple[date, float]]:
        return [(date.fromisoformat(a["date"]), a["kme"]) for a in self.activities
                if (M.is_run(a["type"]) or M.is_trail_like(a["type"])) and a["kme"] >= 10]

    def endurance_for(self, race_kme: float, day: date | None = None, vo2: float | None = None) -> dict | None:
        vo2 = vo2 or self.vo2max
        if not vo2:
            return None
        return M.endurance_shape(self.daily_kme(), self.long_runs(), day or self.today, vo2, race_kme)

    def vo2_at(self, d: date) -> float | None:
        return M.vo2max_shape(self.vo2_points, d)


def build(db: Database, settings: Settings, today: date | None = None) -> Analysis:
    today = today or date.today()
    an = Analysis(settings, today)
    an.last_sync = db.meta("last_sync")
    acts = db.activities()
    daily_rows = db.daily()
    an.daily = {date.fromisoformat(r["date"]): r for r in daily_rows}
    an.races = db.races()
    an.snapshots = {k: db.snapshot(k) for k in ("training_status", "race_predictions", "lthr")}

    # --- Physiologie ----------------------------------------------------------------
    recent = [a for a in acts if a["date"] >= (today - timedelta(days=365)).isoformat()]
    auto_max = M.robust_hr_max([a.get("max_hr") for a in recent]) or 185
    an.hr_max_auto = not settings.hr_max
    an.hr_max = float(settings.hr_max or auto_max)
    rhr_vals = [r["rhr"] for d, r in an.daily.items() if r.get("rhr") and (today - d).days <= 30]
    an.hr_rest = float(settings.hr_rest or (median(rhr_vals) if rhr_vals else 55))
    garmin_lthr = an.snapshots.get("lthr")
    an.lthr = float(settings.lthr) if settings.lthr else (float(garmin_lthr) if garmin_lthr else None)
    an.zones = M.hr_zones(an.hr_max, an.lthr, settings.zone_method, an.hr_rest)

    # --- Activités enrichies -----------------------------------------------------------
    for a in acts:
        a["kme"] = M.km_effort(a.get("distance_m"), a.get("elev_gain"))
        a["trimp"] = M.activity_load(a, an.hr_rest, an.hr_max, settings.sex)
        a["vo2eff"] = M.effective_vo2max(a, an.hr_max, settings.vo2_factor)
        a["intensity"], a["family"] = classify(a, an.hr_max, an.zones)
    an.activities = acts
    garmin_vo2 = [a["vo2max_garmin"] for a in acts if a.get("vo2max_garmin")]
    an.vo2max_garmin = garmin_vo2[-1] if garmin_vo2 else None

    # --- Charge -----------------------------------------------------------------------
    daily_trimp: dict[date, float] = {}
    for a in acts:
        d = date.fromisoformat(a["date"])
        daily_trimp[d] = daily_trimp.get(d, 0.0) + a["trimp"]
    first = min([*daily_trimp.keys(), *an.daily.keys()], default=today)
    first = min(first, today - timedelta(days=1))
    an.load = M.load_series(daily_trimp, first, today)
    an.monotony, an.strain = M.monotony_strain(an.load.trimp[-7:])

    # --- VO2max effective ------------------------------------------------------------------
    an.vo2_points = [(date.fromisoformat(a["date"]), a["vo2eff"], a.get("moving_s") or a.get("duration_s") or 0)
                     for a in acts if a.get("vo2eff")]
    an.vo2max = an.vo2_at(today)
    if an.vo2max is None and an.vo2_points:
        an.vo2max = M.vo2max_shape(an.vo2_points, today, window=120)
    if an.vo2max is None and an.vo2max_garmin:
        an.vo2max = an.vo2max_garmin
    an.paces = M.training_paces(an.vo2max) if an.vo2max else None

    # --- Disponibilité ------------------------------------------------------------------
    for i in range(30):
        d = today - timedelta(days=i)
        if d in an.daily:
            an.readiness_hist[d] = compute_readiness(d, an.daily)
    an.readiness = an.readiness_hist.get(today) or compute_readiness(today, an.daily)
    trained = {date.fromisoformat(a["date"]) for a in acts
               if a["trimp"] >= 20 or a["intensity"] in ("hard", "long", "strength", "race")}
    consecutive, d = 0, today - timedelta(days=1)
    while d in trained:
        consecutive += 1
        d -= timedelta(days=1)
    an.form = assess_form(today, an.readiness, an.readiness_hist, an.daily, an.load_at(today), consecutive,
                          feminine=settings.sex == "F")

    # --- Courses : facteur trail personnel puis pronostics -----------------------------
    factors = []
    for r in an.races:
        if r.result_s and r.kind == "trail" and r.date <= today:
            vo2 = an.vo2_at(r.date) or M.vo2max_shape(an.vo2_points, r.date, 90)
            if vo2:
                shape = an.endurance_for(r.kme, r.date, vo2)
                base = M.predict_race(vo2, r.distance_km, r.elevation_m, "trail", r.technicity,
                                      shape["shape"] if shape else 0.8, 1.0)
                factors.append(r.result_s / base)
    if factors:
        an.personal_trail_factor = max(0.75, min(1.5, median(factors)))
    for r in an.races:
        days = (r.date - today).days
        vo2 = an.vo2max if days >= 0 else (an.vo2_at(r.date) or an.vo2max)
        shape = an.endurance_for(r.kme, today if days >= 0 else r.date, vo2) if vo2 else None
        prog = None
        if vo2:
            prog = M.predict_race(vo2, r.distance_km, r.elevation_m, r.kind, r.technicity,
                                  shape["shape"] if shape else 0.8,
                                  an.personal_trail_factor if r.kind == "trail" else 1.0)
        as_target = Race(r.id, r.name, r.date, r.distance_km, r.elevation_m, r.kind, "A", r.technicity)
        label = compute_phase(today, [as_target]).label if days >= 0 else "Passée"
        an.race_views.append(RaceView(r, days, prog, shape, label))

    # --- Coach --------------------------------------------------------------------------
    history = [ActRec(date.fromisoformat(a["date"]), a["type"], a["name"], a.get("duration_s") or 0, a["kme"],
                      a["trimp"], a["intensity"], a["family"]) for a in acts]
    an.phase = compute_phase(today, an.races)
    ctx = CoachContext(today, settings, history, an.races, an.readiness if an.readiness.score is not None else None,
                       an.load_at(today), an.zones, an.vo2max, an.paces)
    an.plan = plan_days(ctx, 7)
    return an
