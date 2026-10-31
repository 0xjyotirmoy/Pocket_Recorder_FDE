"""Meeting intelligence: summary, key points, decisions, action items, meetings, people."""
import logging
from pathlib import Path

from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from ..models import ActionItem, Insight, Mention, Recording, Segment
from ..providers.llm import LLMError, get_llm
from .timeparse import parse_iso, resolve_relative, valid_date

log = logging.getLogger("extract")
SYSTEM = (Path(__file__).resolve().parents[1] / "prompts" / "extract.md").read_text(encoding="utf-8")


def _seg_id(v):
    if v is None or v == "":
        return None
    try:
        return int(str(v).strip().lstrip("Ss"))
    except ValueError:
        return None


class XAction(BaseModel):
    who: str | None = "unassigned"
    what: str
    due_text: str | None = None
    due_date: str | None = None
    segment_id: int | None = None
    v_sid = field_validator("segment_id", mode="before")(_seg_id)


class XMeeting(BaseModel):
    what: str
    when_text: str | None = None
    when_iso: str | None = None
    segment_id: int | None = None
    v_sid = field_validator("segment_id", mode="before")(_seg_id)


class XPerson(BaseModel):
    name: str
    role: str | None = None
    segment_id: int | None = None
    v_sid = field_validator("segment_id", mode="before")(_seg_id)


class Extraction(BaseModel):
    title: str | None = None
    summary: str = ""
    topics: list[str] = []
    keywords: list[str] = []
    key_points: list[str] = []
    decisions: list[str] = []
    action_items: list[XAction] = []
    meetings: list[XMeeting] = []
    people: list[XPerson] = []


def mmss(s: float) -> str:
    s = int(max(0, s))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def build_user_prompt(rec: Recording, segs: list[Segment]) -> str:
    lines = [f"[S{s.id}] ({mmss(s.start_s)}) {s.text}" for s in segs]
    hint = f"File name hint: {rec.original_name}\n" if rec.original_name else ""
    return f"Recording start time: {rec.recorded_at}\n{hint}Transcript:\n" + "\n".join(lines)


def run_extraction(db: Session, rec: Recording) -> None:
    segs = db.query(Segment).filter_by(recording_id=rec.id).order_by(Segment.idx).all()
    if not segs:
        return
    llm = get_llm()
    data = None
    last_err = None
    for _ in range(2):  # one extra attempt if the JSON does not validate
        try:
            data = Extraction.model_validate(llm.complete_json(SYSTEM, build_user_prompt(rec, segs)))
            break
        except (LLMError, ValueError) as e:
            last_err = e
    if data is None:
        raise LLMError(f"extraction failed: {last_err}")

    valid = {s.id for s in segs}
    base = parse_iso(rec.recorded_at)

    db.query(ActionItem).filter_by(recording_id=rec.id).delete()
    db.query(Mention).filter_by(recording_id=rec.id).delete()
    db.query(Insight).filter_by(recording_id=rec.id).delete()

    kw, seen_kw = [], set()
    for k in data.keywords:
        k = str(k).strip().strip(".,")
        if k and k.lower() not in seen_kw:
            seen_kw.add(k.lower())
            kw.append(k[:40])
    db.add(Insight(recording_id=rec.id, summary=data.summary.strip(), key_points=data.key_points[:12],
                   decisions=data.decisions[:12], topics=[t.strip()[:60] for t in data.topics if t.strip()][:4],
                   keywords=kw[:10], model=getattr(llm, "model", None)))
    for a in data.action_items:
        if a.segment_id not in valid or not a.what.strip():
            continue  # uncited items are dropped: nothing without evidence
        due = valid_date(a.due_date) or resolve_relative(a.due_text, base)
        db.add(ActionItem(recording_id=rec.id, who=(a.who or "unassigned").strip() or "unassigned",
                          what=a.what.strip(), due_text=a.due_text, due_date=due, segment_id=a.segment_id))
    for m in data.meetings:
        if m.segment_id not in valid:
            continue
        when = m.when_iso if (m.when_iso and valid_date(m.when_iso)) else resolve_relative(m.when_text, base)
        db.add(Mention(recording_id=rec.id, kind="meeting", value=m.what.strip(), detail=m.when_text,
                       normalized=when, segment_id=m.segment_id))
    seen = set()
    for p in data.people:
        key = p.name.strip().lower()
        if p.segment_id not in valid or not key or key in seen:
            continue
        seen.add(key)
        db.add(Mention(recording_id=rec.id, kind="person", value=p.name.strip(), detail=p.role,
                       segment_id=p.segment_id))
    if data.title and data.title.strip():
        rec.title = data.title.strip()[:80]
    db.commit()
