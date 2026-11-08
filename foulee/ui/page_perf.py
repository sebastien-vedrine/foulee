"""Page « Performance » : VO2max, pronostics de référence, allures et zones."""
from __future__ import annotations

from datetime import timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from .. import metrics as M
from ..analysis import Analysis
from . import charts as CH
from .theme import C
from .widgets import card, clear_layout, label, rule, scroll_page

DISTANCES = [("5 km", 5000, "time5K"), ("10 km", 10000, "time10K"), ("Semi-marathon", 21097.5, "timeHalfMarathon"),
             ("Marathon", 42195, "timeMarathon")]


class PerfPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        self.an: Analysis | None = None
        inner = QWidget()
        inner.setObjectName("page")
        root = QVBoxLayout(inner)
        root.setContentsMargins(28, 22, 28, 28)
        root.setSpacing(16)
        root.addWidget(label("Performance", "h1"))
        root.addWidget(label("VO2max estimée sur chaque sortie à partir de l'allure, du dénivelé et de la fréquence cardiaque",
                             "muted"))
        f, lay = card()
        lay.addWidget(label("VO2max effective", "h2"))
        lay.addWidget(label("Points : chaque sortie. Courbe : moyenne pondérée par la durée sur 30 jours.", "small"))
        self.chart = CH.Chart(2.8)
        lay.addWidget(self.chart)
        root.addWidget(f)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.pred_card, self.pred = card()
        self.pace_card, self.pace = card()
        self.zone_card, self.zone = card()
        for c in (self.pred_card, self.pace_card, self.zone_card):
            row.addWidget(c, 1)
        root.addLayout(row)
        root.addStretch(1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll_page(inner))

    def update_data(self, an: Analysis) -> None:
        self.an = an
        self._chart()
        self._tables()

    def _chart(self) -> None:
        an = self.an
        ax = self.chart.reset()[0]
        start = an.today - timedelta(days=365)
        pts = [(d, v) for d, v, _ in an.vo2_points if d >= start]
        if not pts:
            CH.empty(ax, "Il faut des sorties de course avec la FC pour estimer la VO2max.")
            self.chart.finish()
            return
        ax.plot([p[0] for p in pts], [p[1] for p in pts], "o", ms=3.5, color=C["muted"], alpha=0.55)
        first = max(start, pts[0][0])
        days = [first + timedelta(days=i) for i in range((an.today - first).days + 1)]
        shape = [M.vo2max_shape(an.vo2_points, d) for d in days]
        ax.plot(days, shape, color=C["green"], lw=2.2, label="Foulée (30 j)")
        g = [(a["date"], a["vo2max_garmin"]) for a in an.activities if a.get("vo2max_garmin") and a["date"] >= start.isoformat()]
        if g:
            from datetime import date
            ax.step([date.fromisoformat(x[0]) for x in g], [x[1] for x in g], where="post", color=C["blue"], lw=1.4,
                    ls=(0, (5, 3)), label="Garmin")
        CH.legend(ax, ncol=2)
        CH.date_axis(ax, first, an.today)
        self.chart.finish()

    def _table(self, lay, title: str, sub: str, rows: list[tuple], headers: tuple) -> None:
        clear_layout(lay)
        lay.addWidget(label(title, "h2"))
        lay.addWidget(label(sub, "small", wrap=True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        for j, h in enumerate(headers):
            lb = label(h, "small")
            grid.addWidget(lb, 0, j, Qt.AlignRight if j else Qt.AlignLeft)
        for i, row in enumerate(rows, start=1):
            for j, v in enumerate(row):
                lb = label(v, "h3" if j else None)
                grid.addWidget(lb, i, j, Qt.AlignRight if j else Qt.AlignLeft)
        grid.setColumnStretch(0, 1)
        lay.addLayout(grid)
        lay.addStretch(1)

    def _tables(self) -> None:
        an = self.an
        rp = an.snapshots.get("race_predictions") or {}
        if isinstance(rp, list):
            rp = rp[-1] if rp else {}
        rows = []
        for name, dist, key in DISTANCES:
            ours = M.fmt_duration(M.race_time_from_vdot(an.vo2max, dist), True) if an.vo2max else "–"
            g = rp.get(key) if isinstance(rp, dict) else None
            rows.append((name, ours, M.fmt_duration(g, True) if g else "–"))
        self._table(self.pred, "Pronostics sur route", "Potentiel sur parcours plat, sans tenir compte de l'endurance spécifique.",
                    rows, ("", "Foulée", "Garmin"))
        if an.paces:
            prow = [(k, M.pace_str(fast), M.pace_str(slow)) for k, (slow, fast) in an.paces.items()]
        else:
            prow = []
        self._table(self.pace, "Allures d'entraînement", f"Tables de Daniels pour une VO2max de {M.fr(an.vo2max)}." if an.vo2max else
                    "Disponibles dès que la VO2max est estimée.", prow, ("", "Rapide", "Lente"))
        if an.lthr and an.settings.zone_method in ("auto", "lthr"):
            src = f"Basées sur ta FC seuil ({an.lthr:.0f} bpm)."
        elif an.settings.zone_method in ("auto", "reserve"):
            src = f"Basées sur ta FC de réserve (repos {an.hr_rest:.0f}, max {an.hr_max:.0f} bpm)."
        else:
            src = f"Basées sur ta FC max ({an.hr_max:.0f} bpm)."
        if an.hr_max_auto:
            src += " FC max déduite de tes activités : précise-la dans Réglages si besoin."
        zrows = [(n, f"{lo}–{hi}") for n, lo, hi in an.zones]
        self._table(self.zone, "Zones cardiaques", src, zrows, ("", "bpm"))
