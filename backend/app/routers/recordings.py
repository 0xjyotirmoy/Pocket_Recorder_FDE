from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import config, events, worker
from ..db import get_db
from ..models import ActionItem, CalendarEvent, Insight, Mention, Recording, Segment
from ..services.actions import calendar_suggestions
from ..services.serialize import (action_dict, event_dict, insights_map, open_item_counts, recording_detail,
                                  recording_row)
from ..services.timeparse import now_local

router = APIRouter(tags=["recordings"])


def _get(db: Session, rid: str) -> Recording:
    rec = db.get(Recording, rid)
    if rec is None:
        raise HTTPException(404, "recording not found")
    return rec


@router.get("/recordings")
def list_recordings(date: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Recording)
    if date:
        q = q.filter(Recording.local_date == date)
    counts, ins = open_item_counts(db), insights_map(db)
    return [recording_row(r, counts.get(r.id, 0), ins.get(r.id))
            for r in q.order_by(Recording.recorded_at_utc.desc()).all()]


@router.get("/recordings/{rid}")
def get_recording(rid: str, db: Session = Depends(get_db)):
    return recording_detail(db, _get(db, rid))


@router.get("/recordings/{rid}/audio")
def get_audio(rid: str, db: Session = Depends(get_db)):
    rec = _get(db, rid)
    path = Path(rec.file_path)
    if not path.exists():
        raise HTTPException(404, "audio file missing on disk")
    return FileResponse(path, media_type="audio/wav", filename=f"{rid}.wav")


@router.post("/recordings/{rid}/retry")
def retry(rid: str, db: Session = Depends(get_db)):
    """Full re-run: transcription + analysis."""
    rec = _get(db, rid)
    if rec.status in ("transcribing", "extracting"):
        raise HTTPException(409, "recording is being processed")
    for model in (ActionItem, Mention, Insight, Segment):
        db.query(model).filter_by(recording_id=rid).delete()
    rec.status, rec.error = "queued", None
    db.commit()
    events.publish("recording", id=rid, status="queued")
    worker.wake()
    return recording_row(rec)


@router.post("/recordings/{rid}/reextract")
def reextract(rid: str, db: Session = Depends(get_db)):
    """Keep the transcript, regenerate summary/topics/actions/people."""
    rec = _get(db, rid)
    if rec.status in ("transcribing", "extracting", "queued"):
        raise HTTPException(409, "recording is being processed")
    rec.status, rec.error = "queued", None
    db.commit()
    events.publish("recording", id=rid, status="queued")
    worker.wake()
    return recording_row(rec)


@router.delete("/recordings/{rid}")
def delete_recording(rid: str, db: Session = Depends(get_db)):
    """Removes the recording, its transcript, analysis and audio file (storage management)."""
    rec = _get(db, rid)
    if rec.status in ("transcribing", "extracting"):
        raise HTTPException(409, "recording is being processed")
    path = Path(rec.file_path)
    for model in (ActionItem, Mention, Insight, Segment):
        db.query(model).filter_by(recording_id=rid).delete()
    db.delete(rec)
    db.commit()
    path.unlink(missing_ok=True)
    events.publish("recording", id=rid, status="deleted")
    return {"ok": True}


@router.get("/action-items")
def list_items(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(ActionItem, Recording).join(Recording, Recording.id == ActionItem.recording_id)
    if status:
        q = q.filter(ActionItem.status == status)
    rows = q.order_by(ActionItem.due_date.is_(None), ActionItem.due_date, Recording.recorded_at_utc.desc()).all()
    seg_ids = [a.segment_id for a, _ in rows if a.segment_id]
    starts = dict(db.query(Segment.id, Segment.start_s).filter(Segment.id.in_(seg_ids)).all()) if seg_ids else {}
    return [action_dict(a, starts, r) for a, r in rows]


class ItemPatch(BaseModel):
    status: str


@router.patch("/action-items/{item_id}")
def patch_item(item_id: int, body: ItemPatch, db: Session = Depends(get_db)):
    if body.status not in ("open", "done"):
        raise HTTPException(422, "status must be open or done")
    item = db.get(ActionItem, item_id)
    if item is None:
        raise HTTPException(404, "action item not found")
    item.status = body.status
    db.commit()
    events.publish("data", what="action_items")
    return action_dict(item)


def _dir_size(path: Path) -> tuple[int, int]:
    files = [p for p in path.glob("*") if p.is_file()]
    return sum(p.stat().st_size for p in files), len(files)


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    """Everything the home screen needs in one call."""
    recs = db.query(Recording).order_by(Recording.recorded_at_utc.desc()).all()
    ins, counts = insights_map(db), open_item_counts(db)
    today = now_local().date().isoformat()

    kw, topics = Counter(), Counter()
    kw_recs: dict[str, set] = {}
    for r in recs:
        i = ins.get(r.id)
        for k in (i.keywords or []) if i else []:
            key = k.lower()
            kw[key] += 1
            kw_recs.setdefault(key, set()).add(r.id)
        for t in (i.topics or []) if i else []:
            topics[t] += 1

    days: dict[str, list] = {}
    for r in recs:
        days.setdefault(r.local_date, []).append(recording_row(r, counts.get(r.id, 0), ins.get(r.id)))

    audio_bytes, audio_files = _dir_size(config.AUDIO_DIR)
    db_bytes = sum(p.stat().st_size for p in config.DATA_DIR.glob("app.db*") if p.is_file())
    sources = Counter(r.source or "device" for r in recs)
    return {
        "totals": {
            "meetings": len(recs),
            "minutes": round(sum((r.duration_ms or 0) for r in recs) / 60000, 1),
            "from_device": sources.get("device", 0),
            "from_import": sources.get("import", 0),
            "from_dashboard": sources.get("dashboard", 0),
            "devices": len({r.device_id for r in recs if (r.source or "device") == "device"}),
            "open_items": db.query(ActionItem).filter_by(status="open").count(),
            "upcoming": db.query(CalendarEvent).filter(CalendarEvent.start >= today).count(),
            "suggestions": len(calendar_suggestions(db)),
        },
        "queue": {s: sum(1 for r in recs if r.status == s) for s in ("queued", "transcribing", "extracting", "failed")},
        "keywords": [{"word": w, "count": c, "recordings": sorted(kw_recs[w])} for w, c in kw.most_common(24)],
        "topics": [{"topic": t, "count": c} for t, c in topics.most_common(12)],
        "days": [{"date": d, "recordings": rows} for d, rows in days.items()],
        "open_items": list_items("open", db)[:6],
        "upcoming": [event_dict(e) for e in db.query(CalendarEvent).filter(CalendarEvent.start >= today)
                     .order_by(CalendarEvent.start).limit(5).all()],
        "storage": {"audio_mb": round(audio_bytes / 1e6, 1), "audio_files": audio_files,
                    "db_mb": round(db_bytes / 1e6, 2), "path": str(config.DATA_DIR)},
    }
