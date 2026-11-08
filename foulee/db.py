"""Stockage local SQLite : activités, métriques quotidiennes, courses, instantanés Garmin."""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from .models import Race

ACT_COLS = ["id", "start", "date", "type", "name", "distance_m", "duration_s", "moving_s", "elev_gain", "elev_loss",
            "avg_hr", "max_hr", "avg_speed", "calories", "te_aero", "te_anaero", "garmin_load", "vo2max_garmin",
            "cadence", "z1", "z2", "z3", "z4", "z5", "te_label", "is_race", "raw"]
DAILY_COLS = ["date", "hrv_night", "hrv_weekly", "hrv_base_low", "hrv_base_high", "hrv_status", "rhr", "sleep_s",
              "deep_s", "light_s", "rem_s", "awake_s", "sleep_score", "bb_wake", "bb_high", "bb_low", "stress_avg",
              "readiness", "readiness_level", "recovery_min", "steps", "raw"]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY, start TEXT, date TEXT, type TEXT, name TEXT,
    distance_m REAL, duration_s REAL, moving_s REAL, elev_gain REAL, elev_loss REAL,
    avg_hr REAL, max_hr REAL, avg_speed REAL, calories REAL, te_aero REAL, te_anaero REAL,
    garmin_load REAL, vo2max_garmin REAL, cadence REAL, z1 REAL, z2 REAL, z3 REAL, z4 REAL, z5 REAL,
    te_label TEXT, is_race INTEGER DEFAULT 0, raw TEXT);
CREATE INDEX IF NOT EXISTS idx_act_date ON activities(date);
CREATE TABLE IF NOT EXISTS daily (
    date TEXT PRIMARY KEY, hrv_night REAL, hrv_weekly REAL, hrv_base_low REAL, hrv_base_high REAL,
    hrv_status TEXT, rhr REAL, sleep_s REAL, deep_s REAL, light_s REAL, rem_s REAL, awake_s REAL,
    sleep_score REAL, bb_wake REAL, bb_high REAL, bb_low REAL, stress_avg REAL, readiness REAL,
    readiness_level TEXT, recovery_min REAL, steps INTEGER, raw TEXT);
CREATE TABLE IF NOT EXISTS races (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, date TEXT, distance_km REAL, elevation_m REAL,
    kind TEXT, priority TEXT, technicity INTEGER, goal_s INTEGER, result_s INTEGER, notes TEXT);
CREATE TABLE IF NOT EXISTS snapshots (key TEXT PRIMARY KEY, date TEXT, value TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- activités --------------------------------------------------------------
    def upsert_activities(self, rows: list[dict]) -> None:
        q = f"INSERT OR REPLACE INTO activities ({','.join(ACT_COLS)}) VALUES ({','.join('?' * len(ACT_COLS))})"
        self.conn.executemany(q, [[r.get(c) for c in ACT_COLS] for r in rows])
        self.conn.commit()

    def activities(self, since: str | None = None) -> list[dict]:
        cols = ",".join(c for c in ACT_COLS if c != "raw")
        if since:
            cur = self.conn.execute(f"SELECT {cols} FROM activities WHERE date >= ? ORDER BY start", (since,))
        else:
            cur = self.conn.execute(f"SELECT {cols} FROM activities ORDER BY start")
        return [dict(r) for r in cur.fetchall()]

    def last_activity_date(self) -> str | None:
        r = self.conn.execute("SELECT MAX(date) FROM activities").fetchone()
        return r[0] if r else None

    # --- quotidien ---------------------------------------------------------------
    def upsert_daily(self, row: dict) -> None:
        q = f"INSERT OR REPLACE INTO daily ({','.join(DAILY_COLS)}) VALUES ({','.join('?' * len(DAILY_COLS))})"
        self.conn.execute(q, [row.get(c) for c in DAILY_COLS])
        self.conn.commit()

    def daily(self) -> list[dict]:
        cols = ",".join(c for c in DAILY_COLS if c != "raw")
        return [dict(r) for r in self.conn.execute(f"SELECT {cols} FROM daily ORDER BY date").fetchall()]

    def daily_dates(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT date FROM daily").fetchall()}

    # --- courses -----------------------------------------------------------------
    def races(self) -> list[Race]:
        out = []
        for r in self.conn.execute("SELECT * FROM races ORDER BY date").fetchall():
            out.append(Race(r["id"], r["name"], date.fromisoformat(r["date"]), r["distance_km"] or 0, r["elevation_m"] or 0,
                            r["kind"] or "trail", r["priority"] or "A", r["technicity"] or 3, r["goal_s"], r["result_s"],
                            r["notes"] or ""))
        return out

    def save_race(self, race: Race) -> int:
        vals = (race.name, race.date.isoformat(), race.distance_km, race.elevation_m, race.kind, race.priority,
                race.technicity, race.goal_s, race.result_s, race.notes)
        if race.id:
            self.conn.execute("UPDATE races SET name=?, date=?, distance_km=?, elevation_m=?, kind=?, priority=?, "
                              "technicity=?, goal_s=?, result_s=?, notes=? WHERE id=?", vals + (race.id,))
            rid = race.id
        else:
            rid = self.conn.execute("INSERT INTO races (name, date, distance_km, elevation_m, kind, priority, technicity, "
                                    "goal_s, result_s, notes) VALUES (?,?,?,?,?,?,?,?,?,?)", vals).lastrowid
        self.conn.commit()
        return rid

    def delete_race(self, rid: int) -> None:
        self.conn.execute("DELETE FROM races WHERE id=?", (rid,))
        self.conn.commit()

    # --- instantanés & méta -------------------------------------------------------
    def set_snapshot(self, key: str, day: str, value) -> None:
        self.conn.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?)", (key, day, json.dumps(value)))
        self.conn.commit()

    def snapshot(self, key: str):
        r = self.conn.execute("SELECT value FROM snapshots WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))
        self.conn.commit()

    def meta(self, key: str) -> str | None:
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def is_empty(self) -> bool:
        a = self.conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
        d = self.conn.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
        return a == 0 and d == 0
