"""Bilan de forme du jour : un message en clair (en forme, fatigué…) à partir des dernières métriques.

Sources : disponibilité du jour (VFC, FC de repos, sommeil, Body Battery, stress), son évolution sur
quelques jours, et la charge d'entraînement (TSB, ratio aigu/chronique, jours d'affilée).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean

from .metrics import fr
from .readiness import Readiness

TITLES = {
    "alerte": "Organisme en alerte",
    "energique": "Plein d'énergie",
    "forme_chargee": "En forme, jambes chargées",
    "en_forme": "En forme",
    "fatigue_entrainement": "Fatigue d'entraînement",
    "un_peu_fatigue": "Un peu fatigué",
    "fatigue": "Fatigué",
    "inconnue": "Forme inconnue",
}

INTROS = {
    "alerte": "Ta VFC est nettement sous ta normale et ta FC de repos grimpe : c'est souvent le signe d'une grosse "
              "fatigue, d'un stress important ou d'un début de maladie. Repos ou marche facile aujourd'hui, et "
              "surveille ces valeurs demain.",
    "energique": "Tous les voyants sont au vert : bonne journée pour une séance de qualité ou une belle sortie.",
    "forme_chargee": "Ta récupération est bonne, mais la charge des derniers jours reste élevée : les jambes peuvent "
                     "sembler lourdes même si l'énergie est là.",
    "en_forme": "Bonne forme générale, rien d'inquiétant dans tes données.",
    "fatigue_entrainement": "Tu récupères correctement, mais la charge accumulée se fait sentir. C'est normal en "
                            "période de construction ; à surveiller si ça dure plus de quelques jours.",
    "un_peu_fatigue": "Ta récupération est incomplète : garde de la marge aujourd'hui et ne force pas.",
    "fatigue": "Ton corps n'a pas encore récupéré : privilégie le repos ou une séance très facile, et soigne ton sommeil.",
    "inconnue": "Pas encore assez de données pour juger ta forme : synchronise ta montre après ton réveil.",
}


@dataclass
class FormReport:
    state: str
    score: float | None            # score effectif utilisé (disponibilité, sinon estimé depuis la charge)
    measured: bool                 # True si fondé sur des mesures santé du jour
    positives: list[str] = field(default_factory=list)
    negatives: list[str] = field(default_factory=list)
    trend: str = ""
    feminine: bool = False

    @property
    def title(self) -> str:
        t = TITLES[self.state]
        return t.replace("fatigué", "fatiguée").replace("Fatigué", "Fatiguée") if self.feminine else t

    @property
    def message(self) -> str:
        intro = INTROS[self.state]
        if self.negatives and self.state == "en_forme":
            intro = "Forme correcte dans l'ensemble, avec un point à surveiller."
        elif self.negatives and self.state == "energique":
            intro = "Bonne énergie dans l'ensemble : séance de qualité possible, en restant attentif au point ci-dessous."
        parts = [intro]
        if not self.measured and self.state != "inconnue":
            parts.insert(0, "Pas de mesure santé ce matin (synchronise ta montre après ton réveil) : estimation "
                            "à partir de ta charge d'entraînement seulement.")
        if self.trend:
            parts.append(self.trend)
        return " ".join(parts)


def _hm(hours: float) -> str:
    return f"{int(hours)} h {int(round((hours % 1) * 60)):02d}"


def _trend(day: date, hist: dict[date, Readiness]) -> str:
    def scores(lo: int, hi: int) -> list[float]:
        return [r.score for d, r in hist.items() if r.score is not None and lo <= (day - d).days <= hi]
    recent, before = scores(0, 2), scores(3, 9)
    if len(recent) < 2 or len(before) < 3:
        return ""
    diff = mean(recent) - mean(before)
    if diff >= 7:
        return f"Ta forme remonte ces derniers jours (+{diff:.0f} points par rapport à la semaine passée)."
    if diff <= -7:
        return f"Ta forme baisse depuis quelques jours ({diff:.0f} points par rapport à la semaine passée)."
    return ""


def assess(day: date, readiness: Readiness | None, history: dict[date, Readiness], daily: dict[date, dict],
           load: dict, consecutive_days: int = 0, feminine: bool = False) -> FormReport:
    r = readiness if readiness is not None and readiness.score is not None else None
    tsb = load.get("tsb") or 0.0
    acwr = load.get("acwr")
    ctl = load.get("ctl") or 0.0
    pos: list[str] = []
    neg: list[str] = []

    if r is not None:
        if r.hrv_z is not None:
            if r.hrv_z >= 0.5:
                pos.append("VFC au-dessus de ta normale")
            elif r.hrv_z <= -1:
                neg.append("VFC sous ta normale")
        if r.hrv_trend_low and not any("VFC" in n for n in neg):
            neg.append("VFC en baisse sur 7 jours")
        if r.rhr_delta is not None:
            if r.rhr_delta <= -2:
                pos.append(f"FC de repos basse ({r.rhr_delta:+.0f} bpm)")
            elif r.rhr_delta >= 3:
                neg.append(f"FC de repos plus haute que d'habitude ({r.rhr_delta:+.0f} bpm)")
        today = daily.get(day) or {}
        if r.sleep_h is not None:
            score = today.get("sleep_score")
            extra = f", score {score:.0f}" if score else ""
            if r.sleep_h >= 7.3 and (not score or score >= 70):
                pos.append(f"bonne nuit ({_hm(r.sleep_h)}{extra})")
            elif r.sleep_h < 6.3 or (score and score < 55):
                neg.append(f"nuit courte ou agitée ({_hm(r.sleep_h)}{extra})")
        nights = [daily[d]["sleep_s"] / 3600 for d in (day - timedelta(days=i) for i in range(3))
                  if d in daily and daily[d].get("sleep_s")]
        if len(nights) == 3 and mean(nights) < 6.5 and not any("nuit" in n for n in neg):
            neg.append(f"dette de sommeil ({fr(mean(nights), 1)} h en moyenne sur 3 nuits)")
        bb = today.get("bb_wake") or today.get("bb_high")
        if bb:
            if bb >= 75:
                pos.append(f"Body Battery à {bb:.0f} au réveil")
            elif bb < 40:
                neg.append(f"Body Battery basse au réveil ({bb:.0f})")
        stress = (daily.get(day - timedelta(days=1)) or {}).get("stress_avg")
        if stress and stress >= 40:
            neg.append(f"journée stressante hier (stress moyen {stress:.0f})")

    if ctl > 5:
        if tsb > 5:
            pos.append("charge récente légère, jambes reposées")
        elif tsb < -20:
            neg.append(f"grosse charge d'entraînement récente (TSB {tsb:+.0f})")
        if acwr is not None and acwr > 1.4:
            neg.append(f"charge en hausse rapide (ratio {fr(acwr, 2)})")
    if consecutive_days >= 4:
        neg.append(f"{consecutive_days} jours d'entraînement d'affilée")

    if r is not None:
        score = r.score
    else:
        score = max(40.0, min(85.0, 72 + 0.8 * tsb)) if ctl > 5 else None

    alert = r is not None and r.hrv_z is not None and r.hrv_z < -1.5 and (r.rhr_delta or 0) >= 4
    if alert:
        state = "alerte"
    elif score is None:
        state = "inconnue"
    elif score >= 75:
        state = "energique" if tsb > -15 else "forme_chargee"
    elif score >= 60:
        state = "fatigue_entrainement" if tsb < -20 else "en_forme"
    elif score >= 45:
        state = "un_peu_fatigue"
    else:
        state = "fatigue"
    return FormReport(state, score, r is not None, pos, neg, _trend(day, history), feminine)
