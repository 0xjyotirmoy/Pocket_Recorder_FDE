from datetime import datetime
from pathlib import Path

from app.models import CalendarEvent, EmailDraft, Recording
from app.db import SessionLocal
from app.providers import llm
from app.services.timeparse import resolve_relative
from conftest import upload, wait_status


# ---- contract -----------------------------------------------------------------------------------
def test_upload_contract_201(client):
    r = upload(client)
    assert r.status_code == 201
    assert r.json() == {"id": "rec-01_2026-11-05T14-32-10+05-30", "status": "saved"}


def test_duplicate_upload_is_201_same_id_one_row(client):
    a = upload(client, recorded_at="2026-11-05T15:00:00+05:30")
    b = upload(client, recorded_at="2026-11-05T15:00:00+05:30")
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] == b.json()["id"]
    with SessionLocal() as db:
        assert db.query(Recording).filter_by(id=a.json()["id"]).count() == 1


def test_missing_audio_400(client):
    r = client.post("/upload", data={"device_id": "rec-01", "recorded_at": "2026-11-05T14:32:10+05:30"})
    assert r.status_code == 400 and "audio" in r.json()["error"]


def test_bad_recorded_at_422(client):
    assert upload(client, recorded_at="yesterday").status_code == 422
    assert upload(client, recorded_at="2026-11-05T14:32:10").status_code == 422  # no offset


def test_not_a_wav_422(client):
    r = upload(client, recorded_at="2026-11-05T16:00:00+05:30", data=b"hello world, not audio")
    assert r.status_code == 422


def test_local_date_uses_own_offset(client):
    rid = upload(client, recorded_at="2026-11-06T00:30:00+05:30").json()["id"]
    assert client.get(f"/recordings/{rid}").json()["local_date"] == "2026-11-06"


# ---- import + processing ------------------------------------------------------------------------
def test_import_idempotent(client):
    r1 = client.post("/import").json()
    r2 = client.post("/import").json()
    assert r1["imported"] == ["rec-demo_2026-11-03T10-05-00+05-30"]
    assert r2["imported"] == [] and r2["skipped"] == r1["imported"]
    assert r1["errors"][0]["file"] == "missing.wav"


def test_worker_transcribes_and_extracts(client):
    rid = upload(client, recorded_at="2026-11-02T09:00:00+05:30").json()["id"]  # Monday
    rec = wait_status(client, rid)
    assert rec["status"] == "done"
    assert len(rec["segments"]) == 3 and rec["segments"][1]["start_s"] > 0
    assert rec["duration_ms"] == 8200
    assert rec["insights"]["summary"]
    whats = [a["what"] for a in rec["action_items"]]
    assert "Send the purchase order" in whats and "Hallucinated task" not in whats  # bogus segment dropped
    item = next(a for a in rec["action_items"] if a["what"] == "Send the purchase order")
    assert item["due_date"] == "2026-11-05"  # "Thursday" resolved from Monday 2 Nov


def test_failed_transcription_does_not_kill_worker(client):
    rid = upload(client, device_id="fail-device", recorded_at="2026-11-05T17:00:00+05:30").json()["id"]
    assert wait_status(client, rid)["status"] == "failed"
    ok = upload(client, recorded_at="2026-11-05T18:00:00+05:30").json()["id"]
    assert wait_status(client, ok)["status"] == "done"
    assert client.get("/health").json()["worker_alive"]


def test_llm_failure_keeps_transcript(client):
    llm.FAKE_STATE["raise"] = True
    try:
        rid = upload(client, recorded_at="2026-11-05T19:00:00+05:30").json()["id"]
        rec = wait_status(client, rid)
    finally:
        llm.FAKE_STATE.clear()
    assert rec["status"] == "done" and rec["segments"] and rec["insights"] is None and rec["error"]


# ---- search -------------------------------------------------------------------------------------
def test_search_hit_has_timestamp(client):
    rid = upload(client, recorded_at="2026-11-05T20:00:00+05:30").json()["id"]
    wait_status(client, rid)
    hits = client.get("/search", params={"q": "purchase order"}).json()["hits"]
    assert hits and "start_s" in hits[0] and "\u0002" in hits[0]["snippet"]


def test_search_weird_input_no_error(client):
    for q in ['"', "AND OR NOT", "a*b(c)", "NEAR(", "'; DROP TABLE x;--"]:
        assert client.get("/search", params={"q": q}).status_code == 200


# ---- agent --------------------------------------------------------------------------------------
def test_chat_grounded_with_real_timestamp(client):
    rid = upload(client, recorded_at="2026-11-04T10:00:00+05:30").json()["id"]
    wait_status(client, rid)
    r = client.post("/chat", json={"message": "What did we promise about the purchase order?"}).json()
    assert r["grounded"] is True and r["sources"]
    s = r["sources"][0]
    assert "[S" not in r["answer"]
    seg = next(x for x in client.get(f"/recordings/{s['recording_id']}").json()["segments"] if x["id"] == s["segment_id"])
    assert s["start_s"] == seg["start_s"]


