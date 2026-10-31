import io
import json
import os
import struct
import sys
import tempfile
import time
import wave
from pathlib import Path

import pytest

# Isolated data dir + fake providers BEFORE the app is imported
_TMP = Path(tempfile.mkdtemp(prefix="mip_test_"))
os.environ.update({
    "FIELDNOTES_HOME": str(_TMP / "home"),
    "DATA_DIR": str(_TMP / "data"),
    "SAMPLE_DIR": str(_TMP / "samples"),
    "ASR_PROVIDER": "fake",
    "LLM_PROVIDER": "fake",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def make_wav(seconds: float = 6.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture(scope="session")
def client():
    samples = _TMP / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    (samples / "rec_01_vendor_call.wav").write_bytes(make_wav(9))
    (samples / "manifest.json").write_text(json.dumps([
        {"file": "rec_01_vendor_call.wav", "device_id": "rec-demo", "recorded_at": "2026-11-03T10:05:00+05:30"},
        {"file": "missing.wav", "device_id": "rec-demo", "recorded_at": "2026-11-03T11:00:00+05:30"},
    ]))
    with TestClient(app) as c:
        yield c


def upload(client, device_id="rec-01", recorded_at="2026-11-05T14:32:10+05:30", data=None, name="clip.wav",
           duration_ms="8200", battery_pct=""):
    files = {"audio": (name, data if data is not None else make_wav(), "audio/wav")}
    form = {"device_id": device_id, "recorded_at": recorded_at, "duration_ms": duration_ms, "battery_pct": battery_pct}
    return client.post("/upload", files=files, data=form)


def wait_status(client, rid, want=("done", "failed"), timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/recordings/{rid}").json()
        if r["status"] in want:
            return r
        time.sleep(0.2)
    raise AssertionError(f"{rid} stuck in {r['status']}")
