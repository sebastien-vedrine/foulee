"""Page « Progression » : sorties comparées par type de séance, meilleurs temps."""
from __future__ import annotations

from datetime import timedelta

from matplotlib.ticker import FuncFormatter
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QPushButton, QVBoxLayout

from .. import metrics as M
from .. import progress as P
from . import charts as CH
from .page_charts import RangePage
from .theme import C
from .widgets import Tile, card, clear_layout, hbox, label


def eff_str(e: float | None) -> str:
    return f"{M.fr(e, 2)} m/batt." if e else "–"


def eff_color(pct: float | None) -> str | None:
    if pct is None:
        return None
    if pct >= 1.5:
        return C["green"]
    if pct <= -1.5:
        return C["orange"]
    return C["text"]


def pace_delta_str(s: float | None) -> str:
    if s is None:
        return ""
    if abs(s) < 2:
        return "même allure"
    return f"{abs(s):.0f} s/km plus {'rapide' if s < 0 else 'lent'}"


def comparison_block(cmp: P.Comparison) -> QVBoxLayout:
    """Bloc « comparée à tes N dernières sorties du même type » (fiche activité, page du jour)."""
    box = QVBoxLayout()
    box.setSpacing(6)
    box.addWidget(label(f"Comparée à tes {len(cmp.peers)} sorties « {cmp.label} » précédentes "
                        f"({P.COMPARE_DAYS // 30} derniers mois au plus)", "small"))
    grid = QGridLayout()
    grid.setHorizontalSpacing(28)
    p = cmp.point
    hr_sub = f"moy. {cmp.hr:.0f}" if cmp.hr else ""
    if cmp.hr_delta is not None:
        hr_sub += f" · {'+' if cmp.hr_delta >= 0 else '−'}{abs(cmp.hr_delta):.0f} bpm"
    pace_sub = f"moy. {M.pace_str(cmp.speed)}" if cmp.speed else ""
    if cmp.pace_delta_s is not None:
        pace_sub += f" · {pace_delta_str(cmp.pace_delta_s)}"
    eff_sub = ""
    if cmp.eff_delta_pct is not None:
        eff_sub = f"{P.signed(cmp.eff_delta_pct)} % vs moy. {M.fr(cmp.efficiency, 2)}"
        if cmp.rank:
            eff_sub += f" · {cmp.rank}{'re' if cmp.rank == 1 else 'e'} sur {cmp.ranked}"
    cells = [
        ("FC moyenne", f"{p.hr:.0f} bpm" if p.hr else "–", hr_sub, None),
        ("Allure ajustée à la pente", M.pace_str(p.speed), pace_sub, None),
        ("Efficacité", eff_str(p.efficiency), eff_sub, eff_color(cmp.eff_delta_pct)),
    ]
    for i, (k, v, sub, col) in enumerate(cells):
        cell = QVBoxLayout()
        cell.setSpacing(0)
        cell.addWidget(label(k, "small"))
        val = label(v, "h3")
        if col:
            val.setStyleSheet(f"color: {col};")
        cell.addWidget(val)
        cell.addWidget(label(sub, "small"))
        grid.addLayout(cell, 0, i)
    grid.setColumnStretch(len(cells), 1)
    box.addLayout(grid)
    return box