def test_chat_hallucinated_citation_abstains(client):
    llm.FAKE_STATE["hallucinate"] = True
    try:
        r = client.post("/chat", json={"message": "purchase order details?"}).json()
    finally:
        llm.FAKE_STATE.clear()
    assert r["grounded"] is False and r["sources"] == [] and "don't contain" in r["answer"]


def test_chat_no_evidence_abstains(client):
    r = client.post("/chat", json={"message": "What is the quarterly marketing budget for Zanzibar?"}).json()
    assert r["grounded"] is False and r["pending_action"] is None


# ---- actions ------------------------------------------------------------------------------------
def _count(model):
    with SessionLocal() as db:
        return db.query(model).count()


def test_calendar_requires_confirm_and_is_idempotent(client):
    before = _count(CalendarEvent)
    r = client.post("/chat", json={"message": "Schedule a follow-up on the purchase order"}).json()
    pa = r["pending_action"]
    assert pa and pa["tool"] == "create_calendar_event"
    assert _count(CalendarEvent) == before  # nothing written yet
    assert client.post(f"/actions/{pa['id']}/confirm", json={}).status_code == 200
    assert client.post(f"/actions/{pa['id']}/confirm", json={}).status_code == 200
    assert _count(CalendarEvent) == before + 1


def test_email_reject_writes_nothing(client):
    before = _count(EmailDraft)
    pa = client.post("/chat", json={"message": "Draft an email to the vendor about the purchase order"}).json()["pending_action"]
    assert pa and pa["tool"] == "draft_email"
    assert client.post(f"/actions/{pa['id']}/reject").status_code == 200
    assert client.post(f"/actions/{pa['id']}/confirm", json={}).status_code == 409
    assert _count(EmailDraft) == before


def test_no_email_sending_code():
    root = Path(__file__).resolve().parents[1] / "app"
    src = " ".join(p.read_text(encoding="utf-8") for p in root.rglob("*.py"))
    for banned in ("smtplib", "sendmail", "send_message("):
        assert banned not in src


# ---- dates --------------------------------------------------------------------------------------
def test_resolve_relative():
    base = datetime.fromisoformat("2026-11-02T10:00:00+05:30")  # Monday
    assert resolve_relative("by Thursday", base) == "2026-11-05"
    assert resolve_relative("tomorrow", base) == "2026-11-03"
    assert resolve_relative("on 12 Nov", base) == "2026-11-12"
    assert resolve_relative("next week", base) == "2026-11-09"
    assert resolve_relative("no date here", base) is None


# ---- Hindi / Bengali ------------------------------------------------------------------------------
def test_indic_search(client):
    from app.models import Segment
    rid = upload(client, recorded_at="2026-11-07T10:00:00+05:30").json()["id"]
    wait_status(client, rid)
    with SessionLocal() as db:
        db.add(Segment(recording_id=rid, idx=10, start_s=40.0, end_s=44.0, text="আমরা বৃহস্পতিবারের মধ্যে অর্ডার পাঠাব"))
        db.add(Segment(recording_id=rid, idx=11, start_s=45.0, end_s=49.0, text="हम गुरुवार तक खरीद आदेश भेज देंगे"))
        db.commit()
    bn = client.get("/search", params={"q": "অর্ডার পাঠাব"}).json()["hits"]
    hi = client.get("/search", params={"q": "खरीद आदेश"}).json()["hits"]
    assert bn and bn[0]["start_s"] == 40.0
    assert hi and hi[0]["start_s"] == 45.0



