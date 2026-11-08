"""Page « Courses » : calendrier, pronostics et préparation."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)

from .. import metrics as M
from ..analysis import Analysis, RaceView
from ..models import Race
from .theme import C, level_color
from .widgets import Balise, Bar, card, clear_layout, hbox, label, scroll_page, vbox

PRIORITY_COLORS = {"A": C["red"], "B": C["yellow"], "C": C["blue"]}
PRIORITY_LABELS = {"A": "Objectif (A)", "B": "Préparation (B)", "C": "Plaisir (C)"}


def parse_hms(text: str) -> int | None:
    text = text.strip().replace("h", ":").replace("H", ":").replace(" ", "")
    if not text:
        return None
    parts = [p for p in text.split(":")]
    try:
        nums = [int(p) if p else 0 for p in parts]
    except ValueError:
        return None
    if len(nums) == 1:
        return nums[0] * 3600
    if len(nums) == 2:
        return nums[0] * 3600 + nums[1] * 60
    return nums[0] * 3600 + nums[1] * 60 + nums[2]


def fmt_hms(s: int | None) -> str:
    if not s:
        return ""
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def km(x: float) -> str:
    return M.fr(x, 1).replace(",0", "") if x % 1 else M.fr(x, 0)


class RaceDialog(QDialog):
    def __init__(self, race: Race | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modifier la course" if race else "Ajouter une course")
        self.setMinimumWidth(460)
        self.race = race
        f = QFormLayout()
        f.setSpacing(10)
        self.name = QLineEdit(race.name if race else "")
        self.name.setPlaceholderText("Ex. Ultra des Volcans")
        self.date = QDateEdit(QDate(race.date.year, race.date.month, race.date.day) if race else QDate.currentDate().addDays(60))
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        self.kind = QComboBox()
        self.kind.addItems(["Trail", "Route"])
        self.kind.setCurrentIndex(0 if not race or race.kind == "trail" else 1)
        self.dist = QDoubleSpinBox()
        self.dist.setRange(1, 400)
        self.dist.setDecimals(1)
        self.dist.setSuffix(" km")
        self.dist.setValue(race.distance_km if race else 42.2)
        self.elev = QSpinBox()
        self.elev.setRange(0, 30000)
        self.elev.setSingleStep(50)
        self.elev.setSuffix(" m")
        self.elev.setValue(int(race.elevation_m) if race else 0)
        self.prio = QComboBox()
        for k in ("A", "B", "C"):
            self.prio.addItem(PRIORITY_LABELS[k], k)
        self.prio.setCurrentIndex(["A", "B", "C"].index(race.priority) if race else 0)
        self.tech = QComboBox()
        for k, v in M.TECHNICITY_LABELS.items():
            self.tech.addItem(f"{k}. {v}", k)
        self.tech.setCurrentIndex((race.technicity if race else 3) - 1)
        self.goal = QLineEdit(fmt_hms(race.goal_s) if race else "")
        self.goal.setPlaceholderText("h:mm (facultatif)")
        self.result = QLineEdit(fmt_hms(race.result_s) if race else "")
        self.result.setPlaceholderText("h:mm:ss, une fois la course faite")
        self.notes = QPlainTextEdit(race.notes if race else "")
        self.notes.setFixedHeight(60)
        f.addRow("Nom", self.name)
        f.addRow("Date", self.date)
        f.addRow("Type", self.kind)
        f.addRow("Distance", self.dist)
        f.addRow("Dénivelé positif", self.elev)
        f.addRow("Priorité", self.prio)
        f.addRow("Technicité", self.tech)
        f.addRow("Objectif", self.goal)
        f.addRow("Résultat", self.result)
        f.addRow("Notes", self.notes)
        help_ = label("A : la course que tu prépares (phases et affûtage). B : course de préparation, "
                      "allègement de 2 jours. C : course plaisir, considérée comme une séance.", "small", wrap=True)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Enregistrer")
        bb.button(QDialogButtonBox.Cancel).setText("Annuler")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(help_)
        lay.addWidget(bb)
        self.kind.currentIndexChanged.connect(lambda i: self.tech.setEnabled(i == 0))
        self.tech.setEnabled(self.kind.currentIndex() == 0)

    def _accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Nom manquant", "Donne un nom à la course.")
            return
        for field, txt in ((self.goal, "objectif"), (self.result, "résultat")):
            if field.text().strip() and parse_hms(field.text()) is None:
                QMessageBox.warning(self, "Temps invalide", f"Le temps {txt} doit être au format h:mm ou h:mm:ss.")
                return
        self.accept()

    def value(self) -> Race:
        q = self.date.date()
        return Race(self.race.id if self.race else None, self.name.text().strip(), date(q.year(), q.month(), q.day()),
                    self.dist.value(), float(self.elev.value()), "trail" if self.kind.currentIndex() == 0 else "route",
                    self.prio.currentData(), int(self.tech.currentData()), parse_hms(self.goal.text()),
                    parse_hms(self.result.text()), self.notes.toPlainText().strip())


class RacesPage(QWidget):
    changed = Signal()

    def __init__(self, db_getter):
        super().__init__()
        self.setObjectName("page")
        self.db_getter = db_getter
        self.an: Analysis | None = None
        inner = QWidget()
        inner.setObjectName("page")
        self.root = QVBoxLayout(inner)
        self.root.setContentsMargins(28, 22, 28, 28)
        self.root.setSpacing(14)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll_page(inner))

    def update_data(self, an: Analysis) -> None:
        self.an = an
        self.render()

    def render(self) -> None:
        clear_layout(self.root)
        add = QPushButton("Ajouter une course")
        add.setObjectName("primary")
        add.clicked.connect(lambda: self._edit(None))
        self.root.addLayout(hbox(vbox(label("Courses", "h1"),
                                      label("Ton calendrier oriente les phases d'entraînement et l'affûtage", "muted"),
                                      spacing=2), None, add))
        an = self.an
        if not an:
            return
        upcoming = sorted((rv for rv in an.race_views if rv.days_to >= 0), key=lambda rv: rv.race.date)
        past = sorted((rv for rv in an.race_views if rv.days_to < 0), key=lambda rv: rv.race.date, reverse=True)
        if not upcoming:
            f, lay = card()
            lay.addWidget(label("Aucune course à venir. Ajoute ton prochain objectif : la suggestion du jour "
                                "s'organisera autour (foncier, développement, spécifique, affûtage).", "muted", wrap=True))
            self.root.addWidget(f)
        for rv in upcoming:
            self.root.addWidget(self._race_card(rv))
        if past:
            self.root.addSpacing(6)
            self.root.addWidget(label("Courses passées", "h2"))
            if an.personal_trail_factor != 1.0:
                pct = (an.personal_trail_factor - 1) * 100
                self.root.addWidget(label(f"Calibration trail : tes résultats passés ajustent les pronostics trail de "
                                          f"{pct:+.0f} %.", "small", wrap=True))
            else:
                self.root.addWidget(label("Saisis tes résultats : ils calibrent les pronostics trail sur ta façon de courir.",
                                          "small", wrap=True))
            for rv in past:
                self.root.addWidget(self._past_card(rv))
        self.root.addStretch(1)

    @staticmethod
    def _role(rv: RaceView) -> str:
        r = rv.race
        if r.priority == "A":
            return f"Objectif (A), phase actuelle : {rv.phase.lower()}"
        if r.priority == "B":
            return "Préparation (B) : séances allégées les deux jours d'avant"
        return "Plaisir (C) : traitée comme une séance, sans affûtage"

    def _actions(self, race: Race) -> QHBoxLayout:
        e = QPushButton("Modifier")
        e.clicked.connect(lambda: self._edit(race))
        d = QPushButton("Supprimer")
        d.clicked.connect(lambda: self._delete(race))
        return hbox(e, d, spacing=6)

    def _race_card(self, rv: RaceView):
        r = rv.race
        f, lay = card()
        lay.setContentsMargins(20, 16, 20, 16)
        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(Balise(PRIORITY_COLORS[r.priority], 34, 22), 0, Qt.AlignTop)
        when = "aujourd'hui" if rv.days_to == 0 else (f"dans {rv.days_to} jours" if rv.days_to < 60 else f"dans {rv.days_to // 7} semaines")
        specs = f"{km(r.distance_km)} km"
        if r.elevation_m:
            specs += f", {M.fr(r.elevation_m, 0)} m D+"
        if r.kind == "trail":
            specs += f", {M.TECHNICITY_LABELS.get(r.technicity, '').lower()}"
        else:
            specs += ", route"
        head.addLayout(vbox(label(r.name, "h2"),
                            label(f"{r.date.strftime('%d/%m/%Y')}, {when}. {specs}.", "muted"),
                            label(self._role(rv), "small"),
                            spacing=2), 1)
        progbox = QVBoxLayout()
        progbox.setSpacing(0)
        progbox.addWidget(label("Pronostic", "small"), 0, Qt.AlignRight)
        progbox.addWidget(label(M.fmt_duration(rv.prognosis_s) if rv.prognosis_s else "–", "big"), 0, Qt.AlignRight)
        if r.goal_s and rv.prognosis_s:
            diff = rv.prognosis_s - r.goal_s
            txt = f"objectif {M.fmt_duration(r.goal_s)} ({'+' if diff > 0 else '−'}{M.fmt_duration(abs(diff))})"
            g = label(txt, "small")
            g.setStyleSheet(f"color: {C['green'] if diff <= 0 else C['yellow']};")
            progbox.addWidget(g, 0, Qt.AlignRight)
        head.addLayout(progbox)
        lay.addLayout(head)
        if rv.shape:
            sh = rv.shape
            pct = sh["shape"] * 100
            lay.addLayout(hbox(label("Endurance pour cette course", "small"), None, label(f"{pct:.0f} %", "h3")))
            lay.addWidget(Bar(pct, level_color(pct)))
            lay.addWidget(label(f"Volume moyen {sh['week_avg']:.0f} km-effort par semaine sur {sh['target_week']:.0f} visés ; "
                                f"sorties longues ({sh['target_long']:.0f} km-effort) : {sh['long_score'] * 100:.0f} %.",
                                "small", wrap=True))
        if r.notes:
            lay.addWidget(label(r.notes, "muted", wrap=True))
        lay.addLayout(hbox(None, self._actions(r)))
        return f

    def _past_card(self, rv: RaceView):
        r = rv.race
        f, lay = card()
        lay.setContentsMargins(18, 12, 18, 12)
        res = M.fmt_duration(r.result_s) if r.result_s else "résultat non saisi"
        txt = f"{r.date.strftime('%d/%m/%Y')}, {km(r.distance_km)} km"
        if r.elevation_m:
            txt += f", {M.fr(r.elevation_m, 0)} m D+"
        row = hbox(Balise(PRIORITY_COLORS[r.priority], 26, 16),
                   vbox(label(r.name, "h3"), label(txt, "small"), spacing=0), None,
                   label(res, "h3"), self._actions(r), spacing=14)
        lay.addLayout(row)
        return f

    def _edit(self, race: Race | None) -> None:
        dlg = RaceDialog(race, self)
        if dlg.exec():
            self.db_getter().save_race(dlg.value())
            self.changed.emit()

    def _delete(self, race: Race) -> None:
        ok = QMessageBox.question(self, "Supprimer la course", f"Supprimer « {race.name} » du calendrier ?",
                                  QMessageBox.Yes | QMessageBox.No)
        if ok == QMessageBox.Yes:
            self.db_getter().delete_race(race.id)
            self.changed.emit()
