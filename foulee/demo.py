"""Données fictives réalistes pour essayer l'application sans compte Garmin."""
from __future__ import annotations

import json
import math
import random
from datetime import date, datetime, timedelta

from . import metrics as M
from .db import Database
from .models import Race


def _speed_for(vo2max: float, hr_pct: float) -> float:
    pct = (hr_pct - 0.2812) / 0.7305
    return M.speed_at_vo2(vo2max * pct)  # m/min


def generate(db: Database, today: date | None = None, days: int = 240, seed: int = 7) -> None:
    rnd = random.Random(seed)
    today = today or date.today()
    start = today - timedelta(days=days)
    hr_max, hr_rest = 188, 47
    past_race = Race(None, "Trail des Crêtes", today - timedelta(days=63), 42, 1900, "trail", "A", 3, None, None, "")
    races = [
        past_race,
        Race(None, "Trail du Val de Loing", today + timedelta(days=27), 25, 850, "trail", "B", 2, None, None, ""),
        Race(None, "Ultra des Volcans", today + timedelta(days=76), 62, 3100, "trail", "A", 3, 11 * 3600, None,
             "Objectif : finir sous 11 h"),
        Race(None, "10 km de Vincennes", today + timedelta(days=150), 10, 30, "route", "C", 1, None, None, ""),
    ]
    acts, aid = [], 10 ** 9
    hrv_base, fatigue = 58.0, 0.0
    daily_rows = []
    d = start
    while d <= today:
        wd = d.weekday()
        progress = (d - start).days / days
        vo2 = 46.5 + 3.0 * progress + rnd.gauss(0, 0.6)
        week_in_block = ((d - start).days // 7) % 4  # 3 semaines de charge, 1 de récup
        recovery_week = week_in_block == 3
        days_after_race = (d - past_race.date).days
        session = None
        if 0 < days_after_race <= 8:
            session = ("easy", 35) if days_after_race in (4, 6, 8) else None
        elif d == past_race.date:
            session = ("race", 0)
        elif d == today:
            session = None  # la journée n'est pas encore faite
        elif wd == 0:
            session = ("easy", 50) if rnd.random() < 0.85 else None
        elif wd == 2:
            session = ("hard", 70) if not recovery_week else ("easy", 50)
        elif wd == 4:
            session = ("strength", 40) if rnd.random() < 0.6 else ("easy", 55)
        elif wd == 5:
            session = ("long", int((110 + 70 * progress) * (0.7 if recovery_week else 1.0)))
        elif wd == 6:
            session = ("strength", 35) if rnd.random() < 0.5 else ("easy", 60)
        trimp_day = 0.0
        if session:
            kind, minutes = session
            start_dt = datetime(d.year, d.month, d.day, 8 if wd >= 5 else 12, 15)
            a = {"activityId": aid, "startTimeLocal": start_dt.strftime("%Y-%m-%d %H:%M:%S")}
            aid += 1
            if kind == "strength":
                a.update(activityType={"typeKey": "strength_training"}, activityName="Renforcement",
                         duration=minutes * 60, averageHR=102 + rnd.randint(-5, 6), maxHR=138)
            else:
                if kind == "race":
                    minutes = int(6.9 * 60 + rnd.randint(-10, 10))
                    hr_pct, gain_per_km, name, typ = 0.83, 45, past_race.name, "trail_running"
                    dist_km_eq = None
                elif kind == "hard":
                    hr_pct, gain_per_km, typ = 0.84, rnd.choice([10, 35]), "running"
                    name = rnd.choice(["Fractionné seuil", "VO2max 5×4 min", "Fractionné en côte"])
                    if "côte" in name:
                        typ, gain_per_km = "trail_running", 45
                elif kind == "long":
                    hr_pct, gain_per_km, typ, name = 0.74, rnd.choice([30, 45, 60]), "trail_running", "Sortie longue trail"
                else:
                    hr_pct, gain_per_km, typ, name = 0.71 + rnd.gauss(0, 0.015), rnd.choice([5, 10, 25]), "running", "Footing"
                if kind == "race":
                    dist = 42000.0
                    gain = float(past_race.elevation_m)
                else:
                    v = _speed_for(vo2 * rnd.uniform(0.96, 1.04), hr_pct)  # m/min (équivalent plat)
                    d_eq = v * minutes
                    # d_eq = dist + 10 gain - 4 loss, gain = loss = g*dist/1000
                    dist = d_eq / (1 + 6 * gain_per_km / 1000)
                    gain = gain_per_km * dist / 1000
                avg_hr = round(hr_max * hr_pct + rnd.gauss(0, 2))
                split = {"hard": (0.10, 0.35, 0.20, 0.25, 0.10), "long": (0.10, 0.68, 0.18, 0.04, 0.0),
                         "race": (0.05, 0.35, 0.40, 0.18, 0.02)}.get(kind, (0.15, 0.72, 0.11, 0.02, 0.0))
                zones = {f"hrTimeInZone_{i + 1}": minutes * 60 * f for i, f in enumerate(split)}
                a.update(activityType={"typeKey": typ}, activityName=name, distance=dist, duration=minutes * 60,
                         movingDuration=minutes * 60 * 0.98, elevationGain=gain, elevationLoss=gain * rnd.uniform(0.95, 1.05),
                         averageHR=avg_hr, maxHR=min(hr_max, avg_hr + rnd.randint(12, 25)),
                         averageSpeed=dist / (minutes * 60), aerobicTrainingEffect=3.6 if kind in ("hard", "long") else 2.8,
                         anaerobicTrainingEffect=2.4 if kind == "hard" else 0.4,
                         trainingEffectLabel="LACTATE_THRESHOLD" if kind == "hard" and "seuil" in name else
                         ("VO2MAX" if kind == "hard" else "AEROBIC_BASE"),
                         vO2MaxValue=round(vo2 + 1.2), averageRunningCadenceInStepsPerMinute=172 + rnd.randint(-4, 4),
                         **zones)
                if kind == "race":
                    a["eventType"] = {"typeKey": "race"}
            from .garmin_sync import parse_activity
            row = parse_activity(a)
            acts.append(row)
            trimp_day = M.activity_load(row, hr_rest, hr_max)
        # Santé : la fatigue de la veille fait baisser la VFC et monter la FC repos
        fatigue = fatigue * 0.72 + trimp_day / 100
        hrv = hrv_base * math.exp(rnd.gauss(0, 0.08) - 0.06 * fatigue) * (1 + 0.04 * progress)
        if d == today:
            hrv *= 0.93
        rhr = hr_rest + 2.2 * fatigue + rnd.gauss(0, 1.2)
        sleep_h = max(5.0, min(9.0, 7.1 + rnd.gauss(0, 0.55) + (0.4 if wd >= 5 else 0)))
        if d == today:
            sleep_h = 6.6
        sleep_s = sleep_h * 3600
        score = max(40, min(95, 55 + (sleep_h - 6) * 14 + rnd.gauss(0, 5)))
        bb = max(20, min(100, 92 - 9 * fatigue + rnd.gauss(0, 6)))
        daily_rows.append({
            "date": d.isoformat(), "hrv_night": round(hrv, 1), "hrv_weekly": None,
            "hrv_base_low": 49, "hrv_base_high": 68, "hrv_status": "BALANCED", "rhr": round(rhr),
            "sleep_s": sleep_s, "deep_s": sleep_s * 0.18, "light_s": sleep_s * 0.55, "rem_s": sleep_s * 0.22,
            "awake_s": sleep_s * 0.05, "sleep_score": round(score), "bb_wake": round(bb), "bb_high": round(bb),
            "bb_low": round(max(5, bb - 60)), "stress_avg": round(26 + 6 * fatigue + rnd.gauss(0, 4)),
            "readiness": round(max(5, min(100, 78 - 12 * fatigue + rnd.gauss(0, 7)))),
            "readiness_level": "MODERATE", "recovery_min": None, "steps": 9000 + rnd.randint(-3000, 5000), "raw": None,
        })
        d += timedelta(days=1)
    db.upsert_activities(acts)
    for r in daily_rows:
        db.upsert_daily(r)
    # Résultat de la course passée, cohérent avec l'activité générée
    race_act = next((a for a in acts if a["is_race"]), None)
    if race_act:
        past_race.result_s = int(race_act["duration_s"])
    for r in races:
        db.save_race(r)
    db.set_snapshot("race_predictions", today.isoformat(),
                    {"time5K": 1290, "time10K": 2700, "timeHalfMarathon": 6050, "timeMarathon": 12900})
    db.set_snapshot("training_status", today.isoformat(), {"demo": True})
    db.set_meta("last_sync", datetime.now().strftime("%Y-%m-%d %H:%M") + " (démo)")
    db.set_meta("demo", json.dumps(True))