# ---- round 3: real audio, dates, dashboard, actions, sessions -------------------------------------
def test_mp3_phone_recording_is_converted(client, tmp_path):
    import subprocess
    from app.services.audio import ffmpeg_exe
    mp3 = tmp_path / "call.mp3"
    subprocess.run([ffmpeg_exe(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=4",
                    "-ar", "8000", "-ac", "2", str(mp3)], check=True)
    r = upload(client, device_id="dashboard", recorded_at="2026-11-08T09:00:00+05:30", data=mp3.read_bytes(),
               name="call.mp3", duration_ms="")
    assert r.status_code == 201
    rec = wait_status(client, r.json()["id"])
    assert rec["status"] == "done" and rec["source"] == "dashboard" and 3500 < rec["duration_ms"] < 4500


def test_garbage_upload_still_rejected(client):
    assert upload(client, recorded_at="2026-11-08T10:00:00+05:30", data=b"\x00" * 2000, name="x.mp3").status_code == 422


def test_search_by_date_returns_sessions(client):
    rid = upload(client, recorded_at="2026-11-09T11:00:00+05:30").json()["id"]
    wait_status(client, rid)
    for q in ("nov 9", "9 Nov", "9/11", "2026-11-09"):
        r = client.get("/search", params={"q": q}).json()
        assert r["date_from"] == "2026-11-09" and any(x["id"] == rid for x in r["recordings"]), q
    r = client.get("/search", params={"q": "purchase order 9 nov"}).json()
    assert r["hits"] and all(h["local_date"] == "2026-11-09" for h in r["hits"])
    r = client.get("/search", params={"q": "delivery"}).json()  # keyword from analysis matches the session
    assert any(x["id"] == rid for x in r["recordings"])


def test_dashboard_has_topics_keywords_sources(client):
    d = client.get("/dashboard").json()
    assert d["totals"]["meetings"] >= 1 and "from_device" in d["totals"]
    assert any(k["word"] == "purchase order" for k in d["keywords"])
    assert d["days"] and d["days"][0]["recordings"][0]["topics"] is not None
    assert "audio_mb" in d["storage"]


def test_schedule_question_is_not_an_action(client):
    r = client.post("/chat", json={"message": "What is on my schedule next week?"}).json()
    assert r["pending_action"] is None


def test_action_fallback_when_model_asks_back(client):
    llm.FAKE_STATE["no_action"] = True
    try:
        r = client.post("/chat", json={"message": "schedule mail 3 nov content"}).json()
        r2 = client.post("/chat", json={"message": "reminder on vendor payment friday 4pm"}).json()
    finally:
        llm.FAKE_STATE.clear()
    assert r["pending_action"]["tool"] == "draft_email" and r["pending_action"]["args"]["body"]
    assert r2["pending_action"]["tool"] == "create_calendar_event"
    assert "T16:00:00" in r2["pending_action"]["args"]["start"]


def test_draft_needs_recipient_only_at_confirm(client):
    llm.FAKE_STATE["no_action"] = True
    try:
        pa = client.post("/chat", json={"message": "draft a mail about the order"}).json()["pending_action"]
    finally:
        llm.FAKE_STATE.clear()
    if not pa["args"]["to"]:
        assert client.post(f"/actions/{pa['id']}/confirm", json={}).status_code == 422
    assert client.post(f"/actions/{pa['id']}/confirm", json={"args": {"to": "ravi@example.com"}}).status_code == 200


def test_calendar_suggestions_from_recordings(client):
    from app.models import ActionItem
    sugg = client.get("/calendar/suggestions").json()
    assert any(s["kind"] == "deadline" for s in sugg)
    s = sugg[0]
    pa = client.post(f"/calendar/suggestions/{s['ref']}").json()
    assert pa["tool"] == "create_calendar_event"
    client.post(f"/actions/{pa['id']}/confirm", json={})
    assert all(x["ref"] != s["ref"] for x in client.get("/calendar/suggestions").json())  # now on calendar


def test_action_item_email_and_schedule(client):
    items = client.get("/action-items", params={"status": "open"}).json()
    pa = client.post(f"/action-items/{items[0]['id']}/email").json()
    assert pa["tool"] == "draft_email" and pa["args"]["subject"]
    pa2 = client.post(f"/action-items/{items[0]['id']}/schedule").json()
    assert pa2["tool"] == "create_calendar_event"


def test_chat_sessions_persist(client):
    r1 = client.post("/chat", json={"message": "What did we promise about the purchase order?"}).json()
    sid = r1["session_id"]
    client.post("/chat", json={"message": "and the delivery address?", "session_id": sid})
    s = client.get(f"/chat/sessions/{sid}").json()
    assert len(s["turns"]) == 2 and s["turns"][0]["q"].startswith("What did we promise")
    assert any(x["id"] == sid for x in client.get("/chat/sessions").json())


def test_delete_recording_removes_audio(client):
    rid = upload(client, recorded_at="2026-11-10T10:00:00+05:30").json()["id"]
    rec = wait_status(client, rid)
    from app.models import Recording
    with SessionLocal() as db:
        path = Path(db.get(Recording, rid).file_path)
    assert path.exists()
    assert client.delete(f"/recordings/{rid}").status_code == 200
    assert not path.exists() and client.get(f"/recordings/{rid}").status_code == 404


def test_migration_adds_columns_to_old_db(tmp_path):
    import sqlite3
    from sqlalchemy import create_engine
    from app import db as dbmod
    old = tmp_path / "old.db"
    con = sqlite3.connect(old)
    con.execute("CREATE TABLE recordings (id TEXT PRIMARY KEY, device_id TEXT, recorded_at TEXT, recorded_at_utc DATETIME, local_date TEXT, duration_ms INT, battery_pct INT, file_path TEXT, original_name TEXT, title TEXT, language TEXT, status TEXT, error TEXT, created_at DATETIME)")
    con.execute("INSERT INTO recordings (id, device_id, status) VALUES ('a', 'dashboard', 'done')")
    con.commit(); con.close()
    eng = create_engine(f"sqlite:///{old}")
    with eng.begin() as conn:
        dbmod._migrate(conn)
        assert conn.exec_driver_sql("SELECT source FROM recordings").scalar() == "dashboard"
