"""Synchronisation Garmin en arrière-plan (QThread)."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Slot

from ..db import Database
from ..garmin_sync import AuthRequired, GarminService, SyncCancelled, SyncError


class SyncWorker(QObject):
    progress = Signal(str, int, int)
    finished = Signal(str, str, object)   # statut (ok|auth|error|cancelled), message, stats
    mfa_needed = Signal()

    def __init__(self, db_path: str, token_dir, history_days: int, credentials: tuple[str, str] | None = None):
        super().__init__()
        self.db_path = db_path
        self.token_dir = token_dir
        self.history_days = history_days
        self.credentials = credentials
        self._stop = False
        self._mfa_event = threading.Event()
        self._mfa_code = ""
        self.account_name = ""

    def stop(self) -> None:
        self._stop = True

    def provide_mfa(self, code: str) -> None:
        self._mfa_code = code
        self._mfa_event.set()

    def _prompt_mfa(self) -> str:
        self._mfa_event.clear()
        self.mfa_needed.emit()
        if not self._mfa_event.wait(timeout=300) or not self._mfa_code:
            raise SyncError("Code de validation non saisi.")
        return self._mfa_code

    @Slot()
    def run(self) -> None:
        db = Database(self.db_path)
        svc = GarminService(self.token_dir)
        try:
            self.progress.emit("Connexion à Garmin…", 0, 0)
            if self.credentials:
                self.account_name = svc.login(*self.credentials, prompt_mfa=self._prompt_mfa)
            else:
                self.account_name = svc.login()
            stats = svc.sync(db, self.history_days, self.progress.emit, lambda: self._stop)
            msg = f"{stats['activities']} activités et {stats['days']} jours de données santé mis à jour."
            self.finished.emit("ok", msg, stats)
        except AuthRequired as e:
            self.finished.emit("auth", str(e), None)
        except SyncCancelled as e:
            self.finished.emit("cancelled", str(e), None)
        except SyncError as e:
            self.finished.emit("error", str(e), None)
        except Exception as e:  # erreur réseau inattendue
            self.finished.emit("error", f"Synchronisation interrompue : {e}", None)
        finally:
            db.close()
