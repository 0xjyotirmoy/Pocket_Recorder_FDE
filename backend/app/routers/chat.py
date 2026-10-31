from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import events
from ..db import get_db
from ..models import ActionItem, CalendarEvent, ChatMessage, ChatSession, EmailDraft, PendingAction, Recording, utcnow
from ..providers.llm import LLMError, get_llm
from ..services import actions, agent
from ..services.serialize import draft_dict, event_dict

router = APIRouter(tags=["agent"])


# ---- chat with persistent sessions ---------------------------------------------------------------
class ChatIn(BaseModel):
    message: str
    session_id: int | None = None
    history: list[dict[str, Any]] = []  # only used when no session_id is given


def _session_dict(s: ChatSession) -> dict:
    return {"id": s.id, "title": s.title, "created_at": s.created_at.isoformat() + "Z",
            "updated_at": s.updated_at.isoformat() + "Z"}


@router.post("/chat")
def chat(body: ChatIn, db: Session = Depends(get_db)):
    msg = body.message.strip()
    if not msg:
        raise HTTPException(422, "message is empty")
    sess = db.get(ChatSession, body.session_id) if body.session_id else None
    if sess is None:
        sess = ChatSession(title=msg[:60])
        db.add(sess)
        db.commit()
        history = body.history
    else:
        rows = (db.query(ChatMessage).filter_by(session_id=sess.id).order_by(ChatMessage.id.desc()).limit(8).all())
        history = [{"role": m.role, "content": m.content} for m in reversed(rows)]
    try:
        result = agent.answer(db, msg, history)
    except LLMError as e:
        raise HTTPException(503, f"The language model is unavailable right now: {e}")
    db.add(ChatMessage(session_id=sess.id, role="user", content=msg))
    db.add(ChatMessage(session_id=sess.id, role="assistant", content=result["answer"], payload=result))
    sess.updated_at = utcnow()
    db.commit()
    return {**result, "session_id": sess.id}


@router.get("/chat/sessions")
def sessions(db: Session = Depends(get_db)):
    return [_session_dict(s) for s in db.query(ChatSession).order_by(ChatSession.updated_at.desc()).limit(50).all()]


@router.get("/chat/sessions/{sid}")
def session_messages(sid: int, db: Session = Depends(get_db)):
    s = db.get(ChatSession, sid)
    if s is None:
        raise HTTPException(404, "conversation not found")
    msgs = db.query(ChatMessage).filter_by(session_id=sid).order_by(ChatMessage.id).all()
    # pair user/assistant turns; refresh pending action status (it may have been confirmed since)
    turns, q = [], None
    for m in msgs:
        if m.role == "user":
            q = m.content
            continue
        p = dict(m.payload or {"answer": m.content})
        if p.get("pending_action"):
            pa = db.get(PendingAction, p["pending_action"]["id"])
            if pa:
                p["pending_action"] = actions.pending_dict(pa)
        turns.append({"q": q, **p})
    return {**_session_dict(s), "turns": turns}


@router.delete("/chat/sessions/{sid}")
def delete_session(sid: int, db: Session = Depends(get_db)):
    s = db.get(ChatSession, sid)
    if s is None:
        raise HTTPException(404, "conversation not found")
    db.query(ChatMessage).filter_by(session_id=sid).delete()
    db.delete(s)
    db.commit()
    return {"ok": True}


# ---- confirm / discard -------------------------------------------------------------------------
class ConfirmIn(BaseModel):
    args: dict[str, Any] | None = None


def _pending(db: Session, pid: int) -> PendingAction:
    pa = db.get(PendingAction, pid)
    if pa is None:
        raise HTTPException(404, "action not found")
    return pa


@router.post("/actions/{pid}/confirm")
def confirm(pid: int, body: ConfirmIn | None = None, db: Session = Depends(get_db)):
    try:
        pa = actions.confirm(db, _pending(db, pid), (body.args if body else None))
    except actions.ActionError as e:
        raise HTTPException(409 if "discarded" in str(e) else 422, str(e))
    events.publish("data", what="calendar" if pa.tool == "create_calendar_event" else "drafts")
    return actions.pending_dict(pa)


@router.post("/actions/{pid}/reject")
def reject(pid: int, db: Session = Depends(get_db)):
    try:
        return actions.pending_dict(actions.reject(db, _pending(db, pid)))
    except actions.ActionError as e:
        raise HTTPException(409, str(e))


# ---- proposals from the dashboard (no chat needed) ----------------------------------------------
@router.get("/calendar/suggestions")
def suggestions(db: Session = Depends(get_db)):
    """Meetings and deadlines said in recordings that are not on the calendar yet."""
    return actions.calendar_suggestions(db)


