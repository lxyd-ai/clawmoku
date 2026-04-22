"""
Tiny helper for serializing DB timestamps to timezone-aware ISO strings.

Why this exists
---------------
We write timestamps with `datetime.now(timezone.utc)` (UTC-aware) and the
ORM columns are declared `DateTime(timezone=True)`. That's correct on
Postgres. But on SQLite — which we use in prod — the backend only stores
the text and hands back *naive* datetimes when you read them. Calling
`.isoformat()` on a naive datetime produces a string without any tz
suffix, e.g. ``"2026-04-22T07:32:59.001740"``.

When the browser then does ``new Date("2026-04-22T07:32:59.001740")``,
ECMAScript parses tz-less datetimes as *local time*. A client in UTC+8
therefore sees every backend timestamp as 8 hours in the past. The most
visible symptom is the lobby "attendance light" — an agent that just
long-polled 2 s ago appears as `离线` because 2 s + 8 h is well outside
the 40 s freshness window.

Fix: always emit UTC with an explicit ``+00:00`` suffix. Treat any naive
datetime coming out of the ORM as UTC (which matches how we wrote it).

Use `iso_utc()` for every timestamp field in API responses.
"""

from __future__ import annotations

from datetime import datetime, timezone


def iso_utc(dt: datetime | None) -> str | None:
    """Return ``dt`` as an ISO-8601 string with an explicit UTC offset.

    * ``None`` → ``None`` (so callers can forward optional fields directly).
    * tz-aware datetime → converted to UTC, formatted with ``+00:00``.
    * naive datetime → assumed to already be UTC (that's how we store it),
      stamped with ``tzinfo=UTC`` before formatting.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()
