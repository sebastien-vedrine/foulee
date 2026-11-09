"""Recherche de courses pour pré-remplir la fiche d'une course.

Trois sources :
- Garmin : courses du calendrier et parcours enregistrés, récupérés pendant la synchronisation ;
- catalogue UTMB World Series, interrogé en ligne (API publique de utmb.world) ;
- fichier GPX du parcours (distance et dénivelé calculés localement).
"""
from __future__ import annotations

import json
import math
import re
import ssl
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import __version__
from .metrics import fr

UTMB_URL = "https://api.utmb.world/search/races"
SOURCE_LABELS = {
    "garmin_event": "Calendrier Garmin",
    "garmin_course": "Parcours Garmin",
    "utmb": "UTMB World Series",
    "gpx": "Fichier GPX",
}
MONTHS_EN = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"], start=1)}
TRAIL_RATIO = 12.0          # m de D+ par km au-delà duquel une course est considérée comme un trail
GPX_HYSTERESIS_M = 4.0      # lissage du dénivelé GPX (filtre le bruit d'altitude)


class SearchError(Exception):
    pass


@dataclass
class RaceHit:
    source: str
    name: str
    date: date | None = None
    distance_km: float | None = None
    elevation_m: float | None = None
    kind: str | None = None          # "trail", "route" ou None (inconnu)
    location: str = ""
    goal_s: int | None = None

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    def summary(self) -> str:
        parts = []
        if self.date:
            parts.append(self.date.strftime("%d/%m/%Y"))
        if self.distance_km:
            parts.append(f"{fr(self.distance_km, 1).replace(',0', '')} km")
        if self.elevation_m:
            parts.append(f"{fr(self.elevation_m, 0)} m D+")
        if self.location:
            parts.append(self.location)
        return " · ".join(parts)


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Minuscules sans accents ni ponctuation, pour comparer des noms de courses."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def _tokens(query: str) -> list[str]:
    return normalize(query).split()


def match_score(query: str, *texts: str) -> int:
    """Nombre de mots de la requête présents dans les textes (0 si aucun)."""
    hay = " ".join(normalize(t) for t in texts if t)
    return sum(1 for tok in _tokens(query) if tok in hay)


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def _parse_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str) and len(v) >= 10:
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


def _to_km(value, unit) -> float | None:
    v = _num(value)
    if v is None:
        return None
    u = (unit or "").lower()
    if u in ("kilometer", "kilometers", "km"):
        return v
    if u in ("mile", "miles", "mi"):
        return v * 1.609344
    if u in ("meter", "meters", "m", "metre", "metres"):
        return v / 1000
    return v / 1000 if v > 500 else v   # unité absente : on devine


def guess_kind(type_key: str | None, distance_km: float | None, elevation_m: float | None) -> str | None:
    t = (type_key or "").lower()
    if any(k in t for k in ("trail", "hik", "mountain", "ultra")):
        return "trail"
    if any(k in t for k in ("road", "street", "track")):
        return "route"
    if distance_km and elevation_m is not None:
        return "trail" if elevation_m / distance_km >= TRAIL_RATIO else "route"
    return None


def _type_key(v) -> str:
    if isinstance(v, dict):
        return str(v.get("typeKey") or v.get("key") or "")
    return str(v or "")


# ---------------------------------------------------------------------------
# Garmin (données issues de la synchronisation)
# ---------------------------------------------------------------------------

def parse_garmin_event(e) -> RaceHit | None:
    """Course du calendrier Garmin (calendar-service/events)."""
    if not isinstance(e, dict):
        return None
    name = (e.get("eventName") or e.get("name") or e.get("title") or "").strip()
    if not name:
        return None
    d = _parse_date(e.get("date") or e.get("eventDate") or e.get("startDate"))
    dist = None
    ct = e.get("completionTarget")
    if isinstance(ct, dict) and (ct.get("unitType") or "distance") == "distance":
        dist = _to_km(ct.get("value"), ct.get("unit"))
    course = e.get("_course") if isinstance(e.get("_course"), dict) else {}
    dist = dist or _to_km(course.get("distance_m"), "meter")
    elev = _num(course.get("elevation_m"))
    goal = None
    cg = (e.get("eventCustomization") or {}).get("customGoal") if isinstance(e.get("eventCustomization"), dict) else None
    if isinstance(cg, dict) and ((cg.get("unitType") or "") == "time" or (cg.get("unit") or "") in ("second", "s")):
        g = _num(cg.get("value"))
        goal = int(g) if g else None
    loc = e.get("location") or ""
    if not isinstance(loc, str):
        loc = ""
    kind = guess_kind(_type_key(e.get("eventType") or e.get("activityType")), dist, elev)
    return RaceHit("garmin_event", name, d, dist, elev, kind, loc.strip(), goal)


def parse_garmin_course(c) -> RaceHit | None:
    """Parcours enregistré dans Garmin Connect (course-service)."""
    if not isinstance(c, dict):
        return None
    name = (c.get("courseName") or c.get("name") or "").strip()
    if not name:
        return None
    dist = _to_km(c.get("distanceInMeters") or c.get("distanceMeter"), "meter")
    elev = _num(c.get("elevationGainInMeters") or c.get("elevationGainMeter"))
    kind = guess_kind(_type_key(c.get("activityType")), dist, elev)
    return RaceHit("garmin_course", name, None, dist, elev, kind)


