import re
import shutil
from datetime import timezone
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config
from ..models import Recording
from .audio import is_wav, to_wav16k, wav_duration
from .timeparse import parse_iso

GENERIC_NAMES = {"clip", "audio", "recording", "rec", "file", "upload", "sample", "test"}


class IngestError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


def make_id(device_id: str, recorded_at: str) -> str:
    """Contract: id = device_id + '_' + recorded_at with ':' replaced by '-'."""
    return f"{device_id}_{recorded_at.replace(':', '-')}"


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._+-]", "_", name)


def title_from_filename(name: str | None) -> str | None:
    stem = Path(name or "").stem
    stem = re.sub(r"^(rec|recording)[_-]?\d+[_-]?", "", stem, flags=re.I)
    words = re.sub(r"[_-]+", " ", stem).strip()
    if not words or words.lower() in GENERIC_NAMES:
        return None
    return words[:1].upper() + words[1:]


def _opt_int(value, name: str, lo: int | None = None, hi: int | None = None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        n = int(float(str(value).strip()))
    except ValueError:
        raise IngestError(f"{name} must be a number")
    if (lo is not None and n < lo) or (hi is not None and n > hi):
        raise IngestError(f"{name} is out of range")
    return n


def ingest_file(
    db: Session,
    src: Path,
    *,
    original_name: str | None,
    device_id: str | None,
    recorded_at: str | None,
    duration_ms=None,
    battery_pct=None,
    move: bool = True,
    source: str = "device",
) -> tuple[Recording, bool]:
    """Validate and store one recording. Returns (recording, created).
    Shared by POST /upload (move=True, temp file) and POST /import (move=False, copy).
    WAV from the recorder is stored as-is; any other audio (mp3, m4a, ogg, phone recordings)
    is converted to 16 kHz mono WAV first, so the rest of the pipeline sees one format."""
    device_id = (device_id or "").strip()
    recorded_at = (recorded_at or "").strip()
    try:
        if not device_id or len(device_id) > 64:
            raise IngestError("device_id is required (max 64 characters)")
        try:
            dt = parse_iso(recorded_at)
        except ValueError as e:
            raise IngestError(f"recorded_at must be ISO 8601 with a time zone offset ({e})")
        dur_ms = _opt_int(duration_ms, "duration_ms", 0)
        battery = _opt_int(battery_pct, "battery_pct", 0, 100)

        rid = make_id(device_id, recorded_at)
        existing = db.get(Recording, rid)
        if existing:
            return existing, False

        dest = config.AUDIO_DIR / f"{_safe_filename(rid)}.wav"
        if is_wav(src):
            try:
                dur_s = wav_duration(src)
            except ValueError as e:
                raise IngestError(str(e))
            if dur_s is not None and dur_s <= 0:
                raise IngestError("WAV contains no audio frames")
            if move:
                shutil.move(str(src), dest)
            else:
                shutil.copyfile(src, dest)
        else:
            try:
                dur_s = to_wav16k(src, dest)
            except (RuntimeError, ValueError) as e:
                dest.unlink(missing_ok=True)
                raise IngestError(f"not a readable audio file ({str(e)[:160]})")

        rec = Recording(
            id=rid,
            device_id=device_id,
            recorded_at=recorded_at,
            recorded_at_utc=dt.astimezone(timezone.utc).replace(tzinfo=None),
            local_date=dt.date().isoformat(),
            duration_ms=dur_ms if dur_ms is not None else (round(dur_s * 1000) if dur_s else None),
            battery_pct=battery,
            source=source,
            file_path=str(dest),
            original_name=original_name,
            title=title_from_filename(original_name),
            status="queued",
        )
        db.add(rec)
        try:
            db.commit()
        except IntegrityError:  # same clip arrived twice concurrently
            db.rollback()
            existing = db.get(Recording, rid)
            if existing:
                return existing, False
            raise
        return rec, True
    finally:
        if move and src.exists():
            src.unlink(missing_ok=True)
