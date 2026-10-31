"""Single background worker. The job queue is recordings.status, so nothing is lost on restart."""
import logging
import threading
import time
from pathlib import Path

from . import events
from .db import SessionLocal
from .models import Recording, Segment
from .providers.transcriber import build_transcriber
from .services.extract import run_extraction

log = logging.getLogger("worker")


class Worker(threading.Thread):
    def __init__(self, poll_s: float = 2.0):
        super().__init__(daemon=True, name="worker")
        self.poll_s = poll_s
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()  # set by POST /upload so work starts instantly
        self.transcriber = None
        self.current: str | None = None

    def stop(self):
        self.stop_event.set()
        self.wake_event.set()

    def wake(self):
        self.wake_event.set()

    def _sleep(self):
        self.wake_event.wait(self.poll_s)
        self.wake_event.clear()

    def run(self):
        self._recover()
        while not self.stop_event.is_set():
            try:
                rid = self._next_job()
                if rid is None:
                    self._sleep()
                    continue
                self.current = rid
                self._process(rid)
            except Exception:  # never let the loop die
                log.exception("worker loop error")
                self._sleep()
            finally:
                self.current = None

    def _recover(self):
        with SessionLocal() as db:
            n = (db.query(Recording).filter(Recording.status.in_(["transcribing", "extracting"]))
                 .update({Recording.status: "queued"}, synchronize_session=False))
            db.commit()
            if n:
                log.info("re-queued %d interrupted recording(s)", n)

    def _next_job(self) -> str | None:
        with SessionLocal() as db:
            rec = (db.query(Recording).filter(Recording.status == "queued")
                   .order_by(Recording.created_at).first())
            return rec.id if rec else None

    def _set(self, rid: str, **fields):
        with SessionLocal() as db:
            db.query(Recording).filter_by(id=rid).update(fields, synchronize_session=False)
            db.commit()
        if "status" in fields:
            events.publish("recording", id=rid, status=fields["status"])

    def _process(self, rid: str):
        with SessionLocal() as db:
            rec = db.get(Recording, rid)
            has_segments = db.query(Segment.id).filter_by(recording_id=rid).first() is not None
            path = Path(rec.file_path)

        # 1) transcription (skipped when segments exist, e.g. re-extract)
        if not has_segments:
            self._set(rid, status="transcribing", error=None)
            try:
                if self.transcriber is None:
                    self.transcriber = build_transcriber()
                t0 = time.time()
                segs, dur, lang = self.transcriber.transcribe(path)
                log.info("transcribed %s: %d segments in %.1fs", rid, len(segs), time.time() - t0)
            except Exception as e:  # noqa: BLE001
                log.exception("transcription failed for %s", rid)
                self._set(rid, status="failed", error=f"Transcription failed: {e}"[:1000])
                return
            with SessionLocal() as db:
                rec = db.get(Recording, rid)
                db.query(Segment).filter_by(recording_id=rid).delete()
                for i, s in enumerate(segs):
                    db.add(Segment(recording_id=rid, idx=i, start_s=s.start, end_s=max(s.end, s.start),
                                   text=s.text, lang=lang))
                if dur and not rec.duration_ms:
                    rec.duration_ms = round(dur * 1000)
                rec.language = lang
                db.commit()
            events.publish("recording", id=rid, status="transcribed")

        # 2) meeting intelligence; failure keeps the transcript usable
        self._set(rid, status="extracting")
        with SessionLocal() as db:
            rec = db.get(Recording, rid)
            try:
                run_extraction(db, rec)
                rec.error = None
            except Exception as e:  # noqa: BLE001
                db.rollback()
                rec = db.get(Recording, rid)
                log.exception("extraction failed for %s", rid)
                rec.error = f"Summary unavailable: {e}"[:1000]
            rec.status = "done"
            db.commit()
        events.publish("recording", id=rid, status="done")


worker: Worker | None = None


def wake() -> None:
    if worker is not None:
        worker.wake()