def trim_course(c: dict) -> dict:
    """Champs utiles d'un parcours Garmin (évite de stocker les tracés complets)."""
    keys = ("courseId", "courseName", "distanceInMeters", "elevationGainInMeters", "activityType", "updatedDate")
    return {k: c.get(k) for k in keys if k in c}


def garmin_hits(snapshot, today: date) -> list[RaceHit]:
    """Courses du calendrier (à venir d'abord) puis parcours Garmin, à partir de l'instantané de synchro."""
    snap = snapshot if isinstance(snapshot, dict) else {}
    events = [h for h in (parse_garmin_event(e) for e in snap.get("events") or []) if h]
    upcoming = sorted((h for h in events if not h.date or h.date >= today), key=lambda h: h.date or today)
    past = sorted((h for h in events if h.date and h.date < today), key=lambda h: h.date, reverse=True)
    courses = sorted((h for h in (parse_garmin_course(c) for c in snap.get("courses") or []) if h),
                     key=lambda h: normalize(h.name))
    return upcoming + past + courses


def filter_hits(hits: list[RaceHit], query: str) -> list[RaceHit]:
    """Garde les résultats contenant tous les mots de la requête (tous si la requête est vide)."""
    toks = _tokens(query)
    if not toks:
        return list(hits)
    return [h for h in hits if match_score(query, h.name, h.location) == len(toks)]


# ---------------------------------------------------------------------------
# Catalogue UTMB World Series
# ---------------------------------------------------------------------------

def parse_utmb_date(text) -> date | None:
    """« 6th November 2026 » → date."""
    m = re.match(r"\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})", text or "")
    if not m or m.group(2).lower() not in MONTHS_EN:
        return None
    try:
        return date(int(m.group(3)), MONTHS_EN[m.group(2).lower()], int(m.group(1)))
    except ValueError:
        return None


def parse_utmb(payload, query: str = "") -> list[RaceHit]:
    out = []
    for r in (payload or {}).get("races") or []:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        stats = {s.get("name"): s.get("value") for s in ((r.get("details") or {}).get("statsUp") or [])
                 if isinstance(s, dict)}
        loc = r.get("startLocation") or ""
        if not isinstance(loc, str) or loc.strip().lower() in ("undefined", "null", "none"):
            loc = ""
        out.append(RaceHit("utmb", " ".join(str(r["name"]).split()), parse_utmb_date(r.get("startDate")),
                           _num(stats.get("distance")), _num(stats.get("elevationGain")), "trail", loc.strip()))
    if query:
        # L'API renvoie aussi des courses ne contenant qu'un des mots : les plus pertinentes d'abord.
        out.sort(key=lambda h: -match_score(query, h.name, h.location))
        best = match_score(query, out[0].name, out[0].location) if out else 0
        if best:
            out = [h for h in out if match_score(query, h.name, h.location) == best]
    return out


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def search_utmb(query: str, limit: int = 30, timeout: float = 12) -> list[RaceHit]:
    query = query.strip()
    if len(query) < 3:
        return []
    url = UTMB_URL + "?" + urllib.parse.urlencode({"lang": "en", "limit": limit, "search": query})
    req = urllib.request.Request(url, headers={"User-Agent": f"Foulee/{__version__}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # réseau, HTTP, JSON
        raise SearchError(f"catalogue UTMB injoignable ({e})") from e
    return parse_utmb(payload, query)


# ---------------------------------------------------------------------------
# Fichier GPX
# ---------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(min(1.0, math.sqrt(h)))


def elevation_gain(elevations: list[float], threshold: float = GPX_HYSTERESIS_M) -> float:
    """D+ avec hystérésis : une montée n'est comptée qu'au-delà de `threshold` mètres (filtre le bruit)."""
    if not elevations:
        return 0.0
    gain, ref = 0.0, elevations[0]
    for e in elevations[1:]:
        if e - ref >= threshold:
            gain += e - ref
            ref = e
        elif ref - e >= threshold:
            ref = e
    return gain


def parse_gpx(source: str | Path | bytes) -> RaceHit:
    try:
        root = ET.fromstring(source) if isinstance(source, bytes) else ET.parse(str(source)).getroot()
    except (ET.ParseError, OSError) as e:
        raise SearchError(f"fichier GPX illisible ({e})") from e
    name = ""
    for el in root.iter():
        if _local(el.tag) == "name" and (el.text or "").strip():
            name = el.text.strip()
            break
    pts, eles = [], []
    for tag in ("trkpt", "rtept"):
        for el in root.iter():
            if _local(el.tag) != tag:
                continue
            try:
                pts.append((float(el.get("lat")), float(el.get("lon"))))
            except (TypeError, ValueError):
                continue
            ele = next((c.text for c in el if _local(c.tag) == "ele"), None)
            try:
                if ele is not None:
                    eles.append(float(ele))
            except ValueError:
                pass
        if pts:
            break
    if len(pts) < 2:
        raise SearchError("le fichier GPX ne contient pas de tracé")
    dist_km = sum(_haversine_m(pts[i - 1], pts[i]) for i in range(1, len(pts))) / 1000
    elev = elevation_gain(eles) if len(eles) >= 2 else None
    if not name and isinstance(source, (str, Path)):
        name = Path(source).stem.replace("_", " ")
    return RaceHit("gpx", name, None, round(dist_km, 1), round(elev) if elev is not None else None,
                   guess_kind("", dist_km, elev))
