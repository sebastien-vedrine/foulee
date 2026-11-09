"""Page « Aujourd'hui » : la séance suggérée et ce qui la justifie."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from .. import metrics as M
from ..analysis import Analysis
from ..coach import Suggestion
from ..form import FormReport
from ..readiness import LABELS
from .theme import C, KIND_COLORS, level_color
from .widgets import Balise, Bar, Gauge, Tile, card, clear_layout, hbox, label, rule, scroll_page, vbox

DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
DAYS_SHORT = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]


def long_date(d: date) -> str:
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


class DayChip(QFrame):
    clicked = Signal(int)

    def __init__(self, idx: int, sug: Suggestion, selected: bool):
        super().__init__()
        self.idx = idx
        self.setObjectName("chipToday" if selected else "chip")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{sug.title}\n{sug.summary}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        head = "Aujourd'hui" if idx == 0 else f"{DAYS_SHORT[sug.day.weekday()]} {sug.day.day}"
        lay.addWidget(label(head, "small"))
        lay.addWidget(Balise(KIND_COLORS[sug.kind], 26, 16))
        k = label("Sortie longue" if sug.intensity == "long" else sug.kind_label, "h3")
        lay.addWidget(k)
        dur = M.fmt_duration(sug.duration_min * 60) if sug.duration_min else ("Fait" if sug.done else "–")
        lay.addWidget(label(dur, "small"))
        lay.addStretch(1)

    def mousePressEvent(self, e):
        self.clicked.emit(self.idx)
        super().mousePressEvent(e)


class TodayPage(QWidget):
    connect_requested = Signal()
    demo_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        self.an: Analysis | None = None
        self.selected = 0
        inner = QWidget()
        inner.setObjectName("page")
        self.root = QVBoxLayout(inner)
        self.root.setContentsMargins(28, 22, 28, 28)
        self.root.setSpacing(18)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll_page(inner))

    # ------------------------------------------------------------------
    def update_data(self, an: Analysis) -> None:
        self.an = an
        self.selected = 0
        self.render()

    def render(self) -> None:
        clear_layout(self.root)
        an = self.an
        if an is None or not an.has_data:
            self._empty_state()
            return
        today = an.today
        ph = an.phase
        sub = ""
        if ph and ph.race and ph.days_to is not None:
            sub = f"{ph.race.name} dans {ph.days_to} jours, phase {ph.label.lower()}"
        elif ph and ph.name == "recuperation" and ph.last_race:
            sub = f"Récupération après {ph.last_race.name}"
        else:
            sub = "Aucune course objectif programmée"
        self.root.addLayout(vbox(label(long_date(today), "h1"), label(sub, "muted"), spacing=2))
        if an.form:
            self.root.addWidget(self._form_card(an.form))

        top = QHBoxLayout()
        top.setSpacing(18)
        top.addWidget(self._hero(an.plan[self.selected]), 3)
        top.addWidget(self._readiness_card(), 2)
        self.root.addLayout(top)

        self.root.addLayout(hbox(label("Les 7 prochains jours", "h2"), None,
                                 label("Projection indicative, recalculée chaque jour avec tes données", "small")))
        strip = QHBoxLayout()
        strip.setSpacing(10)
        for i, sg in enumerate(an.plan):
            chip = DayChip(i, sg, i == self.selected)
            chip.clicked.connect(self._select)
            strip.addWidget(chip, 1)
        self.root.addLayout(strip)

        self.root.addWidget(label("Charge et forme", "h2"))
        grid = QGridLayout()
        grid.setSpacing(12)
        ld = an.load_at(today)
        tiles = []
        t = Tile("Forme (CTL, 42 j)")
        t.set(f"{ld['ctl']:.0f}", "charge chronique", tip="Moyenne exponentielle de la charge TRIMP sur 42 jours.")
        tiles.append(t)
        t = Tile("Fatigue (ATL, 7 j)")
        t.set(f"{ld['atl']:.0f}", "charge aiguë", tip="Moyenne exponentielle de la charge TRIMP sur 7 jours.")
        tiles.append(t)
        t = Tile("Équilibre (TSB)")
        tsb = ld["tsb"]
        col = C["green"] if tsb > 5 else (C["text"] if tsb > -10 else (C["yellow"] if tsb > -25 else C["red"]))
        desc = "frais" if tsb > 5 else ("neutre" if tsb > -10 else ("fatigue productive" if tsb > -25 else "fatigue élevée"))
        t.set(f"{tsb:+.0f}", desc, col)
        tiles.append(t)
        t = Tile("Ratio aigu / chronique")
        acwr = ld.get("acwr")
        if acwr:
            col = C["green"] if 0.8 <= acwr <= 1.3 else (C["yellow"] if acwr <= 1.5 else C["red"])
            t.set(M.fr(acwr, 2), "zone sûre 0,8 à 1,3", col)
        else:
            t.set("–", "historique insuffisant")
        tiles.append(t)
        t = Tile("VO2max effective")
        if an.vo2max:
            g = f"Garmin : {an.vo2max_garmin:.0f}" if an.vo2max_garmin else "moyenne pondérée sur 30 j"
            t.set(M.fr(an.vo2max), g)
        tiles.append(t)
        t = Tile("Endurance course A")
        rv = next((r for r in an.race_views if r.days_to >= 0 and r.race.priority == "A"), None)
        if rv and rv.shape:
            sh = rv.shape["shape"] * 100
            t.set(f"{sh:.0f} %", f"pour {rv.race.name}", level_color(sh),
                  tip="Volume hebdo et sorties longues récents comparés aux exigences de la course.")
        else:
            t.set("–", "ajoute une course objectif")
        tiles.append(t)
        for i, t in enumerate(tiles):
            grid.addWidget(t, 0, i)
        self.root.addLayout(grid)
        self.root.addStretch(1)

    def _select(self, idx: int) -> None:
        self.selected = idx
        self.render()

    # ------------------------------------------------------------------
    def _hero(self, sg: Suggestion) -> QFrame:
        f, lay = card("hero")
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(18)
        b = Balise(KIND_COLORS[sg.kind], 56, 36)
        head.addWidget(b, 0, Qt.AlignTop)
        titles = vbox(spacing=0)
        when = "Séance du jour" if self.selected == 0 else f"Projection pour {long_date(sg.day).lower()}"
        titles.addWidget(label(when, "small"))
        titles.addWidget(label(sg.kind_label, "kind"))
        titles.addWidget(label(sg.title, "h2"))
        titles.addWidget(label(sg.summary, "muted", wrap=True))
        head.addLayout(titles, 1)
        lay.addLayout(head)
        lay.addSpacing(4)
        lay.addWidget(rule())
        if sg.steps:
            lay.addWidget(label("Déroulé", "h3"))
            for st in sg.steps:
                row = QHBoxLayout()
                row.setSpacing(10)
                dot = QFrame()
                dot.setFixedSize(6, 6)
                dot.setStyleSheet(f"background: {KIND_COLORS[sg.kind]}; border-radius: 3px;")
                row.addWidget(dot, 0, Qt.AlignTop)
                row.addSpacing(0)
                lb = label(st, wrap=True)
                row.addWidget(lb, 1)
                row.setContentsMargins(0, 2, 0, 0)
                lay.addLayout(row)
        if sg.complement:
            box = QFrame()
            box.setStyleSheet(f"background: {C['panel2']}; border-radius: 6px;")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(12, 8, 12, 8)
            bl.addWidget(label(sg.complement, wrap=True))
            lay.addWidget(box)
        if sg.reasons:
            lay.addSpacing(4)
            lay.addWidget(label("Pourquoi cette séance", "h3"))
            for r in sg.reasons:
                lay.addWidget(label(r, "muted", wrap=True))
        if self.selected != 0:
            lay.addWidget(label("Les jours suivants supposent que les séances précédentes sont faites ; "
                                "la suggestion réelle tiendra compte de ta récupération du matin.", "small", wrap=True))
        lay.addStretch(1)
        return f

    def _form_card(self, fm: FormReport) -> QFrame:
        f, lay = card()
        lay.setContentsMargins(22, 16, 22, 16)
        lay.setSpacing(6)
        color = C["red"] if fm.state == "alerte" else level_color(fm.score)
        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(Balise(color, 34, 22), 0, Qt.AlignTop)
        title = label(fm.title, "h2")
        title.setStyleSheet(f"color: {color};")
        body = vbox(label("Ta forme du jour", "small"), title, label(fm.message, "muted", wrap=True), spacing=2)
        if fm.positives:
            body.addWidget(label("Points forts : " + ", ".join(fm.positives) + ".", "small", wrap=True))
        if fm.negatives:
            body.addWidget(label("À surveiller : " + ", ".join(fm.negatives) + ".", "small", wrap=True))
        head.addLayout(body, 1)
        lay.addLayout(head)
        return f

    def _readiness_card(self) -> QFrame:
        f, lay = card()
        lay.setContentsMargins(22, 18, 22, 18)
        r = self.an.readiness
        lay.addWidget(label("Disponibilité du jour", "h2"))
        g = Gauge(150)
        g.set_value(r.score if r else None, level_color(r.score if r else None), r.level if r else "")
        lay.addWidget(g, 0, Qt.AlignHCenter)
        if not r or not r.components:
            lay.addWidget(label("Pas de mesure santé pour aujourd'hui. Synchronise ta montre après ton réveil "
                                "pour obtenir VFC, sommeil et FC de repos.", "muted", wrap=True))
            lay.addStretch(1)
            return f
        for comp in r.components:
            row = QGridLayout()
            row.setHorizontalSpacing(10)
            row.setVerticalSpacing(2)
            name = label(LABELS[comp.key])
            val = label(comp.value, "h3")
            val.setAlignment(Qt.AlignRight)
            row.addWidget(name, 0, 0)
            row.addWidget(val, 0, 1)
            row.addWidget(Bar(comp.score, level_color(comp.score)), 1, 0, 1, 2)
            row.addWidget(label(comp.detail, "small"), 2, 0, 1, 2)
            row.setColumnStretch(0, 1)
            lay.addLayout(row)
            lay.addSpacing(4)
        lay.addStretch(1)
        return f

    def _empty_state(self) -> None:
        f, lay = card("hero")
        lay.setContentsMargins(36, 32, 36, 32)
        lay.setSpacing(14)
        lay.addWidget(Balise(C["red"], 56, 36))
        lay.addWidget(label("Bienvenue dans Foulée", "kind"))
        lay.addWidget(label("Connecte ton compte Garmin : Foulée récupère tes activités, ta VFC, ton sommeil et ta "
                            "FC de repos, puis te propose chaque matin la séance adaptée à ta forme et à tes "
                            "prochaines courses.", "muted", wrap=True))
        b1 = QPushButton("Connecter Garmin")
        b1.setObjectName("primary")
        b1.clicked.connect(self.connect_requested.emit)
        b2 = QPushButton("Essayer avec des données fictives")
        b2.clicked.connect(self.demo_requested.emit)
        lay.addLayout(hbox(b1, b2, None))
        f.setMaximumWidth(760)
        self.root.addWidget(f)
        self.root.addStretch(1)
