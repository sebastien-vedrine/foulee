"""Tests hors ligne : python -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("FOULEE_HOME", tempfile.mkdtemp())

from foulee import metrics as M  # noqa: E402
from foulee.analysis import build  # noqa: E402
from foulee.coach import Coach, CoachContext, compute_phase, plan_days  # noqa: E402
from foulee.config import Settings  # noqa: E402
from foulee.db import Database  # noqa: E402
from foulee.demo import generate  # noqa: E402
from foulee.garmin_sync import parse_activity, parse_daily  # noqa: E402
from foulee.models import ActRec, Race  # noqa: E402
from foulee.readiness import Readiness  # noqa: E402

TODAY = date(2026, 11, 11)  # mercredi
ZONES = M.hr_zones(185, None, "reserve", 50)


def ctx(history=(), races=(), score=75, load=None, day=TODAY, **kw):
    r = Readiness(day, score) if score is not None else None
    if r is not None:
        r.hrv_z, r.rhr_delta = kw.pop("hrv_z", 0.0), kw.pop("rhr_delta", 0.0)
    s = Settings()
    for k, v in kw.items():
        setattr(s, k, v)
    return CoachContext(day, s, list(history), list(races), r, load or {"atl": 60, "ctl": 60, "tsb": 0, "acwr": 1.0},
                        ZONES, 48, M.training_paces(48))


class MetricsTest(unittest.TestCase):
    def test_daniels_table(self):
        self.assertAlmostEqual(M.race_time_from_vdot(50, 5000), 19 * 60 + 57, delta=3)
        self.assertAlmostEqual(M.race_time_from_vdot(50, 42195), 3 * 3600 + 10 * 60 + 49, delta=30)
        self.assertAlmostEqual(M.vdot_from_race(10000, 41 * 60 + 21), 50, delta=0.2)

    def test_effective_vo2(self):
        act = dict(type="running", duration_s=3600, moving_s=3600, distance_m=10000, avg_hr=140, elev_gain=0, elev_loss=0)
        v = M.effective_vo2max(act, 190)
        self.assertTrue(40 < v < 50)
        self.assertIsNone(M.effective_vo2max(dict(act, type="strength_training"), 190))
        steep = dict(act, elev_gain=900)
        self.assertIsNone(M.effective_vo2max(steep, 190))

    def test_load_and_monotony(self):
        days = {TODAY - timedelta(days=i): 80.0 for i in range(0, 60, 2)}
        ls = M.load_series(days, TODAY - timedelta(days=60), TODAY)
        self.assertGreater(ls.at(TODAY)["ctl"], 30)
        mono, strain = M.monotony_strain([50, 0, 50, 0, 50, 0, 50])
        self.assertLess(mono, 1.5)
        self.assertGreater(strain, 0)

    def test_trail_prognosis_grows_with_elevation(self):
        flat = M.predict_race(48, 50, 0, "trail", 3, 0.9)
        hilly = M.predict_race(48, 50, 3000, "trail", 3, 0.9)
        self.assertGreater(hilly, flat * 1.4)

    def test_zones_ordered(self):
        for z in (M.hr_zones(190), M.hr_zones(190, 170), M.hr_zones(190, None, "reserve", 50)):
            self.assertEqual(len(z), 5)
            self.assertTrue(all(z[i][2] < z[i + 1][1] + 1 for i in range(4)))


class ParseTest(unittest.TestCase):
    def test_parse_activity_and_daily(self):
        a = parse_activity({"activityId": 12, "startTimeLocal": "2026-11-07 08:30:00",
                            "activityType": {"typeKey": "trail_running"}, "distance": 21000, "duration": 9000,
                            "elevationGain": 900, "averageHR": 145, "hrTimeInZone_4": 600,
                            "eventType": {"typeKey": "race"}})
        self.assertEqual(a["date"], "2026-11-07")
        self.assertEqual(a["is_race"], 1)
        self.assertEqual(a["z4"], 600)
        d = parse_daily("2026-11-08",
                        {"hrvSummary": {"lastNightAvg": 55, "status": "BALANCED", "baseline": {"balancedLow": 48}}},
                        {"dailySleepDTO": {"sleepTimeSeconds": 25000, "sleepScores": {"overall": {"value": 80}}}},
                        {"restingHeartRate": 47, "bodyBatteryHighestValue": 85, "averageStressLevel": -1},
                        [{"score": 40, "timestampLocal": "2026-11-08T06:00"},
                         {"score": 70, "timestampLocal": "2026-11-08T07:00", "inputContext": "AFTER_WAKEUP_RESET"}])
        self.assertEqual(d["hrv_night"], 55)
        self.assertEqual(d["sleep_score"], 80)
        self.assertEqual(d["readiness"], 70)
        self.assertIsNone(d["stress_avg"])
        empty = parse_daily("2026-11-08", None, None, None, None)
        self.assertIsNone(empty["hrv_night"])


class CoachTest(unittest.TestCase):
    def test_red_readiness_means_rest(self):
        self.assertEqual(Coach(ctx(score=30)).suggest().kind, "REPOS")
        self.assertEqual(Coach(ctx(score=70, hrv_z=-2.0, rhr_delta=6)).suggest().kind, "REPOS")

    def test_no_slot_means_rest(self):
        tuesday = TODAY - timedelta(days=1)
        self.assertEqual(Coach(ctx(day=tuesday)).suggest().kind, "REPOS")

    def test_race_day_and_taper(self):
        race = Race(1, "Ultra", TODAY, 60, 3000)
        self.assertEqual(Coach(ctx(races=[race])).suggest().kind, "COURSE")
        race2 = Race(1, "Ultra", TODAY + timedelta(days=1), 60, 3000)
        self.assertIn("Activation", Coach(ctx(races=[race2])).suggest().title)
        self.assertEqual(compute_phase(TODAY, [Race(1, "U", TODAY + timedelta(days=10), 60, 3000)]).name, "affutage")

    def test_post_race_recovery(self):
        race = Race(1, "Ultra", TODAY - timedelta(days=2), 60, 3000)
        self.assertEqual(Coach(ctx(races=[race])).suggest().kind, "REPOS")

    def test_intervals_when_fresh(self):
        race = Race(1, "Marathon", TODAY + timedelta(days=80), 42.2, 100, "route")
        hist = [ActRec(TODAY - timedelta(days=4), "running", trimp=60, intensity="easy", duration_s=3600)]
        sug = Coach(ctx(history=hist, races=[race])).suggest()
        self.assertEqual(sug.kind, "FRACTIONNE")
        self.assertLessEqual(sug.duration_min, Settings().avail(TODAY.weekday()))

    def test_no_intervals_when_tired(self):
        hist = [ActRec(TODAY - timedelta(days=1), "running", trimp=150, intensity="hard", family="vo2")]
        sug = Coach(ctx(history=hist, score=55)).suggest()
        self.assertNotEqual(sug.kind, "FRACTIONNE")

    def test_overload_blocks_quality(self):
        sug = Coach(ctx(load={"atl": 120, "ctl": 70, "tsb": -50, "acwr": 1.7}, score=50)).suggest()
        self.assertEqual(sug.kind, "REPOS")

    def test_long_run_on_weekend(self):
        saturday = TODAY + timedelta(days=3)
        sug = Coach(ctx(day=saturday, races=[Race(1, "U", saturday + timedelta(days=70), 60, 3000)])).suggest()
        self.assertEqual(sug.intensity, "long")

    def test_week_plan_has_rest_and_quality(self):
        plan = plan_days(ctx(races=[Race(1, "U", TODAY + timedelta(days=70), 60, 3000)]), 7)
        kinds = [p.kind for p in plan]
        self.assertEqual(len(plan), 7)
        self.assertIn("REPOS", kinds)
        self.assertTrue({"FRACTIONNE", "RENFO"} & set(kinds))


class DemoIntegrationTest(unittest.TestCase):
    def test_build_on_demo(self):
        db = Database(":memory:")
        generate(db, TODAY)
        an = build(db, Settings(), TODAY)
        self.assertTrue(an.has_data)
        self.assertIsNotNone(an.vo2max)
        self.assertEqual(len(an.plan), 7)
        self.assertTrue(all(rv.prognosis_s for rv in an.race_views))


if __name__ == "__main__":
    unittest.main()
