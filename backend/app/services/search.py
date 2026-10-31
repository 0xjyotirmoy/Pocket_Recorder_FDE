import re

from sqlalchemy import text
from sqlalchemy.orm import Session

STOPWORDS = set("""a an the and or but if of to in on at by for with from as is are was were be been being do does did
i me my we our us you your he she it they them their this that these those what which who whom when where why how
can could would should will shall may might must have has had not no yes so than then there here about into over
please tell show give find any all some did say said says get got let lets just also very really much many more most
recording recordings meeting meetings call""".split())

HL_START, HL_END = "\u0002", "\u0003"  # highlight markers; the UI escapes text and turns these into <mark>


# Words, including Indic vowel signs/viramas (Python's \w alone splits Hindi/Bengali words at every matra)
_WORD = re.compile(r"[\w\u0900-\u0DFF\u200c\u200d]+", re.UNICODE)


def tokens(q: str) -> list[str]:
    return [t.strip("_") for t in _WORD.findall(q or "") if t.strip("_")]


def fts_query(q: str, mode: str = "AND") -> str | None:
    toks = tokens(q)
    if mode == "OR":
        toks = [t for t in toks if t.lower() not in STOPWORDS and len(t) > 1]
    if not toks:
        return None
    parts = []
    for t in toks[:16]:
        t = t.replace('"', "")
        parts.append(f'"{t}"*' if len(t) >= 4 else f'"{t}"')  # prefix match catches plurals/tenses
    return f" {mode} ".join(parts)


def search_segments(db: Session, q: str, date_from: str | None = None, date_to: str | None = None,
                    limit: int = 50, mode: str = "AND") -> list[dict]:
    match = fts_query(q, mode)
    if not match:
        return []
    where = ["segments_fts MATCH :q"]
    params: dict = {"q": match, "lim": limit}
    if date_from:
        where.append("r.local_date >= :df")
        params["df"] = date_from
    if date_to:
        where.append("r.local_date <= :dt")
        params["dt"] = date_to
    sql = f"""
        SELECT s.id AS segment_id, s.recording_id, s.start_s, s.end_s, s.text,
               r.title, r.recorded_at, r.local_date, r.original_name,
               snippet(segments_fts, 0, '{HL_START}', '{HL_END}', '…', 18) AS snippet,
               bm25(segments_fts) AS score
        FROM segments_fts
        JOIN segments s ON s.id = segments_fts.rowid
        JOIN recordings r ON r.id = s.recording_id
        WHERE {' AND '.join(where)}
        ORDER BY score
        LIMIT :lim"""
    rows = db.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def _text_hits(db: Session, q: str, date_from=None, date_to=None) -> list[dict]:
    """All words first; if nothing matches, any word."""
    hits = search_segments(db, q, date_from, date_to, mode="AND")
    return hits or search_segments(db, q, date_from, date_to, mode="OR")


def user_search(db: Session, q: str, date_from=None, date_to=None) -> dict:
    """Search box: a date phrase ("nov 3", "yesterday", "last week") becomes a date filter, the rest is
    searched in transcripts AND in recording metadata (title, topics, keywords, people, summary)."""
    from ..models import Mention, Recording
    from .serialize import insights_map, open_item_counts, recording_row
    from .timeparse import find_date_range, now_local

    qf, qt, rest = find_date_range(q, now_local())
    date_from, date_to = date_from or qf, date_to or qt
    words = [w.lower() for w in tokens(rest) if w.lower() not in STOPWORDS]

    ins = insights_map(db)
    people: dict[str, list[str]] = {}
    for m in db.query(Mention).filter(Mention.kind == "person").all():
        people.setdefault(m.recording_id, []).append(m.value)
    counts = open_item_counts(db)
    recs = []
    for r in db.query(Recording).order_by(Recording.recorded_at_utc.desc()).all():
        if date_from and not (date_from <= r.local_date <= (date_to or date_from)):
            continue
        i = ins.get(r.id)
        if words:
            meta = " ".join([r.title or "", r.device_id, " ".join(people.get(r.id, [])),
                             " ".join((i.topics or []) + (i.keywords or [])) if i else "",
                             (i.summary or "") if i else ""]).lower()
            if not all(w in meta for w in words):
                continue
        elif not date_from:
            continue
        recs.append(recording_row(r, counts.get(r.id, 0), i))

    hits = _text_hits(db, rest, date_from, date_to) if rest.strip() else []
    return {"query": q, "text": rest, "date_from": date_from, "date_to": date_to, "recordings": recs,
            "hits": [{k: h[k] for k in ("segment_id", "recording_id", "start_s", "end_s", "text", "title",
                                        "recorded_at", "local_date", "snippet")} | {"title": h["title"] or "Untitled clip"}
                     for h in hits]}