@router.post("/calendar/suggestions/{ref}")
def propose_suggestion(ref: str, db: Session = Depends(get_db)):
    try:
        return actions.pending_dict(actions.propose_from_suggestion(db, ref))
    except actions.ActionError as e:
        raise HTTPException(404, str(e))


def _llm_email(db: Session, rec: Recording, item: ActionItem | None) -> dict:
    base = actions.followup_email_template(db, rec, item)
    try:
        focus = f"the action item '{item.what}' owned by {item.who}" if item else "the whole meeting"
        out = get_llm().complete_json(
            "Write a short professional follow-up email draft. Use ONLY the facts given. Return JSON "
            '{"to": str, "subject": str, "body": str}. Sign off with "Best regards".',
            f"Meeting: {rec.title} on {rec.recorded_at}\nFocus: {focus}\nDraft to improve:\n"
            f"To: {base['to']}\nSubject: {base['subject']}\n{base['body']}")
        if out.get("subject") and out.get("body"):
            return {"to": out.get("to") or base["to"], "subject": out["subject"], "body": out["body"]}
    except LLMError:
        pass
    return base


@router.post("/recordings/{rid}/followup-email")
def followup_for_recording(rid: str, db: Session = Depends(get_db)):
    rec = db.get(Recording, rid)
    if rec is None:
        raise HTTPException(404, "recording not found")
    pa = actions.propose(db, "draft_email", _llm_email(db, rec, None), rid, f"recording:{rid}")
    return actions.pending_dict(pa)


@router.post("/action-items/{item_id}/email")
def email_for_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(ActionItem, item_id)
    if item is None:
        raise HTTPException(404, "action item not found")
    rec = db.get(Recording, item.recording_id)
    pa = actions.propose(db, "draft_email", _llm_email(db, rec, item), rec.id, f"item:{item.id}")
    return actions.pending_dict(pa)


@router.post("/action-items/{item_id}/schedule")
def schedule_item(item_id: int, db: Session = Depends(get_db)):
    """Put an action item's deadline (or a reminder tomorrow 10:00 if it has none) on the calendar."""
    item = db.get(ActionItem, item_id)
    if item is None:
        raise HTTPException(404, "action item not found")
    ref = f"item:{item.id}"
    if item.due_date:
        try:
            return actions.pending_dict(actions.propose_from_suggestion(db, ref))
        except actions.ActionError:
            pass
    from datetime import timedelta

    from ..services.timeparse import now_local

    start = (now_local() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    pa = actions.propose(db, "create_calendar_event",
                         {"title": f"{item.what} ({item.who})", "start": start.isoformat()}, item.recording_id, ref)
    return actions.pending_dict(pa)


# ---- calendar + drafts --------------------------------------------------------------------------
@router.get("/calendar")
def calendar(db: Session = Depends(get_db)):
    return [event_dict(e) for e in db.query(CalendarEvent).order_by(CalendarEvent.start).all()]


@router.delete("/calendar/{eid}")
def delete_event(eid: int, db: Session = Depends(get_db)):
    e = db.get(CalendarEvent, eid)
    if e is None:
        raise HTTPException(404, "event not found")
    db.delete(e)
    db.commit()
    events.publish("data", what="calendar")
    return {"ok": True}


@router.get("/drafts")
def drafts(db: Session = Depends(get_db)):
    return [draft_dict(d) for d in db.query(EmailDraft).order_by(EmailDraft.created_at.desc()).all()]


@router.get("/drafts/{did}")
def draft(did: int, db: Session = Depends(get_db)):
    d = db.get(EmailDraft, did)
    if d is None:
        raise HTTPException(404, "draft not found")
    return draft_dict(d)


class DraftPatch(BaseModel):
    to: str | None = None
    subject: str | None = None
    body: str | None = None


@router.patch("/drafts/{did}")
def edit_draft(did: int, body: DraftPatch, db: Session = Depends(get_db)):
    d = db.get(EmailDraft, did)
    if d is None:
        raise HTTPException(404, "draft not found")
    if body.to is not None:
        d.to_addr = body.to.strip()
    if body.subject is not None:
        d.subject = body.subject.strip()
    if body.body is not None:
        d.body = body.body
    db.commit()
    return draft_dict(d)


@router.delete("/drafts/{did}")
def delete_draft(did: int, db: Session = Depends(get_db)):
    d = db.get(EmailDraft, did)
    if d is None:
        raise HTTPException(404, "draft not found")
    db.delete(d)
    db.commit()
    events.publish("data", what="drafts")
    return {"ok": True}
