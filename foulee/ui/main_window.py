"""Fenêtre principale."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QInputDialog, QLineEdit, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..analysis import build
from ..config import Settings
from ..db import Database
from ..demo import generate
from ..garmin_sync import GarminService
from ..paths import db_path, token_dir
from .page_activities import ActivitiesPage
from .page_charts import HealthPage, LoadPage
from .page_perf import PerfPage
from .page_races import RacesPage
from .page_settings import LoginDialog, SettingsPage
from .page_today import TodayPage
from .theme import C
from .widgets import Balise, hbox, label
from .worker import SyncWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1380, 900)
        self.setMinimumSize(1100, 720)
        self.settings = Settings.load()
        self.service = GarminService(token_dir())
        self.db: Database | None = None
        self.thread: QThread | None = None
        self.worker: SyncWorker | None = None
        self.an = None
        self._open_db()

        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._sidebar())
        self.stack = QStackedWidget()
        h.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.today = TodayPage()
        self.load_page = LoadPage()
        self.health = HealthPage()
        self.acts = ActivitiesPage()
        self.races = RacesPage(lambda: self.db)
        self.perf = PerfPage()
        self.settings_page = SettingsPage(self.settings)
        self.pages = [self.today, self.load_page, self.health, self.acts, self.races, self.perf, self.settings_page]
        for p in self.pages:
            self.stack.addWidget(p)
        self.nav_buttons[0].setChecked(True)

        self.today.connect_requested.connect(self.login)
        self.today.demo_requested.connect(lambda: self.set_demo(True))
        self.races.changed.connect(self.refresh)
        self.settings_page.saved.connect(self.on_settings_saved)
        self.settings_page.login_requested.connect(self.login)
        self.settings_page.logout_requested.connect(self.logout)
        self.settings_page.sync_requested.connect(lambda: self.start_sync())

        self.refresh()
        if self.settings.auto_sync and not self.settings.demo and self.service.has_tokens():
            QTimer.singleShot(500, self.start_sync)

    # ------------------------------------------------------------------ UI
    def _sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(230)
        v = QVBoxLayout(side)
        v.setContentsMargins(0, 24, 0, 18)
        v.setSpacing(2)
        brand = hbox(Balise(C["red"], 30, 20), label(APP_NAME, "brand"), None, spacing=12, margins=(20, 0, 16, 0))
        v.addLayout(brand)
        sub = label("Assistant de course à pied", "brandSub")
        sub.setContentsMargins(20, 2, 0, 18)
        v.addWidget(sub)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        for i, name in enumerate(["Aujourd'hui", "Charge", "Récupération", "Activités", "Courses", "Performance", "Réglages"]):
            b = QPushButton(name)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self.stack.setCurrentIndex(i))
            self.nav_group.addButton(b)
            self.nav_buttons.append(b)
            v.addWidget(b)
        v.addStretch(1)
        box = QVBoxLayout()
        box.setContentsMargins(20, 0, 20, 0)
        box.setSpacing(8)
        self.demo_label = label("Mode démo : données fictives", "small")
        self.demo_label.setStyleSheet(f"color: {C['yellow']};")
        self.demo_exit = QPushButton("Quitter le mode démo")
        self.demo_exit.clicked.connect(lambda: self.set_demo(False))
        self.sync_label = label("", "small", wrap=True)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.sync_btn = QPushButton("Synchroniser")
        self.sync_btn.clicked.connect(self.sync_clicked)
        for w in (self.demo_label, self.demo_exit, self.sync_label, self.progress, self.sync_btn):
            box.addWidget(w)
        box.addWidget(label(f"Version {__version__}", "small"))
        v.addLayout(box)
        return side

    # ------------------------------------------------------------------ données
    def _open_db(self) -> None:
        if self.db:
            self.db.close()
        demo = self.settings.demo
        path = db_path(demo)
        if demo:
            # Données fictives régénérées chaque jour pour rester « à jour »
            probe = Database(path)
            stale = probe.meta("demo_day") != date.today().isoformat()
            probe.close()
            if stale and path.exists():
                path.unlink()
            self.db = Database(path)
            if self.db.is_empty():
                generate(self.db)
                self.db.set_meta("demo_day", date.today().isoformat())
        else:
            self.db = Database(path)

    def refresh(self) -> None:
        self.an = build(self.db, self.settings)
        for p in self.pages:
            p.update_data(self.an)
        self._update_status()

    def _update_status(self) -> None:
        demo = self.settings.demo
        self.demo_label.setVisible(demo)
        self.demo_exit.setVisible(demo)
        connected = self.service.has_tokens()
        last = self.an.last_sync if self.an else None
        if demo:
            self.sync_label.setText("")
            self.sync_btn.setVisible(False)
        else:
            self.sync_btn.setVisible(True)
            self.sync_btn.setText("Synchroniser" if connected else "Connecter Garmin")
            self.sync_label.setText(f"Dernière synchro : {self._fmt_sync(last)}" if last else
                                    ("Jamais synchronisé" if connected else "Compte Garmin non connecté"))
        email = self.settings.garmin_email
        if connected:
            txt = f"Connecté{' (' + email + ')' if email else ''}. Les jetons de session sont enregistrés localement."
        else:
            txt = "Aucun compte connecté. Connecte-toi pour récupérer tes activités et tes données santé."
        self.settings_page.set_account(connected, txt)

    @staticmethod
    def _fmt_sync(s: str) -> str:
        try:
            d, t = s.split(" ")[:2]
            y, m, dd = d.split("-")
            return f"{dd}/{m} à {t}"
        except ValueError:
            return s

    # ------------------------------------------------------------------ actions
    def set_demo(self, on: bool) -> None:
        self.settings.demo = on
        self.settings.save()
        self.settings_page.load(self.settings)
        self._open_db()
        self.refresh()
        self.stack.setCurrentIndex(0)
        self.nav_buttons[0].setChecked(True)

    def on_settings_saved(self, s: Settings) -> None:
        demo_changed = s.demo != (self.db.path.endswith("demo.sqlite"))
        self.settings = s
        if demo_changed:
            self._open_db()
        self.refresh()

    def sync_clicked(self) -> None:
        if self.thread is not None and self.worker is not None:
            self.worker.stop()
            return
        if self.service.has_tokens():
            self.start_sync()
        else:
            self.login()

    def login(self, message: str = "") -> None:
        dlg = LoginDialog(self.settings.garmin_email, message, self)
        if not dlg.exec():
            return
        email, pwd = dlg.credentials()
        if not email or not pwd:
            QMessageBox.warning(self, "Identifiants manquants", "Saisis l'e-mail et le mot de passe de ton compte Garmin.")
            return
        self.settings.garmin_email = email
        if self.settings.demo:
            self.settings.demo = False
            self.settings_page.load(self.settings)
            self._open_db()
            self.refresh()
        self.settings.save()
        self.start_sync((email, pwd))

    def logout(self) -> None:
        ok = QMessageBox.question(self, "Se déconnecter", "Supprimer la session Garmin de cet ordinateur ? "
                                  "Les données déjà synchronisées sont conservées.", QMessageBox.Yes | QMessageBox.No)
        if ok == QMessageBox.Yes:
            self.service.logout()
            self._update_status()

    def start_sync(self, credentials: tuple[str, str] | None = None) -> None:
        if self.thread is not None or self.settings.demo:
            return
        self.thread = QThread(self)
        self.worker = SyncWorker(self.db.path, token_dir(), self.settings.history_days, credentials)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.mfa_needed.connect(self._ask_mfa)
        self.worker.finished.connect(self._on_finished)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.sync_btn.setText("Arrêter")
        self.sync_label.setText("Connexion à Garmin…")
        self.thread.start()

    def _on_progress(self, text: str, i: int, n: int) -> None:
        self.sync_label.setText(text)
        if n > 0:
            self.progress.setRange(0, n)
            self.progress.setValue(i)
        else:
            self.progress.setRange(0, 0)

    def _ask_mfa(self) -> None:
        code, ok = QInputDialog.getText(self, "Validation en deux étapes",
                                        "Saisis le code reçu de Garmin (e-mail ou application) :", QLineEdit.Normal)
        self.worker.provide_mfa(code.strip() if ok else "")

    def _on_finished(self, status: str, message: str, _stats) -> None:
        self.thread.quit()
        self.thread.wait()
        self.thread = None
        self.worker = None
        self.progress.setVisible(False)
        # Recharger depuis le disque : le worker a écrit avec sa propre connexion
        self._open_db()
        self.refresh()
        if status == "ok":
            self.statusBar().showMessage(message, 8000)
        elif status == "auth":
            self.login(message)
        elif status == "error":
            QMessageBox.warning(self, "Synchronisation Garmin", message)
        else:
            self.statusBar().showMessage(message, 5000)

    def closeEvent(self, e):
        if self.worker:
            self.worker.stop()
        if self.thread:
            self.thread.quit()
            self.thread.wait(3000)
        super().closeEvent(e)