class ProgressPage(RangePage):
    RANGES = [("6 mois", 182), ("1 an", 365)]

    def __init__(self):
        super().__init__("Progression", "Tes sorties comparées à celles du même type : FC moyenne, allure ajustée "
                                        "à la pente et efficacité")
        self.cat = "footing"
        f, lay = card()
        lay.addWidget(label(f"Ces {P.RECENT_DAYS // 7} dernières semaines, comparées aux "
                            f"{3 * P.RECENT_DAYS // 7} précédentes", "h2"))
        lay.addWidget(label("Efficacité : distance parcourue par battement cardiaque, à allure ajustée à la pente. "
                            "Si elle monte, tu cours plus vite pour la même FC : c'est le signe le plus fiable "
                            "de progrès en endurance. La chaleur, la fatigue et la durée de la sortie la font aussi "
                            "varier, d'où la comparaison entre séances du même type.", "small", wrap=True))
        grid = QGridLayout()
        grid.setSpacing(12)
        self.tiles = {}
        for i, (k, name) in enumerate(P.CATEGORIES.items()):
            t = Tile(name)
            t.setToolTip(P.CATEGORY_HINTS[k])
            self.tiles[k] = t
            grid.addWidget(t, 0, i)
        lay.addLayout(grid)
        self.summary = label("", "muted", wrap=True)
        lay.addWidget(self.summary)
        self.root.addWidget(f)

        f2, lay2 = card()
        self.cat_group = QButtonGroup(self)
        btns = []
        for k, name in P.CATEGORIES.items():
            b = QPushButton(name)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setChecked(k == self.cat)
            b.clicked.connect(lambda _=False, k=k: self._set_cat(k))
            self.cat_group.addButton(b)
            btns.append(b)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(label("Évolution par type de séance", "h2"))
        self.cat_hint = label("", "small")
        head.addWidget(self.cat_hint)
        lay2.addLayout(hbox(head, None, *btns, spacing=6))
        self.chart = CH.Chart(6.4, rows=3)
        lay2.addWidget(self.chart)
        self.sessions = QVBoxLayout()
        lay2.addLayout(self.sessions)
        self.root.addWidget(f2)

        f3, self.rec = card()
        self.root.addWidget(f3)
        self.root.addStretch(1)

    def _set_cat(self, k: str) -> None:
        self.cat = k
        self.render()

    def render(self) -> None:
        an = self.an
        if not an:
            return
        self._tiles()
        self._chart()
        self._sessions()
        self._records()

    # ------------------------------------------------------------------ résumé
    def _tiles(self) -> None:
        an = self.an
        lines = []
        for k, t in self.tiles.items():
            tr = P.trend(an.progress, k, an.today)
            pct = tr.eff_pct
            if pct is None:
                t.set("–", f"pas assez de sorties ({len(tr.recent)} récentes, {len(tr.before)} avant)")
                continue
            (hb, hn), (sb, sn) = tr.hr, tr.speed
            sub = [f"{len(tr.recent)} sorties (avant : {len(tr.before)})"]
            if hb and hn:
                sub.append(f"FC {hn:.0f} bpm (avant {hb:.0f})")
            if sb and sn:
                sub.append(f"{M.pace_str(sn)} (avant {M.pace_str(sb)[:-3]})")
            t.set(f"{P.signed(pct)} %", "\n".join(sub), eff_color(pct))
            lines.append(tr.sentence())
        self.summary.setText(" ".join(lines) if lines else
                             "Il faut au moins deux sorties du même type sur chaque période pour mesurer une tendance.")

    # ------------------------------------------------------------------ graphique
    def _chart(self) -> None:
        an = self.an
        self.cat_hint.setText(P.CATEGORY_HINTS[self.cat].capitalize() + ". Points : chaque sortie. Courbe : moyenne "
                              f"sur {P.RECENT_DAYS // 7} semaines.")
        start = an.today - timedelta(days=self.days)
        pts = [p for p in an.progress if p.category == self.cat and p.day >= start]
        ax_e, ax_h, ax_p = self.chart.reset()
        if not pts:
            CH.empty(ax_e, "Aucune sortie de ce type sur la période.")
            for ax in (ax_h, ax_p):
                ax.set_visible(False)
            self.chart.finish()
            return
        color = C["green"]
        series = [
            (ax_e, [(p.day, p.efficiency) for p in pts if p.efficiency], "Efficacité (m/batt.)", color),
            (ax_h, [(p.day, p.hr) for p in pts if p.hr], "FC moyenne", C["red"]),
            (ax_p, [(p.day, 60000 / p.speed) for p in pts if p.speed], "Allure ajustée", C["blue"]),
        ]
        for ax, data, name, col in series:
            if not data:
                continue
            xs, ys = [d for d, _ in data], [v for _, v in data]
            ax.plot(xs, ys, "o", ms=4, color=col, alpha=0.55)
            roll = []
            for d in xs:
                win = [v for x, v in data if d - timedelta(days=P.RECENT_DAYS) < x <= d]
                roll.append(sum(win) / len(win))
            ax.plot(xs, roll, color=col, lw=2)
            ax.set_ylabel(name, fontsize=9)
        ax_p.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{int(v // 60)}:{int(v % 60):02d}"))
        ax_p.invert_yaxis()
        CH.date_axis(ax_p, start, an.today)
        self.chart.fig.subplots_adjust(hspace=0.12)
        self.chart.finish()

    def _sessions(self) -> None:
        an = self.an
        clear_layout(self.sessions)
        pts = [p for p in an.progress if p.category == self.cat][-8:]
        if not pts:
            return
        self.sessions.addWidget(label("Dernières sorties de ce type", "h3"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        heads = ("Date", "Sortie", "Durée", "FC moy.", "Allure ajustée", "Efficacité", "vs les précédentes")
        for j, h in enumerate(heads):
            grid.addWidget(label(h, "small"), 0, j, Qt.AlignLeft if j < 2 else Qt.AlignRight)
        for i, p in enumerate(reversed(pts), start=1):
            cmp = P.compare(an.progress, p.id)
            pct = cmp.eff_delta_pct if cmp else None
            vals = [p.day.strftime("%d/%m/%Y"), p.name, M.fmt_duration(p.duration_s),
                    f"{p.hr:.0f}" if p.hr else "–", M.pace_str(p.speed), eff_str(p.efficiency),
                    f"{P.signed(pct)} %" if pct is not None else "–"]
            for j, v in enumerate(vals):
                lb = label(v)
                if j == len(vals) - 1 and pct is not None:
                    lb.setStyleSheet(f"color: {eff_color(pct)};")
                grid.addWidget(lb, i, j, Qt.AlignLeft if j < 2 else Qt.AlignRight)
        grid.setColumnStretch(1, 1)
        self.sessions.addLayout(grid)

    # ------------------------------------------------------------------ records
    def _records(self) -> None:
        an = self.an
        lay = self.rec
        clear_layout(lay)
        lay.addWidget(label("Meilleurs temps", "h2"))
        lay.addWidget(label("Meilleurs passages mesurés par la montre pendant tes sorties synchronisées, y compris "
                            "au milieu d'une sortie plus longue ou vallonnée.", "small", wrap=True))
        if not an.records:
            lay.addWidget(label("Pas encore de meilleurs passages dans tes activités.", "muted"))
            return
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        heads = ("", "Record", "Allure", "Date", "Meilleur sur 3 mois", "Écart")
        for j, h in enumerate(heads):
            grid.addWidget(label(h, "small"), 0, j, Qt.AlignLeft if j == 0 else Qt.AlignRight)
        for i, r in enumerate(an.records, start=1):
            gap = r.gap_pct
            vals = [r.label, M.fmt_duration(r.best_s, True), M.pace_str(r.distance_m / r.best_s * 60),
                    r.best_day.strftime("%d/%m/%Y"),
                    M.fmt_duration(r.recent_s, True) if r.recent_s else "–",
                    ("record récent" if gap is not None and gap < 0.05 else f"+{M.fr(gap, 1)} %") if gap is not None else "–"]
            for j, v in enumerate(vals):
                lb = label(v, "h3" if j == 1 else None)
                if j == 5 and gap is not None and gap < 0.05:
                    lb.setStyleSheet(f"color: {C['green']};")
                grid.addWidget(lb, i, j, Qt.AlignLeft if j == 0 else Qt.AlignRight)
        grid.setColumnStretch(0, 1)
        lay.addLayout(grid)
