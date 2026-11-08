"""Coach : suggestion d'entraînement du jour.

Règles transparentes et ordonnées (de la plus prioritaire à la moins prioritaire) :
course du jour > signaux de récupération > disponibilité > récupération post-course >
jours consécutifs > surcharge > affûtage > sortie longue > fractionné > renfo > Z2.
Chaque suggestion explique les raisons qui l'ont déclenchée.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import WEEKDAYS, Settings
from .metrics import fmt_duration, fr, pace_str
from .models import ActRec, Race
from .readiness import Readiness

KIND_LABELS = {
    "REPOS": "Repos",
    "FRACTIONNE": "Fractionné",
    "RENFO": "Renforcement",
    "Z2": "Endurance Z2",
    "COURSE": "Jour de course",
}

PHASE_LABELS = {
    "base": "Foncier",
    "developpement": "Développement",
    "specifique": "Spécifique",
    "affutage": "Affûtage",
    "course": "Course",
    "recuperation": "Récupération",
    "entretien": "Entretien",
}

PHASE_TEXT = {
    "base": "Phase foncière : on construit le volume en endurance, une séance de qualité par semaine.",
    "developpement": "Phase de développement : deux séances de qualité par semaine.",
    "specifique": "Phase spécifique : des séances proches des exigences de la course.",
    "affutage": "Affûtage : volume réduit, un rappel d'intensité pour rester vif.",
    "entretien": "Aucune course objectif programmée : on entretient la forme.",
}

HARD_TARGET = {"base": 1, "developpement": 2, "specifique": 2, "affutage": 1, "entretien": 1, "recuperation": 0}


@dataclass
class Phase:
    name: str
    race: Race | None = None
    days_to: int | None = None
    last_race: Race | None = None
    recovery_ratio: float | None = None   # 0 juste après la course → 1 fin de récupération

    @property
    def label(self) -> str:
        return PHASE_LABELS[self.name]


@dataclass
class Suggestion:
    day: date
    kind: str
    title: str
    summary: str
    duration_min: int = 0
    steps: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    complement: str | None = None
    alternative: str | None = None
    intensity: str = "rest"
    family: str | None = None
    est_trimp: float = 0.0
    est_kme: float = 0.0
    done: bool = False

    @property
    def kind_label(self) -> str:
        return KIND_LABELS[self.kind]


@dataclass
class CoachContext:
    day: date
    settings: Settings
    history: list[ActRec]
    races: list[Race]
    readiness: Readiness | None
    load: dict
    zones: list[tuple[str, int, int]]
    vo2max: float | None = None
    paces: dict | None = None
    simulated: bool = False


# ---------------------------------------------------------------------------
# Phase de préparation
# ---------------------------------------------------------------------------

def taper_days(kme: float) -> int:
    if kme <= 15:
        return 7
    if kme <= 25:
        return 10
    if kme <= 50:
        return 14
    if kme <= 90:
        return 17
    return 21


def recovery_days(kme: float, priority: str) -> int:
    if priority == "A":
        return int(min(max(round(kme / 5), 3), 21))
    return int(min(max(round(kme / 10), 2), 7))


def compute_phase(day: date, races: list[Race]) -> Phase:
    past = sorted((r for r in races if r.date < day and r.priority in ("A", "B")), key=lambda r: r.date, reverse=True)
    for r in past[:3]:
        n = recovery_days(r.kme, r.priority)
        elapsed = (day - r.date).days
        if elapsed <= n:
            return Phase("recuperation", last_race=r, recovery_ratio=elapsed / n)
    upcoming = sorted((r for r in races if r.date >= day), key=lambda r: r.date)
    target = next((r for r in upcoming if r.priority == "A"), None)
    if target is None:
        return Phase("entretien")
    d = (target.date - day).days
    if d == 0:
        return Phase("course", target, 0)
    if d <= taper_days(target.kme):
        return Phase("affutage", target, d)
    spec = 28 if target.kme <= 25 else 42
    if d <= taper_days(target.kme) + spec:
        return Phase("specifique", target, d)
    if d <= 16 * 7:
        return Phase("developpement", target, d)
    return Phase("base", target, d)


# ---------------------------------------------------------------------------
# Coach
# ---------------------------------------------------------------------------

class Coach:
    def __init__(self, ctx: CoachContext):
        self.c = ctx
        self.s = ctx.settings
        self.day = ctx.day
        self.past = [a for a in ctx.history if a.date < ctx.day]
        self.phase = compute_phase(ctx.day, ctx.races)
        r = ctx.readiness
        if r is not None and r.score is not None:
            self.score = r.score
            self.real_readiness = True
        else:
            tsb = ctx.load.get("tsb") or 0
            self.score = max(40.0, min(85.0, 72 + 0.8 * tsb))
            self.real_readiness = False

    # --- historique ---------------------------------------------------------
    def days_since(self, pred) -> int:
        for a in sorted(self.past, key=lambda a: a.date, reverse=True):
            if pred(a):
                return (self.day - a.date).days
        return 99

    def count_week(self, pred) -> int:
        monday = self.day - timedelta(days=self.day.weekday())
        return sum(1 for a in self.past if monday <= a.date < self.day and pred(a))

    def count_last(self, days: int, pred) -> int:
        return sum(1 for a in self.past if (self.day - a.date).days <= days and pred(a))

    def consecutive_days(self) -> int:
        trained = {a.date for a in self.past if a.trimp >= 20 or a.intensity in ("hard", "long", "strength", "race")}
        n, d = 0, self.day - timedelta(days=1)
        while d in trained:
            n += 1
            d -= timedelta(days=1)
        return n

    def last_hard_family(self) -> str | None:
        hard = [a for a in self.past if a.intensity == "hard"]
        return max(hard, key=lambda a: a.date).family if hard else None

    # --- utilitaires de présentation --------------------------------------------
    def zone(self, i: int) -> str:
        if not self.c.zones:
            return f"Z{i}"
        _, lo, hi = self.c.zones[i - 1]
        return f"Z{i} ({lo}–{hi} bpm)"

    def zone_range(self, a: int, b: int) -> str:
        if not self.c.zones:
            return f"Z{a}–Z{b}"
        return f"Z{a}–Z{b} ({self.c.zones[a - 1][1]}–{self.c.zones[b - 1][2]} bpm)"

    def pace(self, key: str) -> str:
        if not self.c.paces or key not in self.c.paces:
            return ""
        slow, fast = self.c.paces[key]
        return f"{pace_str(slow)} à {pace_str(fast)}"

    @property
    def target_kind(self) -> str:
        return self.phase.race.kind if self.phase.race else "trail"

    @property
    def race_factor(self) -> float:
        kme = self.phase.race.kme if self.phase.race else 30
        return min(max(kme / 42.2, 0.4), 2.2)

    # --- point d'entrée ----------------------------------------------------------
    def suggest(self) -> Suggestion:
        sug = self._decide()
        sug.reasons = self._context_reasons() + sug.reasons
        return sug

    def _context_reasons(self) -> list[str]:
        out = []
        ph = self.phase
        if ph.race and ph.days_to is not None:
            w = ph.days_to // 7
            when = f"dans {ph.days_to} j" if ph.days_to < 21 else f"dans {w} semaines"
            out.append(f"{ph.race.name} ({ph.race.priority}) {when} : phase {ph.label.lower()}.")
        elif ph.name == "recuperation" and ph.last_race:
            out.append(f"Récupération après {ph.last_race.name}.")
        elif ph.name == "entretien":
            out.append("Aucune course objectif (A) programmée : entretien de la forme.")
        if self.real_readiness:
            r = self.c.readiness
            out.append(f"Disponibilité {self.score:.0f}/100 ({r.level.lower()}).")
            out.extend(f + "." for f in r.flags[:3])
        tsb, acwr = self.c.load.get("tsb"), self.c.load.get("acwr")
        if tsb is not None and self.c.load.get("ctl", 0) > 5:
            txt = f"Équilibre de charge (TSB) {tsb:+.0f}"
            if acwr:
                txt += f", ratio aigu/chronique {fr(acwr, 2)}"
            out.append(txt + ".")
        return out

    def _decide(self) -> Suggestion:
        c, s, day = self.c, self.s, self.day
        wd = day.weekday()
        avail = s.avail(wd)
        ph = self.phase
        tsb = c.load.get("tsb") or 0.0
        acwr = c.load.get("acwr")
        r = c.readiness

        # 0. Déjà entraîné aujourd'hui
        done = [a for a in c.history if a.date == day and not a.simulated
                and (a.trimp >= 25 or a.intensity in ("hard", "long", "strength", "race"))]
        if done and not c.simulated:
            names = ", ".join(a.name or a.type for a in done)
            return Suggestion(day, "REPOS", "Séance du jour faite", f"Tu as déjà fait : {names}",
                              steps=["Hydratation et repas de récupération.", "10 min de mobilité ou d'étirements doux si tu en as envie."],
                              reasons=["Une séance est déjà enregistrée aujourd'hui."], done=True)

        # 1. Course du jour
        if ph.name == "course" or any(rc.date == day for rc in c.races):
            race = ph.race if ph.name == "course" else next(rc for rc in c.races if rc.date == day)
            return self._race_day(race)

        # 2. Signaux de récupération dans le rouge
        if self.real_readiness:
            hrv_bad = r.hrv_z is not None and r.hrv_z < -1.5 and (r.rhr_delta or 0) >= 4
            if self.score < 35 or hrv_bad:
                why = "VFC effondrée et FC de repos en hausse" if hrv_bad else "Disponibilité très basse"
                return self._rest("Ton corps demande du repos", [why + " : on laisse l'organisme récupérer."])

        # 3. Pas de créneau
        if avail <= 0:
            return self._rest("Pas de créneau prévu", [f"Aucune disponibilité le {WEEKDAYS[wd].lower()} dans tes réglages."])

        # 4. Récupération après course
        if ph.name == "recuperation":
            ratio = ph.recovery_ratio or 0
            if ratio < 0.35:
                return self._rest("Récupération post-course", ["Les premiers jours après une course, le repos est la meilleure séance."])
            if ratio > 0.6 and self.count_week(lambda a: a.intensity == "strength") == 0 and self.days_since(lambda a: a.intensity == "strength") >= 3:
                return self._strength(min(avail, 30), light=True, reasons=["Reprise douce du renforcement."])
            return self._z2(min(avail, 40), recovery=True, reasons=["Reprise progressive, sans intensité."])

        # 5. Trop de jours d'affilée
        consec = self.consecutive_days()
        if consec >= 6 or (consec >= 4 and self.score < 55):
            return self._rest("Jour de repos", [f"{consec} jours d'entraînement d'affilée."])

        # 6. Surcharge
        if tsb < -30 or (acwr is not None and acwr > 1.5):
            why = f"Charge récente élevée (TSB {tsb:+.0f}" + (f", ratio {fr(acwr, 2)})" if acwr else ")")
            if self.score < 60:
                return self._rest("Repos pour assimiler", [why + "."])
            return self._z2(min(avail, 40), recovery=True, reasons=[why + " : séance facile uniquement."])

        hard_week = self.count_week(lambda a: a.intensity in ("hard", "race"))
        since_hard = self.days_since(lambda a: a.intensity in ("hard", "race"))
        since_long = self.days_since(lambda a: a.intensity in ("long", "race"))
        since_strength = self.days_since(lambda a: a.intensity == "strength")
        strength_week = self.count_week(lambda a: a.intensity == "strength")
        yesterday_long = since_long == 1

        # 7. Affûtage
        if ph.name == "affutage":
            d = ph.days_to
            if d == 1:
                return self._activation(min(avail, 25))
            if d == 2:
                return self._rest("Repos avant la course", ["Deux jours avant la course : on arrive frais."])
            if since_hard >= 3 and self.count_last(6, lambda a: a.intensity == "hard") == 0 and self.score >= 60 and d >= 4 and avail >= 40:
                return self._intervals(avail, taper=True, reasons=["Un rappel d'intensité court garde les jambes vives."])
            if d > 7 and strength_week == 0 and since_strength >= 3 and avail >= 25:
                return self._strength(min(avail, 25), light=True, reasons=["Dernier renfo léger, sans charges lourdes."])
            if self._is_long_day(wd, avail, since_long) and d >= 7:
                return self._long(min(avail, 90), taper=True)
            return self._z2(min(avail, 40), reasons=["Volume réduit pendant l'affûtage."])

        # 8. Autour d'une course B ou C
        nxt = min((rc for rc in c.races if rc.date > day), key=lambda rc: rc.date, default=None)
        if nxt and nxt.priority in ("B", "C"):
            dn = (nxt.date - day).days
            if dn == 1:
                return self._activation(min(avail, 25), reasons=[f"{nxt.name} demain."])
            if dn == 2 and nxt.priority == "B":
                return self._z2(min(avail, 35), reasons=[f"{nxt.name} dans 2 jours : séance légère."])

        # 9. Sortie longue
        if self._is_long_day(wd, avail, since_long) and self.score >= 50 and avail >= 75:
            return self._long(avail)
        if (ph.name == "specifique" and self.target_kind == "trail" and self.race_factor >= 1
                and yesterday_long and wd >= 5 and self.score >= 60 and avail >= 75):
            return self._long(avail, back_to_back=True)

        # 10. Fractionné
        target_hard = HARD_TARGET.get(ph.name, 1)
        tomorrow_long = self._is_long_day((wd + 1) % 7, s.avail((wd + 1) % 7), since_long + 1)
        if (self.score >= 62 and since_hard >= 2 and not yesterday_long and hard_week < target_hard
                and avail >= 45 and tsb > -20 and (acwr is None or acwr <= 1.3)
                and not (tomorrow_long and hard_week >= 1)):
            sug = self._intervals(avail)
            strength_target = self._strength_target()
            if strength_week < strength_target and since_strength >= 2 and avail - sug.duration_min >= 25:
                sug.complement = "Si l'énergie est là : 20–25 min de renfo juste après (séance dure = journée dure)."
            return sug

        # 11. Renforcement
        if strength_week < self._strength_target() and since_strength >= 2 and avail >= 25 and self.score >= 45:
            sug = self._strength(min(avail, 45))
            runs_week = self.count_week(lambda a: a.intensity in ("easy", "long", "hard"))
            if avail >= 75 and runs_week < 3:
                sug.complement = "Tu peux le précéder de 30 min en Z2 pour garder du volume."
            return sug

        # 12. Besoin d'un jour off
        trained_7 = {a.date for a in self.past if (day - a.date).days <= 6 and (a.trimp >= 20 or a.intensity != "easy")}
        if len(trained_7) >= 6 and self.score < 70:
            return self._rest("Jour de repos", ["Aucun jour off sur les 7 derniers jours."])

        # 13. Récupération active si forme moyenne
        if self.score < 50:
            return self._z2(min(avail, 40), recovery=True, reasons=["Forme du jour moyenne : on reste très facile."])

        # 14. Par défaut : endurance fondamentale
        strides = ph.name in ("base", "entretien", "developpement") and since_hard >= 4
        return self._z2(min(avail, self._z2_minutes()), strides=strides)

    # --- règles annexes ---------------------------------------------------------
    def _strength_target(self) -> int:
        n = self.s.strength_per_week
        return {"specifique": min(1, n), "affutage": min(1, n), "recuperation": 0}.get(self.phase.name, n)

    def _is_long_day(self, wd: int, avail: int, since_long: int) -> bool:
        if avail < 75 or since_long < 5:
            return False
        pref = self.s.long_run_day
        if pref is not None and pref >= 0:
            return wd == pref or (since_long >= 7 and wd == (pref + 1) % 7)
        best = max(self.s.avail(i) for i in range(7))
        return avail >= best * 0.9

    def _z2_minutes(self) -> int:
        return {"base": 50, "developpement": 55, "specifique": 60, "affutage": 40, "entretien": 45}.get(self.phase.name, 45)

    def _long_minutes(self) -> int:
        rf = self.race_factor
        base = {"base": 75 + 15 * rf, "developpement": 90 + 35 * rf, "specifique": 90 + 55 * rf}.get(self.phase.name, 90)
        # Progression maîtrisée : pas plus de 20 % (+15 min) au-dessus de la plus longue sortie des 6 dernières semaines
        recent = [a.duration_s / 60 for a in self.past if (self.day - a.date).days <= 42 and a.intensity in ("long", "easy", "race")]
        if recent:
            base = min(base, max(recent) * 1.2 + 15)
        return int(round(max(base, 60) / 5) * 5)

    # --- constructeurs de séances ---------------------------------------------------
    def _rest(self, title: str, reasons: list[str]) -> Suggestion:
        return Suggestion(self.day, "REPOS", title, "Pas d'entraînement aujourd'hui",
                          steps=["Option : 20–30 min de marche ou de mobilité douce.",
                                 "Dors tôt : c'est pendant la récupération que la forme progresse."],
                          reasons=reasons, intensity="rest")

    def _race_day(self, race: Race) -> Suggestion:
        return Suggestion(self.day, "COURSE", race.name, f"{fr(race.distance_km, 1).replace(',0', '')} km, {fr(race.elevation_m, 0)} m D+",
                          steps=["Échauffement : 10–15 min très facile + 3 accélérations progressives (moins si ultra).",
                                 "Pars plus lentement que tu ne le voudrais : le premier quart se gère en Z2–Z3.",
                                 "Mange et bois tôt et régulièrement (toutes les 30–45 min en trail long)."],
                          reasons=["C'est le jour J."], intensity="race",
                          est_trimp=race.kme * 12, est_kme=race.kme)

    def _activation(self, minutes: int, reasons: list[str] | None = None) -> Suggestion:
        minutes = max(minutes, 15)
        return Suggestion(self.day, "Z2", "Activation avant course", f"{minutes} min facile avec quelques accélérations",
                          duration_min=minutes,
                          steps=[f"{minutes - 5} min en {self.zone(2)}.",
                                 "4 lignes droites de 20 s, récupération complète en marchant.",
                                 "Prépare ton sac, ton ravitaillement et ta tenue ce soir."],
                          reasons=reasons or ["Veille de course : réveiller les jambes sans fatiguer."],
                          intensity="easy", est_trimp=minutes * 1.3, est_kme=minutes / 6)

    def _z2(self, minutes: int, recovery: bool = False, strides: bool = False, reasons: list[str] | None = None) -> Suggestion:
        minutes = int(max(min(minutes, 240), 25))
        if recovery:
            title, zone = "Footing de récupération", self.zone_range(1, 2)
            summary = f"{minutes} min très facile en {zone}"
            steps = [f"{minutes} min en {zone}, en aisance respiratoire totale.",
                     "Si les jambes sont lourdes, marche active : ça compte aussi."]
        else:
            title, zone = "Endurance fondamentale", self.zone(2)
            summary = f"{minutes} min en {zone}"
            steps = [f"{minutes} min en {zone} : tu dois pouvoir parler en phrases complètes."]
            pace = self.pace("Endurance (E)")
            if pace:
                steps.append(f"Allure indicative sur le plat : {pace} (la FC prime en côte).")
            if strides:
                steps.append("En fin de sortie : 5 lignes droites de 20 s, récupération en trottinant.")
        return Suggestion(self.day, "Z2", title, summary, minutes, steps, reasons or [],
                          intensity="easy", est_trimp=minutes * (1.2 if recovery else 1.5), est_kme=minutes / 6.3)

    def _long(self, avail: int, taper: bool = False, back_to_back: bool = False) -> Suggestion:
        trail = self.target_kind == "trail"
        if back_to_back:
            minutes = int(min(avail, max(60, self._long_minutes() * 0.55)))
            title = "Sortie longue J2 (dos-à-dos)"
            steps = [f"{fmt_duration(minutes * 60)} en {self.zone(2)} sur les jambes de la veille.",
                     "Objectif : apprendre à courir fatigué, comme en deuxième moitié d'ultra.",
                     "Terrain vallonné, marche active dans les pentes raides."]
            reasons = ["Phase spécifique ultra : enchaîner deux sorties longues le week-end."]
        else:
            minutes = int(min(avail, self._long_minutes()))
            if taper:
                minutes = int(min(minutes, 90))
            title = "Sortie longue"
            steps = [f"{fmt_duration(minutes * 60)} en {self.zone(2)} ; la FC ne doit pas dériver au-delà du haut de Z2."]
            if trail and self.phase.name in ("developpement", "specifique") and self.phase.race:
                dplus = self.phase.race.elevation_m / max(self.phase.race.distance_km, 1)
                steps.append(f"Parcours vallonné : vise ≈ {fr(round(dplus * minutes / 6.5, -1), 0)} m de D+ (même ratio que la course).")
                steps.append("Marche active dans les pentes > 15 % ; travaille les descentes en relâchement.")
            if minutes >= 90:
                steps.append("Teste ton ravitaillement : 40–60 g de glucides par heure à partir de 45 min.")
            reasons = ["Jour le plus disponible de la semaine et dernière sortie longue il y a plus de 5 jours."]
            if taper:
                reasons = ["Sortie longue raccourcie pendant l'affûtage."]
        return Suggestion(self.day, "Z2", title, f"{fmt_duration(minutes * 60)} en {self.zone(2)}", minutes, steps, reasons,
                          intensity="long", est_trimp=minutes * 1.6, est_kme=minutes / 6.5)

    def _intervals(self, avail: int, taper: bool = False, reasons: list[str] | None = None) -> Suggestion:
        trail = self.target_kind == "trail"
        ph = self.phase.name
        if taper:
            fam, main, desc = "allure", 20, [f"2 × 8 min à allure course, récupération 3 min en {self.zone(1)}.",
                                             "4 lignes droites de 20 s pour finir."]
            title = "Rappel d'allure"
        else:
            if ph == "specifique":
                order = ["cotes", "seuil"] if trail else ["allure", "seuil"]
            elif ph == "base":
                order = ["cotes", "seuil"] if trail else ["seuil", "vo2"]
            else:
                order = ["vo2", "seuil", "cotes"] if trail else ["vo2", "seuil"]
            last = self.last_hard_family()
            fam = next((f for f in order if f != last), order[0])
            title, main, desc = self._pick_session(fam, avail - 25)
        total = 15 + main + 10
        steps = [f"Échauffement : 15 min progressif jusqu'en {self.zone(2)}, puis 3 accélérations."] + desc + \
                [f"Retour au calme : 10 min en {self.zone(1)}."]
        sug = Suggestion(self.day, "FRACTIONNE", title, f"{total} min dont {main} min de travail", total, steps,
                         reasons or ([f"Dernière séance intense il y a {self.days_since(lambda a: a.intensity in ('hard', 'race'))} jours."
                                      if self.days_since(lambda a: a.intensity in ('hard', 'race')) < 99 else
                                      "Pas de séance intense récente."]),
                         intensity="hard", family=fam, est_trimp=total * 2.0, est_kme=total / 5.5)
        return sug

    def _pick_session(self, fam: str, budget: int) -> tuple[str, int, list[str]]:
        z4, z5, z1 = self.zone(4), self.zone(5), self.zone(1)
        t_pace, i_pace = self.pace("Seuil (T)"), self.pace("Intervalles (I)")
        lib = {
            "vo2": [
                (36, "VO2max : 5 × 4 min", [f"5 × 4 min en {z5}" + (f" (≈ {i_pace})" if i_pace else "") + f", récupération 3 min en {z1}."]),
                (26, "VO2max : 6 × 3 min", [f"6 × 3 min en {z5}, récupération 2 min en trottinant."]),
                (21, "VO2max : 2 × 10 × 30/30", ["2 séries de 10 × (30 s vite / 30 s trot), 3 min entre les séries.",
                                                 f"Le « vite » : effort {z5}, régulier d'une répétition à l'autre."]),
            ],
            "seuil": [
                (36, "Seuil : 3 × 10 min", [f"3 × 10 min en {z4}" + (f" (≈ {t_pace})" if t_pace else "") + ", récupération 2 min en trottinant."]),
                (33, "Seuil : 2 × 15 min", [f"2 × 15 min en {z4}, récupération 3 min en trottinant."]),
                (30, "Seuil : 4 × 6 min", [f"4 × 6 min en {z4}, récupération 90 s."]),
                (20, "Seuil : 3 × 5 min", [f"3 × 5 min en {z4}, récupération 2 min."]),
            ],
            "cotes": [
                (40, "Côtes longues : 4 × 6 min", [f"4 × 6 min en montée régulière en {z4}, récupération en redescendant tranquillement.",
                                                   "Pente 6–12 % ; marche active autorisée si ça devient trop raide."]),
                (30, "Côtes : 8 × 1 min 30", [f"8 × 1 min 30 en côte en {z5}, récupération en redescendant.",
                                              "Buste droit, pas courts et rapides, pousse sur les bras."]),
                (22, "Côtes courtes : 10 × 45 s", [f"10 × 45 s en côte raide, effort {z5}, récupération en descendant en marchant."]),
            ],
            "allure": [
                (35, "Allure course : 3 × 8 min", ["3 × 8 min à l'allure (ou l'effort) visé le jour J, récupération 3 min.",
                                                   "Sur terrain proche de la course si possible."]),
                (24, "Allure course : 2 × 10 min", ["2 × 10 min à l'allure visée, récupération 3 min."]),
            ],
        }
        options = lib[fam]
        for main, title, desc in options:
            if main <= budget:
                return title, main, desc
        main, title, desc = options[-1]
        return title, main, desc

    def _strength(self, minutes: int, light: bool = False, reasons: list[str] | None = None) -> Suggestion:
        minutes = max(20, min(minutes, 50))
        ph = self.phase.name
        if light or ph == "affutage":
            title = "Renfo léger et mobilité"
            steps = ["Gainage : planche 3 × 40 s, planche latérale 2 × 30 s par côté.",
                     "Mobilité hanches et chevilles : 10 min.",
                     "Proprioception : 3 × 30 s en équilibre sur un pied (yeux fermés si facile).",
                     "Pas de charges lourdes ni de pliométrie."]
        elif ph == "specifique":
            title = "Renfo entretien trail"
            steps = ["Circuit en 3 tours, 1 min de pause entre les tours :",
                     "10 squats sautés, 10 fentes marchées par jambe, 12 step-ups par jambe sur un banc.",
                     "15 montées sur pointes de pieds (mollets), 45 s de gainage, 30 s d'équilibre sur un pied.",
                     "Finir par 3 × 6 squats excentriques (4 s en descente) pour préparer les descentes."]
        else:
            title = "Renfo force course à pied"
            steps = ["Squat goblet ou barre : 4 × 6–8 répétitions, lourd mais propre.",
                     "Fentes bulgares : 3 × 8 par jambe.",
                     "Soulevé de terre jambes semi-tendues : 3 × 8.",
                     "Step-ups sur banc haut : 3 × 10 par jambe.",
                     "Mollets excentriques sur une marche : 3 × 12.",
                     "Gainage : planche 3 × 45 s, planche latérale 2 × 30 s par côté."]
        rs = reasons or [f"Renfo cette semaine : {self.count_week(lambda a: a.intensity == 'strength')} séance(s) "
                         f"sur {self._strength_target()} prévue(s)."]
        return Suggestion(self.day, "RENFO", title, f"{minutes} min de renforcement", minutes, steps, rs,
                          intensity="strength", est_trimp=minutes * 0.9)


# ---------------------------------------------------------------------------
# Planification indicative sur plusieurs jours
# ---------------------------------------------------------------------------

def plan_days(ctx: CoachContext, n: int = 7) -> list[Suggestion]:
    """Suggestion du jour + projection indicative des jours suivants.

    Les jours futurs supposent que les suggestions précédentes sont suivies et une
    disponibilité « neutre » ajustée par l'équilibre de charge projeté.
    """
    import math

    out: list[Suggestion] = []
    history = list(ctx.history)
    atl, ctl = ctx.load.get("atl", 0.0), ctx.load.get("ctl", 0.0)
    ka, kc = 1 - math.exp(-1 / 7), 1 - math.exp(-1 / 42)
    # la charge du jour J n'est pas encore dans atl/ctl si la séance n'est pas faite
    for i in range(n):
        d = ctx.day + timedelta(days=i)
        load = {"atl": atl, "ctl": ctl, "tsb": ctl - atl, "acwr": atl / ctl if ctl > 5 else None}
        if i == 0:
            load = ctx.load
        sub = CoachContext(d, ctx.settings, history, ctx.races, ctx.readiness if i == 0 else None, load,
                           ctx.zones, ctx.vo2max, ctx.paces, simulated=i > 0)
        sug = Coach(sub).suggest()
        out.append(sug)
        if not sug.done and sug.intensity != "rest":
            history.append(ActRec(d, "simulation", sug.title, sug.duration_min * 60, sug.est_kme, sug.est_trimp,
                                  sug.intensity, sug.family, simulated=True))
        day_trimp = sum(a.trimp for a in history if a.date == d)
        if i == 0:
            atl, ctl = ctx.load.get("atl", 0.0), ctx.load.get("ctl", 0.0)
            if not sug.done:  # projeter la séance du jour
                atl += ka * (sug.est_trimp - 0)
                ctl += kc * (sug.est_trimp - 0)
            continue
        atl = atl + ka * (day_trimp - atl)
        ctl = ctl + kc * (day_trimp - ctl)
    return out
