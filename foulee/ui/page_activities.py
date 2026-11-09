"""Page « Activités »."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGridLayout, QHeaderView, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import metrics as M
from .. import progress as P
from ..analysis import Analysis
from .theme import C, KIND_COLORS
from .page_progress import comparison_block
from .widgets import StackedBar, card, clear_layout, hbox, label, rule

TYPE_LABELS = {
    "running": "Course", "trail_running": "Trail", "treadmill_running": "Tapis", "track_running": "Piste",
    "street_running": "Course", "indoor_running": "Course indoor", "virtual_run": "Course virtuelle",
    "ultra_run": "Ultra", "strength_training": "Renfo", "hiking": "Randonnée", "walking": "Marche",
    "cycling": "Vélo", "road_biking": "Vélo route", "mountain_biking": "VTT", "indoor_cycling": "Home trainer",
    "lap_swimming": "Natation", "open_water_swimming": "Eau libre", "yoga": "Yoga", "cardio": "Cardio",
}
INTENSITY_LABELS = {"hard": "Intense", "long": "Longue", "strength": "Renfo", "easy": "Facile", "race": "Course"}
INTENSITY_COLORS = {"hard": KIND_COLORS["FRACTIONNE"], "long": KIND_COLORS["Z2"], "strength": KIND_COLORS["RENFO"],
                    "easy": C["muted"], "race": KIND_COLORS["COURSE"]}
ZONE_COLORS = ["#5F6E80", "#3DB37A", "#E8B53A", "#EE8A3C", "#E5484D"]
FILTERS = [("Toutes les activités", None), ("Course et trail", "run"), ("Renforcement", "strength"), ("Autres", "other")]


class NumItem(QTableWidgetItem):
    def __init__(self, text: str, value: float | None):
        super().__init__(text)
        self.value = value if value is not None else -1e9
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        return self.value < getattr(other, "value", 0)


def type_label(t: str) -> str:
    return TYPE_LABELS.get(t, t.replace("_", " ").capitalize())


class ActivitiesPage(QWidget):
    COLS = ["Date", "Type", "Nom", "Distance", "Durée", "D+", "Allure", "FC moy.", "TRIMP", "km-effort", "VO2max eff.", "Intensité"]

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        self.an: Analysis | None = None
        self.rows: list[dict] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 28)
        root.setSpacing(14)
        self.filter = QComboBox()
        for txt, _ in FILTERS:
            self.filter.addItem(txt)
        self.filter.currentIndexChanged.connect(self.render)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(label("Activités", "h1"))
        self.count = label("", "muted")
        head.addWidget(self.count)
        root.addLayout(hbox(head, None, self.filter))
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._show_detail)
        self.table.setMinimumHeight(220)
        root.addWidget(self.table, 1)
        self.detail_frame, self.detail = card()
        self.detail_frame.setMinimumHeight(150)
        root.addWidget(self.detail_frame, 0)

    def update_data(self, an: Analysis) -> None:
        self.an = an
        self.render()

    def render(self) -> None:
        if not self.an:
            return
        mode = FILTERS[self.filter.currentIndex()][1]
        acts = list(reversed(self.an.activities))
        if mode == "run":
            acts = [a for a in acts if M.is_run(a["type"]) or M.is_trail_like(a["type"])]
        elif mode == "strength":
            acts = [a for a in acts if M.is_strength(a["type"])]
        elif mode == "other":
            acts = [a for a in acts if not (M.is_run(a["type"]) or M.is_trail_like(a["type"]) or M.is_strength(a["type"]))]
        self.rows = acts
        self.count.setText(f"{len(acts)} activités synchronisées" if acts else "Aucune activité pour ce filtre")
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(acts))
        for i, a in enumerate(acts):
            d = date.fromisoformat(a["date"])
            dist = (a.get("distance_m") or 0) / 1000
            speed = (a.get("distance_m") or 0) / ((a.get("moving_s") or a.get("duration_s") or 1) / 60)
            run = M.is_run(a["type"]) or M.is_trail_like(a["type"])
            items = [
                NumItem(d.strftime("%d/%m/%Y"), d.toordinal()),
                QTableWidgetItem(type_label(a["type"])),
                QTableWidgetItem(a["name"]),
                NumItem(f"{M.fr(dist)} km" if dist else "–", dist),
                NumItem(M.fmt_duration(a.get("duration_s")), a.get("duration_s")),
                NumItem(f"{M.fr(a['elev_gain'], 0)} m" if a.get("elev_gain") else "–", a.get("elev_gain")),
                NumItem(M.pace_str(speed) if run and dist else "–", -speed if speed else None),
                NumItem(f"{a['avg_hr']:.0f}" if a.get("avg_hr") else "–", a.get("avg_hr")),
                NumItem(f"{a['trimp']:.0f}", a["trimp"]),
                NumItem(M.fr(a["kme"]) if run else "–", a["kme"] if run else None),
                NumItem(M.fr(a["vo2eff"]) if a.get("vo2eff") else "–", a.get("vo2eff")),
                QTableWidgetItem(INTENSITY_LABELS.get(a["intensity"], "")),
            ]
            items[0].setData(Qt.UserRole, i)
            items[-1].setForeground(QColor(INTENSITY_COLORS.get(a["intensity"], C["muted"])))
            for j, it in enumerate(items):
                t.setItem(i, j, it)
        t.setSortingEnabled(True)
        t.sortItems(0, Qt.DescendingOrder)
        if acts:
            t.selectRow(0)
        else:
            clear_layout(self.detail)
            self.detail.addWidget(label("Synchronise Garmin pour voir tes activités ici.", "muted"))

    def _show_detail(self) -> None:
        sel = self.table.selectedItems()
        if not sel:
            return
        idx = self.table.item(sel[0].row(), 0).data(Qt.UserRole)
        a = self.rows[idx]
        clear_layout(self.detail)
        d = date.fromisoformat(a["date"])
        self.detail.addWidget(label(a["name"] or type_label(a["type"]), "h2"))
        bits = [d.strftime("%d/%m/%Y"), type_label(a["type"])]
        if a.get("distance_m"):
            bits.append(f"{M.fr(a['distance_m'] / 1000, 2)} km")
        bits.append(M.fmt_duration(a.get("duration_s")))
        if a.get("elev_gain"):
            bits.append(f"{M.fr(a['elev_gain'], 0)} m D+")
        cat = P.category(a)
        if cat:
            bits.append(f"séance « {P.CATEGORIES[cat]} »")
        self.detail.addWidget(label(", ".join(bits), "muted"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        stats = [
            ("FC moyenne / max", f"{a['avg_hr']:.0f} / {a['max_hr']:.0f} bpm" if a.get("avg_hr") and a.get("max_hr") else "–"),
            ("TRIMP", f"{a['trimp']:.0f}"),
            ("Effet aérobie / anaérobie", f"{M.fr(a['te_aero'])} / {M.fr(a['te_anaero'])}" if a.get("te_aero") is not None and a.get("te_anaero") is not None else "–"),
            ("VO2max effective", M.fr(a["vo2eff"]) if a.get("vo2eff") else "–"),
            ("VO2max Garmin", f"{a['vo2max_garmin']:.0f}" if a.get("vo2max_garmin") else "–"),
            ("Cadence", f"{a['cadence']:.0f} pas/min" if a.get("cadence") else "–"),
        ]
        for i, (k, v) in enumerate(stats):
            box = QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(label(k, "small"))
            box.addWidget(label(v, "h3"))
            grid.addLayout(box, 0, i)
        grid.setColumnStretch(len(stats), 1)
        self.detail.addLayout(grid)
        zones = [a.get(f"z{i}") or 0 for i in range(1, 6)]
        if sum(zones) > 0:
            self.detail.addWidget(label("Temps par zone cardiaque (zones de la montre)", "small"))
            self.detail.addWidget(StackedBar(list(zip(zones, ZONE_COLORS))))
            leg = hbox(spacing=16)
            tot = sum(zones)
            for i, z in enumerate(zones):
                lb = label(f"Z{i + 1} {z / tot * 100:.0f} %", "small")
                lb.setStyleSheet(f"color: {ZONE_COLORS[i] if i else C['muted']};")
                leg.addWidget(lb)
            leg.addStretch(1)
            self.detail.addLayout(leg)
        cmp = P.compare(self.an.progress, a["id"]) if cat else None
        if cmp:
            self.detail.addWidget(rule())
            self.detail.addLayout(comparison_block(cmp))
        self.detail.addStretch(1)
