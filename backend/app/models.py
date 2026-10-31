from datetime import datetime, timezone

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Recording(Base):
    __tablename__ = "recordings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    device_id: Mapped[str] = mapped_column(String)
    recorded_at: Mapped[str] = mapped_column(String)  # exactly as received
    recorded_at_utc: Mapped[datetime] = mapped_column(index=True)
    local_date: Mapped[str] = mapped_column(String, index=True)  # date in recorded_at's own offset
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    battery_pct: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String, default="device", index=True)  # device | import | dashboard
    file_path: Mapped[str] = mapped_column(String)
    original_name: Mapped[str | None] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String)
    language: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    segments: Mapped[list["Segment"]] = relationship(
        cascade="all, delete-orphan", order_by="Segment.idx", passive_deletes=True
    )


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    speaker_label: Mapped[str | None] = mapped_column(String)
    lang: Mapped[str | None] = mapped_column(String)


class Insight(Base):
    __tablename__ = "insights"

    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"), primary_key=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    key_points: Mapped[list] = mapped_column(JSON, default=list)
    decisions: Mapped[list] = mapped_column(JSON, default=list)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ActionItem(Base):
    __tablename__ = "action_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"), index=True)
    who: Mapped[str] = mapped_column(String, default="unassigned")
    what: Mapped[str] = mapped_column(Text)
    due_text: Mapped[str | None] = mapped_column(String)
    due_date: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="open", index=True)
    segment_id: Mapped[int | None] = mapped_column(ForeignKey("segments.id", ondelete="SET NULL"))


class Mention(Base):
    __tablename__ = "mentions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String)  # person | meeting | date
    value: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(String)  # role / when_text
    normalized: Mapped[str | None] = mapped_column(String)  # ISO date when resolvable
    segment_id: Mapped[int | None] = mapped_column(ForeignKey("segments.id", ondelete="SET NULL"))


class PendingAction(Base):
    __tablename__ = "pending_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool: Mapped[str] = mapped_column(String)
    args: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | confirmed | rejected
    result_id: Mapped[int | None] = mapped_column(Integer)
    source_recording_id: Mapped[str | None] = mapped_column(String)
    source_ref: Mapped[str | None] = mapped_column(String)  # e.g. "mention:12", "item:4"
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column()


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String)
    start: Mapped[str] = mapped_column(String)  # ISO 8601 with offset
    end: Mapped[str] = mapped_column(String)
    attendees: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    source_recording_id: Mapped[str | None] = mapped_column(String)
    source_ref: Mapped[str | None] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class EmailDraft(Base):
    __tablename__ = "email_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    to_addr: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    source_recording_id: Mapped[str | None] = mapped_column(String)
    source_ref: Mapped[str | None] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, default="New conversation")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String)  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)  # sources, grounded, pending_action for assistant turns
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
