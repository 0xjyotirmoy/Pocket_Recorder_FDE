from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import ActionItem, CalendarEvent, EmailDraft, Insight, Mention, Recording, Segment


def display_title(rec: Recording) -> str:
    return rec.title or f"Clip from {rec.device_id}"


def recording_row(rec: Recording, open_items: int = 0, insight: Insight | None = None) -> dict:
    return {
        "id": rec.id,
        "title": display_title(rec),
        "device_id": rec.device_id,
        "recorded_at": rec.recorded_at,
        "local_date": rec.local_date,
        "duration_ms": rec.duration_ms,
        "battery_pct": rec.battery_pct,
        "language": rec.language,
        "status": rec.status,
        "error": rec.error,
        "created_at": rec.created_at.isoformat() + "Z" if rec.created_at else None,
        "open_items": open_items,
        "source": rec.source or "device",
        "summary": (insight.summary if insight else None),
        "topics": (insight.topics or []) if insight else [],
        "keywords": (insight.keywords or []) if insight else [],
    }


def insights_map(db: Session) -> dict[str, Insight]:
    return {i.recording_id: i for i in db.query(Insight).all()}


def open_item_counts(db: Session) -> dict[str, int]:
    rows = (db.query(ActionItem.recording_id, func.count(ActionItem.id))
            .filter(ActionItem.status == "open").group_by(ActionItem.recording_id).all())
    return dict(rows)


def segment_dict(s: Segment) -> dict:
    return {"id": s.id, "idx": s.idx, "start_s": s.start_s, "end_s": s.end_s, "text": s.text,
            "speaker": s.speaker_label}


def action_dict(a: ActionItem, seg_start: dict[int, float] | None = None, rec: Recording | None = None) -> dict:
    d = {"id": a.id, "recording_id": a.recording_id, "who": a.who, "what": a.what, "due_text": a.due_text,
         "due_date": a.due_date, "status": a.status, "segment_id": a.segment_id,
         "start_s": (seg_start or {}).get(a.segment_id)}
    if rec is not None:
        d["recording_title"] = display_title(rec)
        d["recorded_at"] = rec.recorded_at
    return d


def recording_detail(db: Session, rec: Recording) -> dict:
    segs = db.query(Segment).filter_by(recording_id=rec.id).order_by(Segment.idx).all()
    starts = {s.id: s.start_s for s in segs}
    ins = db.get(Insight, rec.id)
    items = db.query(ActionItem).filter_by(recording_id=rec.id).order_by(ActionItem.id).all()
    mentions = db.query(Mention).filter_by(recording_id=rec.id).order_by(Mention.id).all()
    d = recording_row(rec, sum(1 for a in items if a.status == "open"), ins)
    d.update({
        "original_name": rec.original_name,
        "segments": [segment_dict(s) for s in segs],
        "insights": None if ins is None else {
            "summary": ins.summary, "key_points": ins.key_points or [], "decisions": ins.decisions or [],
            "topics": ins.topics or [], "keywords": ins.keywords or [], "model": ins.model},
        "action_items": [action_dict(a, starts) for a in items],
        "meetings": [{"id": m.id, "what": m.value, "when_text": m.detail, "when": m.normalized,
                      "segment_id": m.segment_id, "start_s": starts.get(m.segment_id)}
                     for m in mentions if m.kind == "meeting"],
        "people": [{"id": m.id, "name": m.value, "role": m.detail, "segment_id": m.segment_id,
                    "start_s": starts.get(m.segment_id)} for m in mentions if m.kind == "person"],
    })
    return d


def event_dict(e: CalendarEvent) -> dict:
    return {"id": e.id, "title": e.title, "start": e.start, "end": e.end, "attendees": e.attendees or [],
            "notes": e.notes, "source_recording_id": e.source_recording_id, "source_ref": e.source_ref,
            "created_at": e.created_at.isoformat() + "Z"}


def draft_dict(d: EmailDraft) -> dict:
    return {"id": d.id, "to": d.to_addr, "subject": d.subject, "body": d.body,
            "source_recording_id": d.source_recording_id, "source_ref": d.source_ref,
            "created_at": d.created_at.isoformat() + "Z"}
