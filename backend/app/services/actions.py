"""Calendar events and email drafts: propose -> user confirms -> written.

Nothing is written until the user confirms, and there is deliberately no code anywhere in this
project that sends email (the brief: "a follow-up email that is saved and never sent")."""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import ActionItem, CalendarEvent, EmailDraft, Insight, Mention, PendingAction, Recording, utcnow
from .timeparse import now_local, parse_iso

TOOLS = {"create_calendar_event", "draft_email"}
DEFAULT_HOUR = 10  # when a date is known but no time was said


class ActionError(Exception):
    pass


def _attendees(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = v.split(",")
    return [str(x).strip() for x in v if str(x).strip()][:30]


def normalize_args(tool: str, args: dict | None, final: bool = False) -> dict:
    """final=False: proposal (fields may still be incomplete, the user edits them in the card).
    final=True: confirmation (everything required must be present)."""
    args = dict(args or {})
    if tool == "create_calendar_event":
        title = str(args.get("title") or "").strip() or "Meeting"
        try:
            start = parse_iso(str(args.get("start") or ""))
        except ValueError:
            raise ActionError("event start must be a date and time (ISO 8601 with time zone)")
        end_raw = args.get("end")
        try:
            end = parse_iso(str(end_raw)) if end_raw else start + timedelta(minutes=30)
        except ValueError:
            end = start + timedelta(minutes=30)
        if end <= start:
            end = start + timedelta(minutes=30)
        return {"title": title[:200], "start": start.isoformat(), "end": end.isoformat(),
                "attendees": _attendees(args.get("attendees")), "notes": (str(args.get("notes") or "").strip() or None)}
    if tool == "draft_email":
        to = ", ".join(_attendees(args.get("to")))
        subject = str(args.get("subject") or "").strip()
        body = str(args.get("body") or "").strip()
        if final and not to:
            raise ActionError("add a recipient (To) before saving the draft")
        if not subject or not body:
            raise ActionError("an email draft needs a subject and a body")
        return {"to": to, "subject": subject[:300], "body": body}
    raise ActionError(f"unknown tool {tool}")


def propose(db: Session, tool: str, args: dict, source_recording_id: str | None,
            source_ref: str | None = None) -> PendingAction:
    if tool not in TOOLS:
        raise ActionError(f"unknown tool {tool}")
    pa = PendingAction(tool=tool, args=normalize_args(tool, args), source_recording_id=source_recording_id,
                       source_ref=source_ref)
    db.add(pa)
    db.commit()
    return pa


def confirm(db: Session, pa: PendingAction, edited: dict | None = None) -> PendingAction:
    if pa.status == "confirmed":
        return pa  # idempotent: a second confirm writes nothing
    if pa.status == "rejected":
        raise ActionError("this action was discarded")
    args = normalize_args(pa.tool, {**pa.args, **(edited or {})}, final=True)
    if pa.tool == "create_calendar_event":
        row = CalendarEvent(title=args["title"], start=args["start"], end=args["end"], attendees=args["attendees"],
                            notes=args.get("notes"), source_recording_id=pa.source_recording_id,
                            source_ref=pa.source_ref)
    else:
        row = EmailDraft(to_addr=args["to"], subject=args["subject"], body=args["body"],
                         source_recording_id=pa.source_recording_id, source_ref=pa.source_ref)
    db.add(row)
    db.flush()
    pa.args, pa.status, pa.result_id, pa.resolved_at = args, "confirmed", row.id, utcnow()
    db.commit()
    return pa


def reject(db: Session, pa: PendingAction) -> PendingAction:
    if pa.status == "confirmed":
        raise ActionError("already confirmed")
    pa.status, pa.resolved_at = "rejected", utcnow()
    db.commit()
    return pa


def pending_dict(pa: PendingAction) -> dict:
    return {"id": pa.id, "tool": pa.tool, "args": pa.args, "status": pa.status, "result_id": pa.result_id,
            "source_recording_id": pa.source_recording_id, "source_ref": pa.source_ref}


# ---- suggestions: things said in recordings that belong on the calendar -----------------------------
def _start_from(value: str | None, rec: Recording) -> str | None:
    """'2026-11-05' or '2026-11-05T15:00' -> ISO with the recording's offset."""
    if not value:
        return None
    tz = parse_iso(rec.recorded_at).tzinfo
    try:
        dt = datetime.fromisoformat(value[:16]) if "T" in value else datetime.fromisoformat(value[:10]).replace(hour=DEFAULT_HOUR)
    except ValueError:
        return None
    return dt.replace(tzinfo=tz).isoformat()


def _people(db: Session, rid: str) -> list[str]:
    return [m.value for m in db.query(Mention).filter_by(recording_id=rid, kind="person").all()]


def calendar_suggestions(db: Session) -> list[dict]:
    """Meetings mentioned in recordings (with a resolvable date) and action-item deadlines that are not on
    the calendar yet. Each one can be turned into a pending event and confirmed."""
    on_cal = {e.source_ref for e in db.query(CalendarEvent.source_ref).all() if e.source_ref}
    today = now_local().date().isoformat()
    recs = {r.id: r for r in db.query(Recording).all()}
    out = []
    for m in db.query(Mention).filter(Mention.kind == "meeting", Mention.normalized.isnot(None)).all():
        ref, rec = f"mention:{m.id}", recs.get(m.recording_id)
        if ref in on_cal or not rec or m.normalized[:10] < today:
            continue
        out.append({"ref": ref, "kind": "meeting", "title": m.value, "date": m.normalized[:10],
                    "start": _start_from(m.normalized, rec), "said_as": m.detail, "recording_id": rec.id,
                    "recording_title": rec.title, "recorded_at": rec.recorded_at, "segment_id": m.segment_id,
                    "attendees": _people(db, rec.id)})
    for a in db.query(ActionItem).filter(ActionItem.status == "open", ActionItem.due_date.isnot(None)).all():
        ref, rec = f"item:{a.id}", recs.get(a.recording_id)
        if ref in on_cal or not rec or a.due_date < today:
            continue
        out.append({"ref": ref, "kind": "deadline", "title": f"Due: {a.what} ({a.who})", "date": a.due_date,
                    "start": _start_from(a.due_date, rec), "said_as": a.due_text, "recording_id": rec.id,
                    "recording_title": rec.title, "recorded_at": rec.recorded_at, "segment_id": a.segment_id,
                    "attendees": [] if a.who.lower() in ("unassigned", "we", "i") else [a.who]})
    return sorted(out, key=lambda s: s["date"])


def propose_from_suggestion(db: Session, ref: str) -> PendingAction:
    s = next((x for x in calendar_suggestions(db) if x["ref"] == ref), None)
    if s is None:
        raise ActionError("suggestion not found or already on the calendar")
    notes = f"From “{s['recording_title']}”" + (f" — said as “{s['said_as']}”" if s.get("said_as") else "")
    return propose(db, "create_calendar_event",
                   {"title": s["title"], "start": s["start"], "attendees": s["attendees"], "notes": notes},
                   s["recording_id"], ref)


def followup_email_template(db: Session, rec: Recording, item: ActionItem | None = None) -> dict:
    """Deterministic follow-up draft (used when the LLM is unavailable, and as a starting point)."""
    ins = db.get(Insight, rec.id)
    people = [p for p in _people(db, rec.id)]
    items = [item] if item else db.query(ActionItem).filter_by(recording_id=rec.id).all()
    lines = [f"- {a.who}: {a.what}" + (f" (by {a.due_date or a.due_text})" if (a.due_date or a.due_text) else "")
             for a in items]
    title = rec.title or "our meeting"
    body = "Hi,\n\nThanks for the conversation" + (f" on {rec.local_date}" if rec.local_date else "") + ".\n\n"
    if ins and ins.summary and not item:
        body += ins.summary.strip() + "\n\n"
    if lines:
        body += "Next steps:\n" + "\n".join(lines) + "\n\n"
    body += "Best regards"
    to = item.who if item and item.who.lower() not in ("unassigned", "we", "i") else ", ".join(people[:1])
    return {"to": to, "subject": f"Follow-up: {item.what if item else title}"[:120], "body": body}
