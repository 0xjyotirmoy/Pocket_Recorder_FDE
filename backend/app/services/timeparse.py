import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .. import config

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"


def parse_iso(value: str) -> datetime:
    """Parse ISO 8601; the offset is mandatory."""
    if not value or not value.strip():
        raise ValueError("empty value")
    v = value.strip()
    if v.endswith("Z") or v.endswith("z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        raise ValueError("missing time zone offset")
    return dt


def now_local() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def resolve_relative(text: str | None, base: datetime) -> str | None:
    """Best-effort resolution of phrases like 'Thursday', 'tomorrow', '5 Nov' against base.
    Returns YYYY-MM-DD or None. The LLM resolves first; this is the fallback."""
    if not text:
        return None
    t = text.lower()
    d = base.date()

    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        r = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        return r.isoformat() if r else None
    if "day after tomorrow" in t:
        return (d + timedelta(days=2)).isoformat()
    if "tomorrow" in t:
        return (d + timedelta(days=1)).isoformat()
    if "yesterday" in t:
        return (d - timedelta(days=1)).isoformat()
    if re.search(r"\b(today|tonight|eod|end of (the )?day)\b", t):
        return d.isoformat()

    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH_RE}", t) or None
    day_month = None
    if m:
        day_month = (int(m[1]), MONTHS.index(m[2][:3]) + 1)
    else:
        m = re.search(rf"\b{_MONTH_RE}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", t)
        if m:
            day_month = (int(m[2]), MONTHS.index(m[1][:3]) + 1)
    if day_month:
        r = _safe_date(d.year, day_month[1], day_month[0])
        if r and (d - r).days > 180:
            r = _safe_date(d.year + 1, day_month[1], day_month[0])
        return r.isoformat() if r else None

    if "next week" in t:
        return (d + timedelta(days=7 - d.weekday())).isoformat()
    if re.search(r"\b(end of (the )?week|this week)\b", t):
        return (d + timedelta(days=(4 - d.weekday()) % 7)).isoformat()

    for i, name in enumerate(WEEKDAYS):
        if re.search(rf"\b{name[:3]}(?:{name[3:]})?\b", t):
            ahead = (i - d.weekday()) % 7 or 7
            if re.search(rf"\bnext\s+{name[:3]}", t) and ahead < 3:
                ahead += 7
            return (d + timedelta(days=ahead)).isoformat()
    return None


def valid_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def _closest_year(month: int, day: int, today: date) -> date | None:
    cands = [d for d in (_safe_date(today.year + k, month, day) for k in (-1, 0, 1)) if d]
    return min(cands, key=lambda c: abs((c - today).days)) if cands else None


def find_date_range(q: str, now: datetime) -> tuple[str | None, str | None, str]:
    """Find a date phrase in a search query. Returns (date_from, date_to, query_without_the_date).
    Understands 2026-11-03, 3 Nov, Nov 3rd, 3/11 (day/month), today, yesterday, tomorrow,
    last/this/next week, and weekday names (most recent one, for searching past meetings)."""
    text = q or ""
    t = text.lower()
    today = now.date()

    def done(a: date | None, b: date | None, m: re.Match) -> tuple[str | None, str | None, str]:
        rest = (text[:m.start()] + " " + text[m.end():]).strip()
        rest = re.sub(r"\b(on|of|from|in|at|dated?)\s*$", "", rest, flags=re.I).strip()
        return (a.isoformat() if a else None, (b or a).isoformat() if (b or a) else None, re.sub(r"\s+", " ", rest))

    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return done(_safe_date(int(m[1]), int(m[2]), int(m[3])), None, m)
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH_RE}(?:\s*,?\s*(\d{{4}}))?", t)
    if m:
        mo, dd = MONTHS.index(m[2][:3]) + 1, int(m[1])
        return done(_safe_date(int(m[3]), mo, dd) if m[3] else _closest_year(mo, dd, today), None, m)
    m = re.search(rf"\b{_MONTH_RE}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:\s*,?\s*(\d{{4}}))?", t)
    if m:
        mo, dd = MONTHS.index(m[1][:3]) + 1, int(m[2])
        return done(_safe_date(int(m[3]), mo, dd) if m[3] else _closest_year(mo, dd, today), None, m)
    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?\b", t)
    if m and 1 <= int(m[2]) <= 12:
        y = int(m[3]) + (2000 if m[3] and len(m[3]) == 2 else 0) if m[3] else None
        return done(_safe_date(y, int(m[2]), int(m[1])) if y else _closest_year(int(m[2]), int(m[1]), today), None, m)
    for word, delta in (("today", 0), ("yesterday", -1), ("tomorrow", 1)):
        m = re.search(rf"\b{word}\b", t)
        if m:
            return done(today + timedelta(days=delta), None, m)
    m = re.search(r"\b(last|this|next)\s+week\b", t)
    if m:
        monday = today - timedelta(days=today.weekday()) + timedelta(weeks={"last": -1, "this": 0, "next": 1}[m[1]])
        return done(monday, monday + timedelta(days=6), m)
    for i, name in enumerate(WEEKDAYS):
        m = re.search(rf"\b(?:last\s+)?{name[:3]}(?:{name[3:]})?\b", t)
        if m:
            back = (today.weekday() - i) % 7
            return done(today - timedelta(days=back), None, m)
    return None, None, text.strip()
