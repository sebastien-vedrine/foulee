"""Score de disponibilité du jour (0–100) à partir des métriques santé Garmin.

Chaque composante est notée sur 100 puis pondérée ; les composantes manquantes
sont ignorées et les poids renormalisés.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean, median, pstdev

WEIGHTS = {"hrv": 0.30, "sleep": 0.20, "rhr": 0.15, "bb": 0.15, "garmin": 0.15, "stress": 0.05}
LABELS = {
    "hrv": "VFC nocturne", "sleep": "Sommeil", "rhr": "FC de repos",
    "bb": "Body Battery au réveil", "garmin": "Disponibilité Garmin", "stress": "Stress de la veille",
}


@dataclass
class Component:
    key: str
    score: float
    value: str
    detail: str


@dataclass
class Readiness:
    day: date
    score: float | None
    components: list[Component] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    hrv_z: float | None = None
    hrv_trend_low: bool = False
    rhr_delta: float | None = None
    sleep_h: float | None = None

    @property
    def level(self) -> str:
        if self.score is None:
            return "Inconnue"
        if self.score >= 70:
            return "Bonne"
        if self.score >= 50:
            return "Correcte"
        if self.score >= 35:
            return "Basse"
        return "Très basse"


def _clamp(x: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, x))


def compute(day: date, daily: dict[date, dict]) -> Readiness:
    today = daily.get(day) or {}
    yesterday = daily.get(day - timedelta(days=1)) or {}
    comps: list[Component] = []
    flags: list[str] = []
    r = Readiness(day, None)

    # --- VFC : nuit vs normale personnelle (ln, 60 jours) -------------------
    hist = [math.log(daily[d]["hrv_night"]) for d in (day - timedelta(days=i) for i in range(1, 61))
            if d in daily and daily[d].get("hrv_night")]
    hrv = today.get("hrv_night")
    if hrv and len(hist) >= 10:
        m, sd = mean(hist), max(pstdev(hist), 0.03)
        z = (math.log(hrv) - m) / sd
        last7 = [math.log(daily[d]["hrv_night"]) for d in (day - timedelta(days=i) for i in range(0, 7))
                 if d in daily and daily[d].get("hrv_night")]
        trend_low = len(last7) >= 4 and mean(last7) < m - 0.5 * sd
        score = _clamp(75 + 20 * z) - (10 if trend_low else 0)
        r.hrv_z, r.hrv_trend_low = z, trend_low
        comps.append(Component("hrv", _clamp(score), f"{hrv:.0f} ms",
                               f"normale ≈ {math.exp(m):.0f} ms (écart {z:+.1f} σ)"))
        if z < -1.5:
            flags.append(f"VFC nettement sous ta normale ({hrv:.0f} ms vs ≈{math.exp(m):.0f} ms)")
        elif trend_low:
            flags.append("VFC en baisse sur 7 jours")
    elif hrv and today.get("hrv_status"):
        status = today["hrv_status"].upper()
        score = {"BALANCED": 80, "UNBALANCED": 55, "LOW": 35, "POOR": 20}.get(status, 60)
        comps.append(Component("hrv", score, f"{hrv:.0f} ms", f"statut Garmin : {status.lower()}"))

    # --- FC de repos : écart à la médiane 30 jours ---------------------------
    rhr = today.get("rhr")
    rhr_hist = [daily[d]["rhr"] for d in (day - timedelta(days=i) for i in range(1, 31)) if d in daily and daily[d].get("rhr")]
    if rhr and len(rhr_hist) >= 7:
        base = median(rhr_hist)
        delta = rhr - base
        r.rhr_delta = delta
        comps.append(Component("rhr", _clamp(85 - 9 * delta), f"{rhr:.0f} bpm", f"habituelle ≈ {base:.0f} bpm ({delta:+.0f})"))
        if delta >= 5:
            flags.append(f"FC de repos élevée (+{delta:.0f} bpm)")

    # --- Sommeil : durée + score Garmin + dette sur 3 nuits -------------------
    sleep_s = today.get("sleep_s")
    if sleep_s:
        h = sleep_s / 3600
        r.sleep_h = h
        dur_score = _clamp(30 + (h - 5) * 28)  # 5 h → 30, 7,5 h → 100
        parts = [dur_score]
        if today.get("sleep_score"):
            parts.append(float(today["sleep_score"]))
        score = sum(parts) / len(parts)
        nights = [daily[d]["sleep_s"] / 3600 for d in (day - timedelta(days=i) for i in range(0, 3)) if d in daily and daily[d].get("sleep_s")]
        if len(nights) == 3 and mean(nights) < 6.2:
            score -= 10
            flags.append(f"Dette de sommeil (moy. {mean(nights):.1f} h sur 3 nuits)")
        detail = f"score Garmin {today['sleep_score']:.0f}" if today.get("sleep_score") else "durée seule"
        comps.append(Component("sleep", _clamp(score), f"{int(h)} h {int(round((h % 1) * 60)):02d}", detail))
        if h < 6 and not any("sommeil" in f for f in flags):
            flags.append(f"Nuit courte ({h:.1f} h)")

    # --- Body Battery au réveil ----------------------------------------------
    bb = today.get("bb_wake") or today.get("bb_high")
    if bb:
        comps.append(Component("bb", float(bb), f"{bb:.0f}", "niveau d'énergie estimé par Garmin"))
        if bb < 35:
            flags.append(f"Body Battery basse au réveil ({bb:.0f})")

    # --- Disponibilité Garmin -------------------------------------------------
    tr = today.get("readiness")
    if tr is not None:
        lvl = {"PRIME": "optimale", "HIGH": "élevée", "MODERATE": "modérée", "LOW": "faible",
               "POOR": "très faible"}.get((today.get("readiness_level") or "").upper(), "")
        comps.append(Component("garmin", float(tr), f"{tr:.0f}", lvl or "score Training Readiness"))

    # --- Stress moyen de la veille -------------------------------------------
    st = yesterday.get("stress_avg")
    if st and st > 0:
        comps.append(Component("stress", _clamp(100 - 2 * (st - 25), 20, 100), f"{st:.0f}", "stress moyen sur la journée"))

    if comps:
        tot = sum(WEIGHTS[c.key] for c in comps)
        r.score = sum(c.score * WEIGHTS[c.key] for c in comps) / tot
    r.components = comps
    r.flags = flags
    return r
