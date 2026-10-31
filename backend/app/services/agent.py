"""Evidence-grounded question answering.

Flow: retrieve evidence (FTS5) -> one LLM call returning JSON with cited segment ids ->
server keeps only citations that exist in the evidence -> sources are built from the DB,
never from model text. No valid citation => the honest "not in recordings" answer."""
import logging
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from .. import config
from ..models import ActionItem, CalendarEvent, Insight, Mention, Recording, Segment
from ..providers.llm import LLMError, get_llm
from . import actions
from .extract import mmss
from .search import STOPWORDS, search_segments, tokens
from .serialize import display_title
from .timeparse import now_local, resolve_relative

log = logging.getLogger("agent")
SYSTEM = (Path(__file__).resolve().parents[1] / "prompts" / "agent.md").read_text(encoding="utf-8")
# An explicit request to act ("schedule the review call", "draft a mail to Ravi", "remind me..."),
# not a question that merely contains the word ("what's on my schedule?").
ACTION_WORDS = re.compile(
    r"(^\s*(please\s+|pls\s+)?((can|could|would|will) you\s+)?(schedule|book|add|set ?up|create|remind|draft|write|"
    r"send|mail|e-?mail|prepare|compose|plan)\b)"
    r"|(\b(add|put)\b.*\bcalendar\b)"
    r"|(\b(draft|write|prepare|send|compose)\b.{0,25}\b(e-?mails?|mails?|message|note|reply)\b)"
    r"|(\bremind(er)?\b)"
    r"|(\bschedule\s+(a|an|the|my|meeting|call|review|demo|sync|follow|mail|email))", re.I)
MAX_EVIDENCE = 40
SCHEDULE_WORDS = re.compile(r"\b(schedule|agenda|calendar|upcoming|meeting|meetings|when|next week|this week|tomorrow|plan|deadline|due)\b", re.I)


# ---- tools (also usable directly; names follow the brief) -------------------------------------
def search_transcripts(db: Session, query: str, date_from=None, date_to=None, limit=12) -> list[dict]:
    return search_segments(db, query, date_from, date_to, limit=limit, mode="OR")


def get_recording(db: Session, rid: str) -> Recording | None:
    return db.get(Recording, rid)


def list_action_items(db: Session, status: str | None = "open") -> list[ActionItem]:
    q = db.query(ActionItem)
    if status:
        q = q.filter(ActionItem.status == status)
    return q.order_by(ActionItem.due_date.is_(None), ActionItem.due_date).limit(40).all()


# ---- retrieval -----------------------------------------------------------------------------------
def _keywords(text: str) -> set[str]:
    return {t.lower() for t in tokens(text) if t.lower() not in STOPWORDS and len(t) > 2}


def retrieve(db: Session, message: str, history: list[dict]) -> dict[int, Segment]:
    found: dict[int, Segment] = {}

    def add_ids(ids):
        for s in db.query(Segment).filter(Segment.id.in_(list(ids))).all():
            found.setdefault(s.id, s)

    hits = search_transcripts(db, message, limit=12)
    if len(hits) < 3 and history:  # follow-up questions: borrow words from the last user turn
        prev = " ".join(h.get("content", "") for h in history[-4:] if h.get("role") == "user")
        hits += search_transcripts(db, prev, limit=6)
    hit_ids = [h["segment_id"] for h in hits]
    add_ids(hit_ids)

    # neighbours for context (+/-1 segment)
    for s in list(found.values()):
        for n in db.query(Segment).filter(Segment.recording_id == s.recording_id,
                                          Segment.idx.in_([s.idx - 1, s.idx + 1])).all():
            found.setdefault(n.id, n)

    # recordings named by title or by date ("the vendor call", "on 3 Nov", "yesterday")
    words = _keywords(message)
    day = resolve_relative(message, now_local())
    for rec in db.query(Recording).filter(Recording.status == "done").all():
        title_words = _keywords(rec.title or "")
        if (words & title_words) or (day and rec.local_date == day):
            for s in (db.query(Segment).filter_by(recording_id=rec.id).order_by(Segment.idx).limit(25).all()):
                found.setdefault(s.id, s)
        if len(found) >= MAX_EVIDENCE:
            break

    # action items are evidence too (each points at a segment)
    if re.search(r"\b(task|todo|to-do|action|promise|owe|due|deadline|follow.?up|pending|open)\b", message, re.I):
        add_ids([a.segment_id for a in list_action_items(db) if a.segment_id])

    # schedule questions ("what's on my schedule next week?"): meetings and deadlines mentioned in recordings
    if SCHEDULE_WORDS.search(message):
        ids = [m.segment_id for m in db.query(Mention).filter(Mention.kind == "meeting", Mention.segment_id.isnot(None)).all()]
        ids += [a.segment_id for a in list_action_items(db) if a.segment_id and a.due_date]
        add_ids(ids[:30])

    if len(found) > MAX_EVIDENCE:
        keep = set(hit_ids[:MAX_EVIDENCE])
        ordered = sorted(found.values(), key=lambda s: (s.id not in keep,))
        found = {s.id: s for s in ordered[:MAX_EVIDENCE]}
    return found


