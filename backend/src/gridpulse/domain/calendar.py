"""Calendar features for the own forecasting model (phase 7, ADR 0010).

Load follows the local clock and working days, so features are derived in
Europe/Berlin: hour of day, weekday (0 = Monday) and German nationwide public
holidays. Regional holidays are ignored (they shift national load only slightly).
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from gridpulse.domain.timeutils import BERLIN


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm, Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day + 1)


def german_public_holidays(year: int) -> frozenset[date]:
    """Public holidays observed in all German federal states."""
    easter = easter_sunday(year)
    return frozenset(
        {
            date(year, 1, 1),  # Neujahr
            easter - timedelta(days=2),  # Karfreitag
            easter + timedelta(days=1),  # Ostermontag
            date(year, 5, 1),  # Tag der Arbeit
            easter + timedelta(days=39),  # Christi Himmelfahrt
            easter + timedelta(days=50),  # Pfingstmontag
            date(year, 10, 3),  # Tag der Deutschen Einheit
            date(year, 12, 25),
            date(year, 12, 26),
        }
    )


def calendar_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    """``hour``, ``weekday`` and ``holiday`` (0/1) in Europe/Berlin for a UTC index."""
    if index.tz is None:
        raise ValueError("calendar features need a timezone-aware index")
    local = index.tz_convert(BERLIN)
    holidays: set[date] = set()
    for year in sorted(set(local.year)):
        holidays |= german_public_holidays(int(year))
    return pd.DataFrame(
        {
            "hour": local.hour.astype("int64"),
            "weekday": local.weekday.astype("int64"),
            "holiday": [int(d in holidays) for d in local.date],
        },
        index=index,
    )
