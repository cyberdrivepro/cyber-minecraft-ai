"""Shared clock helpers. The database stores naive UTC datetimes, so every
timestamp is produced timezone-aware and then made naive — the supported
replacement for the deprecated datetime.utcnow()."""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC 'now' (drop-in replacement for datetime.utcnow())."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