def _recordings_context(db: Session) -> str:
    rows = []
    for rec in db.query(Recording).order_by(Recording.recorded_at_utc.desc()).limit(30).all():
        ins = db.get(Insight, rec.id)
        summary = (ins.summary[:240] if ins and ins.summary else "").replace("\n", " ")
        rows.append(f"- {display_title(rec)} | {rec.recorded_at} | {rec.status} | {summary}")
    return "\n".join(rows) or "(none)"


def _evidence_block(db: Session, segs: dict[int, Segment]) -> str:
    recs = {r.id: r for r in db.query(Recording).filter(Recording.id.in_({s.recording_id for s in segs.values()})).all()}
    ordered = sorted(segs.values(), key=lambda s: (recs[s.recording_id].recorded_at_utc, s.idx))
    return "\n".join(
        f"[S{s.id}] {display_title(recs[s.recording_id])} | {recs[s.recording_id].recorded_at} | {mmss(s.start_s)}: {s.text}"
        for s in ordered)


def _schedule_block(db: Session, segs: dict[int, Segment]) -> str:
    rows = [f"- [S{m.segment_id}] {m.value} — {m.normalized or 'date unresolved'} (said as: {m.detail or 'n/a'})"
            for m in db.query(Mention).filter(Mention.kind == "meeting").all() if m.segment_id in segs]
    rows += [f"- (calendar, user-confirmed) {e.title} — {e.start}" for e in
             db.query(CalendarEvent).filter(CalendarEvent.start >= now_local().date().isoformat())
             .order_by(CalendarEvent.start).limit(15).all()]
    return "\n".join(rows) or "(none)"


def _items_block(db: Session, segs: dict[int, Segment]) -> str:
    rows = [f"- [S{a.segment_id}] {a.who}: {a.what} (due {a.due_date or a.due_text or 'unspecified'})"
            for a in list_action_items(db) if a.segment_id in segs]
    return "\n".join(rows) or "(none)"


def _sources(db: Session, ids: list[int]) -> list[dict]:
    out = []
    for sid in ids:
        s = db.get(Segment, sid)
        if not s:
            continue
        rec = db.get(Recording, s.recording_id)
        out.append({"segment_id": s.id, "recording_id": rec.id, "title": display_title(rec),
                    "recorded_at": rec.recorded_at, "start_s": s.start_s, "text": s.text})
    return out


def _abstain(db: Session, message: str, extra: str = "") -> dict:
    # "closest moments" come only from the question's own words, never from earlier turns
    related = _sources(db, [h["segment_id"] for h in search_transcripts(db, message, limit=3)])
    return {"answer": config.ABSTAIN + extra, "grounded": False, "sources": [], "related": related,
            "pending_action": None}


EMAIL_WORDS = re.compile(r"\b(e-?mails?|mails?|draft|write to|message to|follow.?up (note|email|mail))\b", re.I)
ACTION_PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "action.md").read_text(encoding="utf-8")


def _validate_citations(out: dict, segs: dict[int, Segment]) -> tuple[list[int], str]:
    raw = list(out.get("cited_segment_ids") or [])
    raw += [int(x) for x in re.findall(r"\[S(\d+)\]", str(out.get("answer") or ""))]
    valid: list[int] = []
    for x in raw:
        try:
            x = int(str(x).lstrip("Ss"))
        except ValueError:
            continue
        if x in segs and x not in valid:  # a citation must point at evidence we actually supplied
            valid.append(x)
    text = re.sub(r"\s*\[S\d+\](?:\s*,?\s*\[S\d+\])*", "", str(out.get("answer") or "")).strip()
    return valid, text


