"""Pages « Charge » et « Récupération »."""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import mean, median, pstdev

from PySide6.QtWidgets import QButtonGroup, QGridLayout, QPushButton, QVBoxLayout, QWidget

from .. import metrics as M
from ..analysis import Analysis
from . import charts as CH
from .theme import C
from .widgets import Tile, card, hbox, label, scroll_page

TRAINING_STATUS = {
    "PRODUCTIVE": "Productif", "MAINTAINING": "Maintien", "RECOVERY": "Récupération",
    "UNPRODUCTIVE": "Improductif", "DETRAINING": "Désentraînement", "OVERREACHING": "Surcharge",
    "PEAKING": "Pic de forme", "STRAINED": "Sous tension", "NO_STATUS": "Pas de statut",
}


def garmin_training_status(snap) -> str | None:
    try:
        data = snap["mostRecentTrainingStatus"]["latestTrainingStatusData"]
        dev = next(iter(data.values()))
        phrase = (dev.get("trainingStatusFeedbackPhrase") or "").upper()
        key = next((k for k in TRAINING_STATUS if phrase.startswith(k)), None)
        return TRAINING_STATUS.get(key) if key else None
    except (KeyError, TypeError, StopIteration, AttributeError):
        return None


class RangePage(QWidget):
    RANGES: list[tuple[str, int]] = []
    DEFAULT = 1

    def __init__(self, title: str, subtitle: str):
        super().__init__()
        self.setObjectName("page")
        self.an: Analysis | None = None
        self.days = self.RANGES[self.DEFAULT][1]
        inner = QWidget()
        inner.setObjectName("page")
        self.root = QVBoxLayout(inner)
        self.root.setContentsMargins(28, 22, 28, 28)
        self.root.setSpacing(16)
        self.group = QButtonGroup(self)
        btns = []
        for i, (txt, n) in enumerate(self.RANGES):
            b = QPushButton(txt)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setChecked(i == self.DEFAULT)
            b.clicked.connect(lambda _=False, n=n: self._set_range(n))
            self.group.addButton(b)
            btns.append(b)
        head_left = QVBoxLayout()
        head_left.setSpacing(2)
        head_left.addWidget(label(title, "h1"))
        head_left.addWidget(label(subtitle, "muted"))
        self.root.addLayout(hbox(head_left, None, *btns, spacing=6))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll_page(inner))

    def _set_range(self, n: int) -> None:
        self.days = n
        self.render()

    def update_data(self, an: Analysis) -> None:
        self.an = an
        self.render()

    def render(self) -> None:  # pragma: no cover - surchargé
        pass


