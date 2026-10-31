import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import config, events, worker
from ..db import get_db
from ..services.ingest import IngestError, ingest_file

router = APIRouter(tags=["ingest"])


@router.post("/upload", status_code=201)
async def upload(
    request: Request,
    audio: UploadFile | None = None,
    device_id: str | None = Form(None),
    recorded_at: str | None = Form(None),
    duration_ms: str | None = Form(None),
    battery_pct: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Hand-off contract. Success and duplicate both return 201 with the same id,
    because the recorder retries anything that is not 201."""
    if audio is None or not audio.filename:
        return JSONResponse({"error": "missing 'audio' file"}, status_code=400)
    tmp = config.AUDIO_DIR / f".upload_{uuid.uuid4().hex}.part"
    size, limit = 0, config.MAX_UPLOAD_MB * 1024 * 1024
    try:
        with open(tmp, "wb") as f:
            while chunk := await audio.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise IngestError(f"file larger than {config.MAX_UPLOAD_MB} MB", 413)
                f.write(chunk)
        source = "dashboard" if (device_id or "").strip() == config.DASHBOARD_DEVICE_ID else "device"
        rec, created = ingest_file(db, tmp, original_name=audio.filename, device_id=device_id,
                                   recorded_at=recorded_at, duration_ms=duration_ms, battery_pct=battery_pct,
                                   source=source)
    finally:
        tmp.unlink(missing_ok=True)
    if created:
        events.publish("recording", id=rec.id, status="queued")
        worker.wake()  # start transcribing now, not on the next poll
    return {"id": rec.id, "status": "saved"}


@router.post("/import")
def import_manifest(db: Session = Depends(get_db)):
    manifest = config.SAMPLE_DIR / "manifest.json"
    if not manifest.exists():
        raise IngestError(f"manifest not found at {manifest}", 404)
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8-sig"))
        if not isinstance(entries, list):
            raise ValueError("manifest must be a JSON array")
    except ValueError as e:
        raise IngestError(f"invalid manifest.json: {e}")
    imported, skipped, errors = [], [], []
    for i, e in enumerate(entries):
        name = str((e or {}).get("file") or "")
        src = (config.SAMPLE_DIR / name).resolve()
        if not name or config.SAMPLE_DIR.resolve() not in src.parents or not src.is_file():
            errors.append({"index": i, "file": name, "error": "file not found in sample-recordings"})
            continue
        try:
            rec, created = ingest_file(db, Path(src), original_name=name, device_id=e.get("device_id"),
                                       recorded_at=e.get("recorded_at"), duration_ms=e.get("duration_ms"),
                                       battery_pct=e.get("battery_pct"), move=False, source="import")
            (imported if created else skipped).append(rec.id)
        except IngestError as err:
            errors.append({"index": i, "file": name, "error": err.message})
    if imported:
        events.publish("recording", id=imported[-1], status="queued")
        worker.wake()
    return {"imported": imported, "skipped": skipped, "errors": errors}