def _context(db: Session, message: str, history: list[dict], segs: dict[int, Segment]) -> str:
    convo = "\n".join(f"{h.get('role', 'user').upper()}: {str(h.get('content', ''))[:600]}" for h in history)
    people = sorted({m.value for m in db.query(Mention).filter(Mention.kind == "person").all()})
    return (f"NOW: {now_local().isoformat(timespec='minutes')}\n\nRECORDINGS:\n{_recordings_context(db)}\n\n"
            f"PEOPLE MENTIONED: {', '.join(people) or '(none)'}\n\n"
            f"EVIDENCE:\n{_evidence_block(db, segs) if segs else '(none)'}\n\n"
            f"OPEN ACTION ITEMS:\n{_items_block(db, segs)}\n\n"
            f"MEETINGS / DATES MENTIONED AND CALENDAR:\n{_schedule_block(db, segs)}\n\n"
            f"CONVERSATION:\n{convo or '(start)'}\n\nQUESTION: {message}")


def _fallback_action(db: Session, message: str, segs: dict[int, Segment]) -> tuple[str, dict, str | None]:
    """Deterministic action when the model gives none: never leave an explicit request without a card."""
    rid = None
    if segs:
        rid = Counter(s.recording_id for s in segs.values()).most_common(1)[0][0]
    rec = db.get(Recording, rid) if rid else db.query(Recording).order_by(Recording.recorded_at_utc.desc()).first()
    if EMAIL_WORDS.search(message):
        if rec is None:
            return "draft_email", {"to": "", "subject": "Follow-up", "body": "Hi,\n\n\n\nBest regards"}, None
        return "draft_email", actions.followup_email_template(db, rec), rec.id
    now = now_local()
    day = resolve_relative(message, now)
    for sug in actions.calendar_suggestions(db):  # a meeting mentioned in recordings that matches the request
        if (day and sug["date"] == day) or _keywords(sug["title"]) & _keywords(message):
            return "create_calendar_event", {"title": sug["title"], "start": sug["start"],
                                             "attendees": sug["attendees"]}, sug["recording_id"]
    hour = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", message, re.I)
    h, mnt = (int(hour[1]) % 12 + (12 if hour[3].lower() == "pm" else 0), int(hour[2] or 0)) if hour else (10, 0)
    base = datetime.fromisoformat(day) if day else (now + timedelta(days=1)).replace(tzinfo=None)
    start = base.replace(hour=h, minute=mnt, second=0, microsecond=0).replace(tzinfo=now.tzinfo)
    title = re.sub(r"(?i)\b(please|can you|could you|schedule|add|book|create|set up|a|an|the|to|my|calendar|event|on|at|for)\b", " ", message)
    title = re.sub(r"\s+", " ", re.sub(r"\d{1,2}(:\d{2})?\s*(am|pm)", "", title, flags=re.I)).strip(" ?.,") or "Meeting"
    return "create_calendar_event", {"title": title[:80].capitalize(), "start": start.isoformat()}, rec.id if rec else None


def _plan_action(db: Session, message: str, history: list[dict], segs: dict[int, Segment]) -> dict:
    tool, args, text, valid = None, {}, "", []
    try:
        out = get_llm().complete_json(ACTION_PROMPT, _context(db, message, history, segs))
        valid, text = _validate_citations(out, segs)
        if out.get("tool") in actions.TOOLS and isinstance(out.get("args"), dict):
            tool, args = out["tool"], out["args"]
    except LLMError as e:
        log.warning("action planner failed, using fallback: %s", e)
    src = segs[valid[0]].recording_id if valid else None
    if tool is None:
        tool, args, src = _fallback_action(db, message, segs)
        text = text or ("Here's a draft email based on the recordings. Edit anything, then save it."
                        if tool == "draft_email" else "Here's the event. Check the date and time, then confirm.")
    try:
        pa = actions.propose(db, tool, args, src)
    except actions.ActionError:
        tool, args, src = _fallback_action(db, message, segs)
        pa = actions.propose(db, tool, args, src)
    return {"answer": text or "Please confirm the action below.", "grounded": bool(valid),
            "sources": _sources(db, valid), "related": [], "pending_action": actions.pending_dict(pa)}


def answer(db: Session, message: str, history: list[dict] | None = None) -> dict:
    message = (message or "").strip()
    if not message:
        raise ValueError("message is empty")
    history = [h for h in (history or []) if isinstance(h, dict)][-8:]
    segs = retrieve(db, message, history)

    if ACTION_WORDS.search(message):
        return _plan_action(db, message, history, segs)  # always ends in a confirm card

    if not segs:
        return _abstain(db, message)  # nothing to ground on: do not even ask the model
    out = get_llm().complete_json(SYSTEM, _context(db, message, history, segs))
    valid, text = _validate_citations(out, segs)
    if not valid:
        return _abstain(db, message)
    return {"answer": text, "grounded": True, "sources": _sources(db, valid), "related": [], "pending_action": None}
