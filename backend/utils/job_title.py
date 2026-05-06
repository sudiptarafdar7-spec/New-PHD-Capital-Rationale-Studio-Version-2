"""Shared helper for building canonical job titles.

Single source of truth for the unified job-title format used across every
tool (Media / Premium / Manual / Bulk / Transcript / Voice Typing /
AI Transcribe / Media Presence) and rendered by the dashboard.

Format: ``{Platform} - {Channel} - {DD-MM-YYYY} - {HH:MM}``

The frontend swaps the leading ``{Platform}`` text for an icon when it
displays the title, but the stored string keeps the platform label so
it remains useful for search, activity logs, and PDF filenames.
"""
from datetime import date as _date_t, datetime as _dt, time as _time_t


def _fmt_date(d) -> str:
    """Return ``DD-MM-YYYY`` for a date / datetime / ISO string."""
    if d is None or d == "":
        return ""
    if isinstance(d, _dt):
        return d.strftime("%d-%m-%Y")
    if isinstance(d, _date_t):
        return d.strftime("%d-%m-%Y")
    s = str(d).strip()
    # Accept the two formats we actually emit: ISO ``YYYY-MM-DD`` and the
    # already-formatted ``DD-MM-YYYY`` (idempotent).
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return _dt.strptime(s, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    return s  # unknown shape — return as-is rather than raise


def _fmt_time(t) -> str:
    """Return ``HH:MM`` (24h) for a time / datetime / string."""
    if t is None or t == "":
        return ""
    if isinstance(t, _dt):
        return t.strftime("%H:%M")
    if isinstance(t, _time_t):
        return t.strftime("%H:%M")
    s = str(t).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return _dt.strptime(s, fmt).strftime("%H:%M")
        except ValueError:
            continue
    # ``HH:MM:SS.micro`` etc. — keep the first 5 chars if they look like time.
    if len(s) >= 5 and s[2] == ":":
        return s[:5]
    return s


def build_job_title(platform, channel_name, call_date, call_time) -> str:
    """Compose the canonical job title.

    Empty / missing components are dropped so the dash separator never
    leaves a dangling ``- -`` for jobs that genuinely lack a field
    (e.g. legacy rows with no time).
    """
    parts = [
        (platform or "").strip() or None,
        (channel_name or "").strip() or None,
        _fmt_date(call_date) or None,
        _fmt_time(call_time) or None,
    ]
    return " - ".join(p for p in parts if p)