class LoadPage(RangePage):
    RANGES = [("3 mois", 90), ("6 mois", 182), ("1 an", 365)]

    def __init__(self):
        super().__init__("Charge d'entraînement", "Modèle forme / fatigue calculé sur le TRIMP de chaque activité")
        self.tiles = {k: Tile(t) for k, t in [("mono", "Monotonie (7 j)"), ("strain", "Contrainte (7 j)"),
                                               ("week", "Cette semaine"), ("garmin", "Statut Garmin")]}
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, t in enumerate(self.tiles.values()):
            grid.addWidget(t, 0, i)
        self.root.addLayout(grid)
        f, lay = card()
        lay.addWidget(label("Forme, fatigue et équilibre", "h2"))
        self.c_load = CH.Chart(4.2, rows=2)
        lay.addWidget(self.c_load)
        self.root.addWidget(f)
        f2, lay2 = card()
        lay2.addWidget(label("Volume hebdomadaire", "h2"))
        lay2.addWidget(label("Kilomètres-effort (distance + D+/100) de course et de randonnée, par semaine", "small"))
        self.c_week = CH.Chart(2.6)
        lay2.addWidget(self.c_week)
        self.root.addWidget(f2)
        self.root.addStretch(1)

    def render(self) -> None:
        an = self.an
        if not an or not an.load:
            return
        ls = an.load
        mono, strain = an.monotony, an.strain
        self.tiles["mono"].set(M.fr(mono, 2) if mono else "–", "au-delà de 2 : semaines trop uniformes",
                               C["yellow"] if mono and mono > 2 else None)
        self.tiles["strain"].set(M.fr(strain, 0), "charge 7 j × monotonie")
        monday = an.today - timedelta(days=an.today.weekday())
        wk = sum(a["kme"] for a in an.activities if a["date"] >= monday.isoformat()
                 and (M.is_run(a["type"]) or M.is_trail_like(a["type"])))
        dplus = sum(a.get("elev_gain") or 0 for a in an.activities if a["date"] >= monday.isoformat()
                    and (M.is_run(a["type"]) or M.is_trail_like(a["type"])))
        self.tiles["week"].set(f"{M.fr(wk, 0)} km-effort", f"dont {M.fr(dplus, 0)} m de D+")
        gs = garmin_training_status(an.snapshots.get("training_status"))
        self.tiles["garmin"].set(gs or "–", "statut d'entraînement de la montre" if gs else "non disponible")

        start = max(ls.days[0], an.today - timedelta(days=self.days))
        i0 = (start - ls.days[0]).days
        days = ls.days[i0:]
        ax1, ax2 = self.c_load.reset()
        if len(days) < 2:
            CH.empty(ax1)
            self.c_load.finish()
        else:
            ax1.bar(days, ls.trimp[i0:], width=0.8, color=C["faint"], alpha=0.45, label="TRIMP du jour")
            ax1.plot(days, ls.ctl[i0:], color=C["blue"], lw=2.2, label="Forme (CTL)")
            ax1.plot(days, ls.atl[i0:], color=C["orange"], lw=1.4, label="Fatigue (ATL)")
            CH.legend(ax1)
            ax1.set_ylim(0, max(max(ls.atl[i0:]), max(ls.ctl[i0:])) * 1.35 + 1)
            tsb = ls.tsb[i0:]
            ax2.fill_between(days, tsb, 0, where=[t >= 0 for t in tsb], color=C["green"], alpha=0.35, lw=0)
            ax2.fill_between(days, tsb, 0, where=[t < 0 for t in tsb], color=C["red"], alpha=0.30, lw=0)
            ax2.plot(days, tsb, color=C["text"], lw=1)
            ax2.axhline(-25, color=C["red"], lw=0.8, ls=(0, (4, 4)))
            ax2.set_ylabel("Équilibre (TSB)", fontsize=9)
            for r in an.races:
                if start <= r.date <= an.today:
                    for ax in (ax1, ax2):
                        ax.axvline(r.date, color=C["yellow"], lw=0.8, alpha=0.7)
            CH.date_axis(ax2, start, an.today)
            self.c_load.fig.subplots_adjust(hspace=0.1)
            self.c_load.finish()

        ax = self.c_week.reset()[0]
        weeks: dict[date, float] = {}
        for d, v in an.daily_kme().items():
            if d >= start:
                wk_start = d - timedelta(days=d.weekday())
                weeks[wk_start] = weeks.get(wk_start, 0) + v
        if weeks:
            xs = sorted(weeks)
            ax.bar([x + timedelta(days=3) for x in xs], [weeks[x] for x in xs], width=5.2, color=C["green"], alpha=0.85)
            avg = mean(weeks[x] for x in xs[-8:])
            ax.axhline(avg, color=C["muted"], lw=0.8, ls=(0, (4, 4)))
            ax.text(xs[0], avg, f" moyenne 8 sem. : {avg:.0f}", color=C["muted"], fontsize=8, va="bottom")
            CH.date_axis(ax, start, an.today + timedelta(days=7))
        else:
            CH.empty(ax)
        self.c_week.finish()


