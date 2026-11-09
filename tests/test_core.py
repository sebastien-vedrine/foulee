"""Tests hors ligne : python -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("FOULEE_HOME", tempfile.mkdtemp())

from foulee import metrics as M  # noqa: E402
from foulee import race_search as RS  # noqa: E402
from foulee.form import assess as assess_form  # noqa: E402
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


ALL_DAYS = {str(i): 90 for i in range(7)}
MONDAY = TODAY - timedelta(days=TODAY.weekday())


def runs_in(plan):
    return [p.day for p in plan if p.intensity in ("easy", "long", "hard", "race")]


def run_history(per_week: int, weeks: int = 8):
    """Historique régulier : `per_week` footings par semaine (lun, mer, ven, dim, mar, jeu, sam)."""
    order = [0, 2, 4, 6, 1, 3, 5][:per_week]
    out = []
    for w in range(1, weeks + 1):
        start = MONDAY - timedelta(weeks=w)
        out += [ActRec(start + timedelta(days=d), "running", "footing", 3000, 8, 50, "easy") for d in order]
    return out


class RunsPerWeekTest(unittest.TestCase):
    def test_fixed_number_is_respected_and_spread(self):
        plan = plan_days(ctx(day=MONDAY, availability=dict(ALL_DAYS), runs_per_week=3), 7)
        days = runs_in(plan)
        self.assertEqual(len(days), 3)
        gaps = [(b - a).days for a, b in zip(days, days[1:])]
        self.assertTrue(all(g >= 2 for g in gaps), days)

    def test_auto_without_race_is_three(self):
        plan = plan_days(ctx(day=MONDAY, history=run_history(5), availability=dict(ALL_DAYS)), 7)
        self.assertEqual(len(runs_in(plan)), 3)
        self.assertEqual(Coach(ctx(day=MONDAY, history=run_history(5))).run_target(), (3, True))

    def test_auto_grows_by_one_towards_a_race(self):
        race = Race(1, "U", MONDAY + timedelta(days=80), 60, 3000)   # phase développement
        c = Coach(ctx(day=MONDAY, history=run_history(3), races=[race], availability=dict(ALL_DAYS)))
        self.assertEqual(c.phase.name, "developpement")
        self.assertEqual(c.run_target(), (4, True))
        c = Coach(ctx(day=MONDAY, history=run_history(6), races=[race], availability=dict(ALL_DAYS)))
        self.assertEqual(c.run_target(), (5, True))

    def test_target_capped_by_available_days(self):
        avail = {"0": 0, "1": 0, "2": 60, "3": 0, "4": 0, "5": 0, "6": 120}
        self.assertEqual(Coach(ctx(day=MONDAY, availability=avail, runs_per_week=5)).run_target(), (2, False))

    def test_off_day_offers_strength_or_rest(self):
        plan = plan_days(ctx(day=MONDAY, availability=dict(ALL_DAYS), runs_per_week=3, strength_per_week=1), 7)
        off = [p for p in plan if p.intensity in ("rest", "strength")]
        self.assertEqual(len(off), 4)
        self.assertEqual(sum(1 for p in off if p.kind == "RENFO"), 1)


class RaceSearchTest(unittest.TestCase):
    def test_garmin_event_and_course(self):
        ev = {"eventName": "Trail des Écureuils", "date": "2027-03-14", "location": "Annecy",
              "completionTarget": {"value": 42000.0, "unit": "meter", "unitType": "distance"},
              "eventType": "trail_running", "_course": {"distance_m": 41800, "elevation_m": 2100},
              "eventCustomization": {"customGoal": {"value": 18000, "unit": "second", "unitType": "time"}}}
        h = RS.parse_garmin_event(ev)
        self.assertEqual((h.name, h.date, h.distance_km, h.elevation_m, h.kind, h.goal_s),
                         ("Trail des Écureuils", date(2027, 3, 14), 42.0, 2100, "trail", 18000))
        c = RS.parse_garmin_course({"courseName": "UTMB ETM 50k Mallorca", "distanceInMeters": 55431.96,
                                    "elevationGainInMeters": 2289.38, "activityType": {"typeKey": "running"}})
        self.assertAlmostEqual(c.distance_km, 55.43, places=2)
        self.assertEqual(c.kind, "trail")    # 41 m de D+ par km
        self.assertIsNone(RS.parse_garmin_event({"date": "2027-01-01"}))

    def test_garmin_hits_order_and_filter(self):
        snap = {"events": [{"eventName": "Passée", "date": "2026-01-10"}, {"eventName": "Future", "date": "2027-01-10"}],
                "courses": [{"courseName": "Écotrail Paris 45 km", "distanceInMeters": 45000}]}
        hits = RS.garmin_hits(snap, TODAY)
        self.assertEqual([h.name for h in hits], ["Future", "Passée", "Écotrail Paris 45 km"])
        self.assertEqual([h.name for h in RS.filter_hits(hits, "ecotrail paris")], ["Écotrail Paris 45 km"])
        self.assertEqual(RS.garmin_hits(None, TODAY), [])

    def test_utmb_payload(self):
        payload = {"races": [
            {"name": "HOKA UTMB Mont-Blanc - CCC", "startDate": "27th August 2027", "startLocation": "undefined",
             "details": {"statsUp": [{"name": "distance", "value": "101.00"}, {"name": "elevationGain", "value": 6050}]}},
            {"name": "Lavaredo Ultra Trail - 20K", "startDate": "24th June 2027", "startLocation": "Cortina",
             "details": {"statsUp": [{"name": "distance", "value": 20}]}}]}
        hits = RS.parse_utmb(payload, "ccc mont blanc")
        self.assertEqual(len(hits), 1)
        self.assertEqual((hits[0].date, hits[0].distance_km, hits[0].elevation_m, hits[0].location),
                         (date(2027, 8, 27), 101.0, 6050, ""))
        self.assertEqual(RS.parse_utmb_date("1st May 2027"), date(2027, 5, 1))
        self.assertIsNone(RS.parse_utmb_date("bientôt"))

    def test_gpx(self):
        pts = "".join(f'<trkpt lat="45.0" lon="{6 + i * 0.001:.3f}"><ele>{e}</ele></trkpt>'
                      for i, e in enumerate([1000, 1001, 1000, 1010, 1020, 1015, 1030]))
        gpx = (f'<?xml version="1.0"?><gpx xmlns="http://www.topografix.com/GPX/1/1"><metadata><name>Mon trail</name>'
               f'</metadata><trk><trkseg>{pts}</trkseg></trk></gpx>').encode()
        h = RS.parse_gpx(gpx)
        self.assertEqual(h.name, "Mon trail")
        self.assertAlmostEqual(h.distance_km, 0.5, delta=0.05)   # 6 × 78,7 m
        self.assertEqual(h.elevation_m, 35)                      # bruit de ±1 m ignoré : 1000 → 1020 puis 1015 → 1030
        with self.assertRaises(RS.SearchError):
            RS.parse_gpx(b"<gpx></gpx>")


class FormTest(unittest.TestCase):
    def test_alert_when_hrv_crashes_and_rhr_rises(self):
        r = Readiness(TODAY, 40)
        r.hrv_z, r.rhr_delta = -2.0, 6
        fm = assess_form(TODAY, r, {}, {}, {"tsb": 0, "ctl": 50, "acwr": 1.0})
        self.assertEqual(fm.state, "alerte")
        self.assertIn("VFC sous ta normale", fm.negatives)

    def test_energetic_and_tired(self):
        good = Readiness(TODAY, 85)
        good.hrv_z, good.rhr_delta, good.sleep_h = 0.8, -3, 7.8
        fm = assess_form(TODAY, good, {}, {TODAY: {"bb_wake": 90}}, {"tsb": 8, "ctl": 50, "acwr": 0.9})
        self.assertEqual(fm.state, "energique")
        self.assertEqual(fm.negatives, [])
        self.assertTrue(fm.measured)
        bad = Readiness(TODAY, 38)
        self.assertEqual(assess_form(TODAY, bad, {}, {}, {"tsb": -30, "ctl": 50}, 5, feminine=True).title, "Fatiguée")

    def test_without_health_data(self):
        fm = assess_form(TODAY, None, {}, {}, {"tsb": -28, "ctl": 60, "acwr": 1.5})
        self.assertFalse(fm.measured)
        self.assertIn("Pas de mesure santé", fm.message)
        self.assertEqual(assess_form(TODAY, None, {}, {}, {}).state, "inconnue")

    def test_trend(self):
        hist = {TODAY - timedelta(days=i): Readiness(TODAY - timedelta(days=i), 80 if i <= 2 else 60) for i in range(10)}
        fm = assess_form(TODAY, hist[TODAY], hist, {}, {"tsb": 0, "ctl": 50})
        self.assertIn("remonte", fm.message)


class DemoIntegrationTest(unittest.TestCase):
    def test_build_on_demo(self):
        db = Database(":memory:")
        generate(db, TODAY)
        an = build(db, Settings(), TODAY)
        self.assertTrue(an.has_data)
        self.assertIsNotNone(an.vo2max)
        self.assertEqual(len(an.plan), 7)
        self.assertTrue(all(rv.prognosis_s for rv in an.race_views))
        self.assertIsNotNone(an.form)
        self.assertTrue(an.form.title)


if __name__ == "__main__":
    unittest.main()
