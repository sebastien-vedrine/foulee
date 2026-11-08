"""Connexion à Garmin Connect (bibliothèque garminconnect) et synchronisation incrémentale.

Lecture seule : aucune méthode d'écriture vers le compte Garmin n'est appelée.
Le mot de passe n'est jamais stocké ; seuls les jetons OAuth renvoyés par Garmin le sont,
dans le dossier de données de l'application.
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from .db import Database


class SyncError(Exception):
    pass


class AuthRequired(SyncError):
    """Pas de jetons valides : identifiants Garmin nécessaires."""


class SyncCancelled(SyncError):
    pass


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Conversion des réponses Garmin
# ---------------------------------------------------------------------------

def parse_activity(a: dict) -> dict:
    t = (a.get("activityType") or {}).get("typeKey") or "other"
    start = (a.get("startTimeLocal") or "").replace("T", " ")
    event = (a.get("eventType") or {}).get("typeKey") or ""
    row = {
        "id": int(a["activityId"]), "start": start, "date": start[:10], "type": t,
        "name": a.get("activityName") or "",
        "distance_m": _num(a.get("distance")),
        "duration_s": _num(a.get("duration")) or _num(a.get("elapsedDuration")),
        "moving_s": _num(a.get("movingDuration")),
        "elev_gain": _num(a.get("elevationGain")), "elev_loss": _num(a.get("elevationLoss")),
        "avg_hr": _num(a.get("averageHR")), "max_hr": _num(a.get("maxHR")),
        "avg_speed": _num(a.get("averageSpeed")), "calories": _num(a.get("calories")),
        "te_aero": _num(a.get("aerobicTrainingEffect")), "te_anaero": _num(a.get("anaerobicTrainingEffect")),
        "garmin_load": _num(a.get("activityTrainingLoad")), "vo2max_garmin": _num(a.get("vO2MaxValue")),
        "cadence": _num(a.get("averageRunningCadenceInStepsPerMinute")),
        "te_label": a.get("trainingEffectLabel"),
        "is_race": 1 if event == "race" else 0,
        "raw": json.dumps(a, ensure_ascii=False),
    }
    for i in range(1, 6):
        row[f"z{i}"] = _num(a.get(f"hrTimeInZone_{i}"))
    return row


def _latest_readiness(tr) -> dict:
    if not tr:
        return {}
    if isinstance(tr, dict):
        tr = [tr]
    items = [x for x in tr if isinstance(x, dict) and x.get("score") is not None]
    if not items:
        return {}
    wake = [x for x in items if x.get("inputContext") == "AFTER_WAKEUP_RESET"]
    pool = wake or items
    return max(pool, key=lambda x: x.get("timestampLocal") or x.get("timestamp") or "")


def parse_daily(day: str, hrv: dict | None, sleep: dict | None, summary: dict | None, readiness) -> dict:
    hs = (hrv or {}).get("hrvSummary") or {}
    base = hs.get("baseline") or {}
    ds = (sleep or {}).get("dailySleepDTO") or {}
    overall = ((ds.get("sleepScores") or {}).get("overall") or {}).get("value")
    s = summary or {}
    tr = _latest_readiness(readiness)
    stress = _num(s.get("averageStressLevel"))
    return {
        "date": day,
        "hrv_night": _num(hs.get("lastNightAvg")),
        "hrv_weekly": _num(hs.get("weeklyAvg")),
        "hrv_base_low": _num(base.get("balancedLow")),
        "hrv_base_high": _num(base.get("balancedUpper")),
        "hrv_status": hs.get("status"),
        "rhr": _num(s.get("restingHeartRate")) or _num((sleep or {}).get("restingHeartRate")),
        "sleep_s": _num(ds.get("sleepTimeSeconds")),
        "deep_s": _num(ds.get("deepSleepSeconds")), "light_s": _num(ds.get("lightSleepSeconds")),
        "rem_s": _num(ds.get("remSleepSeconds")), "awake_s": _num(ds.get("awakeSleepSeconds")),
        "sleep_score": _num(overall),
        "bb_wake": _num(s.get("bodyBatteryAtWakeTime")),
        "bb_high": _num(s.get("bodyBatteryHighestValue")), "bb_low": _num(s.get("bodyBatteryLowestValue")),
        "stress_avg": stress if stress is not None and stress >= 0 else None,
        "readiness": _num(tr.get("score")), "readiness_level": tr.get("level"),
        "recovery_min": _num(tr.get("recoveryTime")),
        "steps": s.get("totalSteps"),
        "raw": json.dumps({"hrv": hs, "sleep": ds, "readiness": tr}, ensure_ascii=False),
    }


def parse_lthr(lt) -> float | None:
    if not isinstance(lt, dict):
        return None
    shr = lt.get("speed_and_heart_rate") or lt.get("speedAndHeartRate") or {}
    if isinstance(shr, list):
        shr = shr[0] if shr else {}
    return _num(shr.get("heartRate") or shr.get("hearRate"))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

Progress = Callable[[str, int, int], None]


class GarminService:
    def __init__(self, token_dir: Path):
        self.token_dir = Path(token_dir)
        self.api = None

    @property
    def token_file(self) -> Path:
        return self.token_dir / "garmin_tokens.json"

    def has_tokens(self) -> bool:
        return self.token_file.exists()

    def login(self, email: str | None = None, password: str | None = None,
              prompt_mfa: Callable[[], str] | None = None) -> str:
        try:
            from garminconnect import Garmin, GarminConnectAuthenticationError
        except ImportError as e:  # pragma: no cover
            raise SyncError("La bibliothèque garminconnect n'est pas installée.") from e
        try:
            if email and password:
                api = Garmin(email, password, prompt_mfa=prompt_mfa)
            elif self.has_tokens():
                api = Garmin()
            else:
                raise AuthRequired("Connecte ton compte Garmin dans Réglages.")
            api.login(str(self.token_dir))
        except AuthRequired:
            raise
        except GarminConnectAuthenticationError as e:
            if email:
                raise SyncError(f"Connexion refusée par Garmin : vérifie l'e-mail et le mot de passe ({e}).") from e
            raise AuthRequired("Session Garmin expirée : reconnecte-toi.") from e
        except Exception as e:  # réseau, MFA abandonnée…
            if not email and self.has_tokens():
                raise AuthRequired(f"Session Garmin invalide : reconnecte-toi ({e}).") from e
            raise SyncError(f"Connexion à Garmin impossible : {e}") from e
        self.api = api
        try:
            return api.get_full_name() or ""
        except Exception:
            return ""

    def logout(self) -> None:
        try:
            if self.token_file.exists():
                self.token_file.unlink()
        except OSError:
            pass
        self.api = None

    # --- appels protégés -----------------------------------------------------------
    def _call(self, fn, *args, **kwargs):
        from garminconnect import (GarminConnectAuthenticationError, GarminConnectConnectionError,
                                   GarminConnectNotFoundError, GarminConnectTooManyRequestsError)
        for attempt in range(2):
            try:
                return fn(*args, **kwargs)
            except GarminConnectTooManyRequestsError as e:
                if attempt == 0:
                    time.sleep(45)
                    continue
                raise SyncError("Garmin limite le nombre de requêtes. Réessaie dans quelques minutes : "
                                "les données déjà récupérées sont conservées.") from e
            except GarminConnectAuthenticationError as e:
                raise AuthRequired("Session Garmin expirée : reconnecte-toi.") from e
            except (GarminConnectNotFoundError, GarminConnectConnectionError, ValueError, KeyError, TypeError):
                return None
        return None

    def sync(self, db: Database, history_days: int, progress: Progress | None = None,
             should_stop: Callable[[], bool] | None = None) -> dict:
        if self.api is None:
            self.login()
        api = self.api
        progress = progress or (lambda *_: None)
        should_stop = should_stop or (lambda: False)
        today = date.today()
        stats = {"activities": 0, "days": 0}

        # 1. Activités (un appel par plage)
        last = db.last_activity_date()
        start = date.fromisoformat(last) - timedelta(days=3) if last else today - timedelta(days=max(history_days, 365))
        progress("Activités…", 0, 1)
        acts = self._call(api.get_activities_by_date, start.isoformat(), today.isoformat()) or []
        rows = [parse_activity(a) for a in acts if isinstance(a, dict) and a.get("activityId")]
        db.upsert_activities(rows)
        stats["activities"] = len(rows)

        # 2. Métriques quotidiennes (les 3 derniers jours sont toujours rafraîchis)
        have = db.daily_dates()
        window = [today - timedelta(days=i) for i in range(history_days)]
        todo = [d for d in window if d.isoformat() not in have or (today - d).days <= 2]
        for i, d in enumerate(todo):
            if should_stop():
                raise SyncCancelled("Synchronisation interrompue.")
            ds = d.isoformat()
            progress(f"Santé du {d.strftime('%d/%m')}…", i, len(todo))
            hrv = self._call(api.get_hrv_data, ds)
            sleep = self._call(api.get_sleep_data, ds)
            summary = self._call(api.get_user_summary, ds)
            ready = self._call(api.get_training_readiness, ds)
            db.upsert_daily(parse_daily(ds, hrv, sleep, summary, ready))
            stats["days"] += 1

        # 3. Instantanés (statut d'entraînement, prédictions, seuil)
        progress("Statut d'entraînement…", len(todo), len(todo) + 1)
        ts = self._call(api.get_training_status, today.isoformat())
        if ts:
            db.set_snapshot("training_status", today.isoformat(), ts)
        rp = self._call(api.get_race_predictions)
        if rp:
            db.set_snapshot("race_predictions", today.isoformat(), rp)
        lt = self._call(api.get_lactate_threshold)
        lthr = parse_lthr(lt)
        if lthr:
            db.set_snapshot("lthr", today.isoformat(), lthr)
        db.set_meta("last_sync", time.strftime("%Y-%m-%d %H:%M"))
        progress("Terminé", 1, 1)
        return stats