class HealthPage(RangePage):
    RANGES = [("30 jours", 30), ("90 jours", 90), ("6 mois", 182)]

    def __init__(self):
        super().__init__("Récupération", "VFC, FC de repos, sommeil et énergie mesurés par ta montre")
        grid = QGridLayout()
        grid.setSpacing(14)
        self.charts = {}
        specs = [("hrv", "VFC nocturne", "En ms : nuit par nuit, moyenne 7 jours et ta zone normale (60 jours)"),
                 ("rhr", "FC de repos", "En bpm : une hausse de 5 bpm ou plus signale fatigue, stress ou infection"),
                 ("sleep", "Sommeil", "En heures, par phase ; la ligne marque 7 h"),
                 ("ready", "Disponibilité", "Score Foulée et Body Battery au réveil")]
        for i, (k, t, s) in enumerate(specs):
            f, lay = card()
            lay.addWidget(label(t, "h2"))
            lay.addWidget(label(s, "small", wrap=True))
            ch = CH.Chart(2.5)
            lay.addWidget(ch)
            self.charts[k] = ch
            grid.addWidget(f, i // 2, i % 2)
        self.root.addLayout(grid)
        self.root.addStretch(1)

    def render(self) -> None:
        an = self.an
        if not an:
            return
        days = CH.days_back(an.today, self.days)
        dl = an.daily
        start, end = days[0], an.today

        # VFC
        ax = self.charts["hrv"].reset()[0]
        hrv = [dl.get(d, {}).get("hrv_night") for d in days]
        if any(hrv):
            pts = [(d, v) for d, v in zip(days, hrv) if v]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], "o", ms=3, color=C["muted"], alpha=0.7)
            r7 = CH.rolling(hrv, 7)
            ax.plot(days, r7, color=C["blue"], lw=2, label="moyenne 7 j")
            lo, hi = [], []
            for d in days:
                hist = [math.log(dl[x]["hrv_night"]) for x in (d - timedelta(days=i) for i in range(1, 61))
                        if x in dl and dl[x].get("hrv_night")]
                if len(hist) >= 10:
                    m, sd = mean(hist), pstdev(hist)
                    lo.append(math.exp(m - 0.5 * sd))
                    hi.append(math.exp(m + 0.5 * sd))
                else:
                    lo.append(math.nan)
                    hi.append(math.nan)
            ax.fill_between(days, lo, hi, color=C["green"], alpha=0.14, lw=0, label="zone normale")
            CH.legend(ax)
            CH.date_axis(ax, start, end)
        else:
            CH.empty(ax, "Pas de VFC : active le suivi VFC nocturne sur ta montre.")
        self.charts["hrv"].finish()

        # FC repos
        ax = self.charts["rhr"].reset()[0]
        rhr = [dl.get(d, {}).get("rhr") for d in days]
        if any(rhr):
            pts = [(d, v) for d, v in zip(days, rhr) if v]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=C["red"], lw=1.6)
            med = median(p[1] for p in pts)
            ax.axhline(med, color=C["muted"], lw=0.8, ls=(0, (4, 4)))
            ax.axhline(med + 5, color=C["red"], lw=0.6, ls=(0, (2, 4)), alpha=0.6)
            CH.date_axis(ax, start, end)
        else:
            CH.empty(ax)
        self.charts["rhr"].finish()

        # Sommeil
        ax = self.charts["sleep"].reset()[0]
        if any(dl.get(d, {}).get("sleep_s") for d in days):
            deep = [(dl.get(d, {}).get("deep_s") or 0) / 3600 for d in days]
            light = [(dl.get(d, {}).get("light_s") or 0) / 3600 for d in days]
            rem = [(dl.get(d, {}).get("rem_s") or 0) / 3600 for d in days]
            tot = [(dl.get(d, {}).get("sleep_s") or 0) / 3600 for d in days]
            if not any(deep):  # pas de phases : durée totale seule
                ax.bar(days, tot, width=0.75, color=C["blue"], alpha=0.8)
            else:
                ax.bar(days, deep, width=0.75, color="#2E5E9E", label="profond")
                ax.bar(days, light, width=0.75, bottom=deep, color=C["blue"], alpha=0.75, label="léger")
                ax.bar(days, rem, width=0.75, bottom=[a + b for a, b in zip(deep, light)], color="#8DB7EA", label="paradoxal")
                CH.legend(ax, ncol=3)
            ax.axhline(7, color=C["muted"], lw=0.8, ls=(0, (4, 4)))
            ax.set_ylim(0, max(tot + [8]) * 1.25)
            CH.date_axis(ax, start - timedelta(days=1), end + timedelta(days=1))
        else:
            CH.empty(ax)
        self.charts["sleep"].finish()

        # Disponibilité
        ax = self.charts["ready"].reset()[0]
        from ..readiness import compute
        scores = [compute(d, dl).score if d in dl else None for d in days]
        bb = [dl.get(d, {}).get("bb_wake") or dl.get(d, {}).get("bb_high") for d in days]
        if any(s is not None for s in scores) or any(bb):
            pts = [(d, v) for d, v in zip(days, scores) if v is not None]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=C["green"], lw=2, label="Disponibilité Foulée")
            pts = [(d, v) for d, v in zip(days, bb) if v]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=C["yellow"], lw=1.2, alpha=0.8, label="Body Battery")
            ax.set_ylim(0, 105)
            CH.legend(ax, ncol=2)
            CH.date_axis(ax, start, end)
        else:
            CH.empty(ax)
        self.charts["ready"].finish()
