# -*- encoding: utf-8 -*-
"""
Local-time helper for stored timestamps.

The mobile app stores business timestamps (orders, dealer visits) in local wall
time rather than UTC, so the value read straight from the database — or shown in
the app — is already the on-the-ground time. Deployment is single-timezone
(India, no DST), which is what makes a fixed offset safe.

JWT token times are deliberately NOT local: those stay UTC (see tokens.py), since
they are epoch security claims, not display times.
"""

import os
from datetime import datetime, timedelta, timezone

# Default to IST (+05:30). Override with APP_UTC_OFFSET_MINUTES if the deployment
# ever moves timezones.
_OFFSET_MIN = int(os.getenv('APP_UTC_OFFSET_MINUTES', str(5 * 60 + 30)))
_LOCAL = timezone(timedelta(minutes=_OFFSET_MIN))


def now_local():
    """Current local wall-clock time as a naive datetime (no tzinfo), suitable
    for inserting into a MySQL DATETIME column so the stored value is local."""
    return datetime.now(_LOCAL).replace(tzinfo=None)
