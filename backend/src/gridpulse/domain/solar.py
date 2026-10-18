"""Approximate solar elevation (NOAA general solar position equations).

Used by the plausibility rule "PV at night is ~0". Accuracy of roughly +-1 degree is
more than enough to tell night from day. Reference: NOAA Global Monitoring Division,
"General Solar Position Calculations" (https://gml.noaa.gov/grad/solcalc/solareqns.PDF).
"""

from __future__ import annotations

import math
from datetime import datetime

from gridpulse.domain.timeutils import ensure_utc

# Geographic centre of Germany (approx.), used for country-level checks.
GERMANY_LAT = 51.16
GERMANY_LON = 10.45


def solar_elevation_deg(
    when: datetime, lat: float = GERMANY_LAT, lon: float = GERMANY_LON
) -> float:
    """Solar elevation angle in degrees above the horizon at ``when`` (aware)."""
    utc = ensure_utc(when)
    day_of_year = utc.timetuple().tm_yday
    hour = utc.hour + utc.minute / 60 + utc.second / 3600
    gamma = 2 * math.pi / 365 * (day_of_year - 1 + (hour - 12) / 24)
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    true_solar_minutes = hour * 60 + eqtime + 4 * lon
    hour_angle = math.radians(true_solar_minutes / 4 - 180)
    lat_r = math.radians(lat)
    cos_zenith = math.sin(lat_r) * math.sin(decl) + math.cos(lat_r) * math.cos(decl) * math.cos(
        hour_angle
    )
    cos_zenith = min(1.0, max(-1.0, cos_zenith))
    return 90.0 - math.degrees(math.acos(cos_zenith))


def is_night(when: datetime, *, margin_deg: float = -6.0) -> bool:
    """True if the sun is below ``margin_deg`` (default: civil twilight) over Germany.

    A country spans ~9 degrees of longitude, so only clearly dark instants count.
    """
    return solar_elevation_deg(when) < margin_deg
