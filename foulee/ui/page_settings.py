"""Page « Réglages » et fenêtre de connexion Garmin."""
from __future__ import annotations

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..analysis import Analysis
from ..config import WEEKDAYS, Settings
from ..paths import data_dir
from .widgets import card, hbox, label, scroll_page, vbox


class LoginDialog(QDialog):
    def __init__(self, email: str = "", message: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connexion à Garmin Connect")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        if message:
            lay.addWidget(label(message, "muted", wrap=True))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.email = QLineEdit(email)
        self.email.setPlaceholderText("adresse e-mail du compte Garmin")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("E-mail", self.email)
        form.addRow("Mot de passe", self.password)
        lay.addLayout(form)
        lay.addWidget(label("Le mot de passe sert uniquement à obtenir un jeton de connexion auprès de Garmin ; "
                            "il n'est pas enregistré. Si la validation en deux étapes est active, un code te sera demandé.",
                            "small", wrap=True))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Se connecter")
        bb.button(QDialogButtonBox.Cancel).setText("Annuler")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        (self.password if email else self.email).setFocus()

    def credentials(self) -> tuple[str, str]:
        return self.email.text().strip(), self.password.text()


class SettingsPage(QWidget):
    saved = Signal(object)            # Settings
    login_requested = Signal()
    logout_requested = Signal()
    sync_requested = Signal()

    def __init__(self, settings: Settings):
        super().__init__()
        self.setObjectName("page")
        self.s = settings
        inner = QWidget()
        inner.setObjectName("page")
        root = QVBoxLayout(inner)
        root.setContentsMargins(28, 22, 28, 28)
        root.setSpacing(16)
        root.addWidget(label("Réglages", "h1"))

        # Compte Garmin
        f, lay = card()
        lay.addWidget(label("Compte Garmin", "h2"))
        self.account = label("", "muted", wrap=True)
        lay.addWidget(self.account)
        self.btn_login = QPushButton("Se connecter")
        self.btn_login.setObjectName("primary")
        self.btn_login.clicked.connect(self.login_requested.emit)
        self.btn_logout = QPushButton("Se déconnecter")
        self.btn_logout.clicked.connect(self.logout_requested.emit)
        self.btn_sync = QPushButton("Synchroniser maintenant")
        self.btn_sync.clicked.connect(self.sync_requested.emit)
        lay.addLayout(hbox(self.btn_login, self.btn_sync, self.btn_logout, None))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.history = QSpinBox()
        self.history.setRange(30, 730)
        self.history.setSuffix(" jours")
        self.history.setMinimumWidth(240)
        self.auto = QCheckBox("Synchroniser au démarrage")
        form.addRow("Historique santé récupéré", self.history)
        form.addRow("", self.auto)
        lay.addLayout(form)
        root.addWidget(f)

        # Physiologie
        f, lay = card()
        lay.addWidget(label("Physiologie", "h2"))
        lay.addWidget(label("Laisse 0 pour utiliser la valeur déduite de tes données Garmin.", "small"))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.sex = QComboBox()
        self.sex.setMinimumWidth(240)
        self.sex.addItems(["Homme", "Femme"])
        self.hrmax, self.hrrest, self.lthr = QSpinBox(), QSpinBox(), QSpinBox()
        for sb, hi in ((self.hrmax, 230), (self.hrrest, 120), (self.lthr, 220)):
            sb.setRange(0, hi)
            sb.setSuffix(" bpm")
            sb.setSpecialValueText("Automatique")
            sb.setMinimumWidth(240)
        self.zone_method = QComboBox()
        for txt, key in (("Automatique (FC seuil, sinon FC de réserve)", "auto"), ("% de la FC seuil", "lthr"),
                         ("% de la FC de réserve", "reserve"), ("% de la FC max", "fcmax")):
            self.zone_method.addItem(txt, key)
        self.vo2f = QDoubleSpinBox()
        self.vo2f.setRange(0.7, 1.3)
        self.vo2f.setSingleStep(0.01)
        self.vo2f.setDecimals(2)
        self.btn_align = QPushButton("Aligner sur la VO2max Garmin")
        self.btn_align.clicked.connect(self._align_vo2)
        self.hint = label("", "small", wrap=True)
        form.addRow("Sexe (calcul du TRIMP)", self.sex)
        form.addRow("FC max", self.hrmax)
        form.addRow("FC de repos", self.hrrest)
        form.addRow("FC seuil", self.lthr)
        form.addRow("Zones cardiaques", self.zone_method)
        form.addRow("Facteur VO2max", hbox(self.vo2f, self.btn_align, None))
        lay.addLayout(form)
        lay.addWidget(self.hint)
        root.addWidget(f)

        # Disponibilités
        f, lay = card()
        lay.addWidget(label("Disponibilités", "h2"))
        lay.addWidget(label("Temps maximum pour t'entraîner chaque jour ; 0 = jour sans entraînement. "
                            "Le coach adapte la durée et place la sortie longue sur ton jour le plus libre.", "small", wrap=True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        self.avail = []
        for i, d in enumerate(WEEKDAYS):
            sb = QSpinBox()
            sb.setRange(0, 600)
            sb.setSingleStep(10)
            sb.setSuffix(" min")
            self.avail.append(sb)
            grid.addWidget(label(d, "small"), 0, i)
            grid.addWidget(sb, 1, i)
        lay.addLayout(grid)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.strength = QSpinBox()
        self.strength.setRange(0, 4)
        self.strength.setSuffix(" par semaine")
        self.long_day = QComboBox()
        self.long_day.setMinimumWidth(240)
        self.strength.setMinimumWidth(240)
        self.long_day.addItem("Automatique", -1)
        for i, d in enumerate(WEEKDAYS):
            self.long_day.addItem(d, i)
        self.runs = QComboBox()
        self.runs.setMinimumWidth(240)
        self.runs.addItem("Automatique", 0)
        for n in range(2, 8):
            self.runs.addItem(f"{n} par semaine", n)
        form.addRow("Sorties de course", self.runs)
        form.addRow("Séances de renfo", self.strength)
        form.addRow("Jour de sortie longue", self.long_day)
        lay.addLayout(form)
        lay.addWidget(label("Automatique : 3 sorties sans course objectif, jusqu'à 4 ou 5 à l'approche d'une course A, "
                            "sans dépasser ton habitude récente de plus d'une sortie ; moins pendant l'affûtage et la "
                            "récupération. Les autres jours disponibles accueillent le renfo ou du repos.",
                            "small", wrap=True))
        root.addWidget(f)

        # Données
        f, lay = card()
        lay.addWidget(label("Données", "h2"))
        self.demo = QCheckBox("Mode démo : afficher des données fictives au lieu de ton compte")
        lay.addWidget(self.demo)
        b = QPushButton("Ouvrir le dossier de données")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir()))))
        lay.addLayout(hbox(b, None))
        lay.addWidget(label("Toutes les données restent sur cet ordinateur (base SQLite et jetons Garmin dans ce dossier).",
                            "small", wrap=True))
        root.addWidget(f)

        save = QPushButton("Enregistrer les réglages")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        root.addLayout(hbox(None, save))
        root.addStretch(1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll_page(inner))
        self.an: Analysis | None = None
        self.load(settings)

    def load(self, s: Settings) -> None:
        self.s = s
        self.history.setValue(s.history_days)
        self.auto.setChecked(s.auto_sync)
        self.sex.setCurrentIndex(1 if s.sex == "F" else 0)
        self.hrmax.setValue(s.hr_max or 0)
        self.hrrest.setValue(s.hr_rest or 0)
        self.lthr.setValue(s.lthr or 0)
        self.zone_method.setCurrentIndex(max(0, self.zone_method.findData(s.zone_method)))
        self.vo2f.setValue(s.vo2_factor)
        for i, sb in enumerate(self.avail):
            sb.setValue(s.avail(i))
        self.strength.setValue(s.strength_per_week)
        self.runs.setCurrentIndex(max(0, self.runs.findData(s.runs_per_week)))
        self.long_day.setCurrentIndex(max(0, self.long_day.findData(s.long_run_day)))
        self.demo.setChecked(s.demo)

    def set_account(self, connected: bool, text: str) -> None:
        self.account.setText(text)
        self.btn_login.setText("Changer de compte" if connected else "Se connecter")
        self.btn_logout.setEnabled(connected)
        self.btn_sync.setEnabled(connected)

    def update_data(self, an: Analysis) -> None:
        self.an = an
        parts = [f"Valeurs utilisées : FC max {an.hr_max:.0f} bpm, FC de repos {an.hr_rest:.0f} bpm"]
        parts.append(f"FC seuil {an.lthr:.0f} bpm" if an.lthr else "FC seuil inconnue")
        self.hint.setText(", ".join(parts) + ".")
        self.btn_align.setEnabled(bool(an.vo2max_garmin and an.vo2_points))

    def _align_vo2(self) -> None:
        an = self.an
        if not an or not an.vo2max_garmin:
            return
        raw = an.vo2max / max(an.settings.vo2_factor, 0.01) if an.vo2max else None
        if raw:
            self.vo2f.setValue(max(0.7, min(1.3, an.vo2max_garmin / raw)))

    def _save(self) -> None:
        s = self.s
        s.history_days = self.history.value()
        s.auto_sync = self.auto.isChecked()
        s.sex = "F" if self.sex.currentIndex() == 1 else "H"
        s.hr_max = self.hrmax.value() or None
        s.hr_rest = self.hrrest.value() or None
        s.lthr = self.lthr.value() or None
        s.zone_method = self.zone_method.currentData()
        s.vo2_factor = round(self.vo2f.value(), 2)
        s.availability = {str(i): sb.value() for i, sb in enumerate(self.avail)}
        s.strength_per_week = self.strength.value()
        s.runs_per_week = int(self.runs.currentData())
        s.long_run_day = self.long_day.currentData()
        s.demo = self.demo.isChecked()
        s.save()
        self.saved.emit(s)
