"""Self-check: python -m app.doctor   (or: python manage.py check)
Prints PASS / WARN / FAIL for every moving part, with the fix."""
import json
import os
import shutil
import socket
import sys
import time
import wave
from pathlib import Path

OK, WARN, FAIL = "PASS", "WARN", "FAIL"
results: list[tuple[str, str, str]] = []


def report(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    mark = {"PASS": "[ OK ]", "WARN": "[WARN]", "FAIL": "[FAIL]"}[status]
    print(f"{mark} {name}" + (f"\n        {detail}" if detail else ""), flush=True)


def main(online: bool = True) -> int:
    print("\n=== Fieldnotes self-check ===\n")
    v = sys.version_info
    report(OK if v >= (3, 10) else FAIL, f"Python {v.major}.{v.minor}.{v.micro}",
           "" if v >= (3, 10) else "Install Python 3.10+ from python.org")

    try:
        import fastapi, httpx, sqlalchemy, uvicorn, pydantic, dotenv, multipart  # noqa: F401,E401
        report(OK, "Python packages installed")
    except ImportError as e:
        report(FAIL, "Python packages missing", f"{e}. Run setup.bat again.")
        return summary()

    from . import config

    key = config.GROQ_API_KEY
    if not key:
        report(FAIL, "GROQ_API_KEY is not set", "Run: python manage.py set-key gsk_your_key")
    elif key != key.strip() or key[0] in "\"'" or " " in key:
        report(FAIL, "GROQ_API_KEY has quotes or spaces", "Write it as GROQ_API_KEY=gsk_xxxx (nothing else on the line)")
    elif not key.startswith("gsk_"):
        report(WARN, "GROQ_API_KEY does not start with gsk_", "Groq keys normally start with gsk_")
    else:
        report(OK, f"GROQ_API_KEY set (gsk_...{key[-4:]})")
    report(OK, f"Providers: speech={config.ASR_PROVIDER} ({config.GROQ_ASR_MODEL}), llm={config.LLM_MODEL}")

    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = config.DATA_DIR / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        report(OK, f"Data folder writable ({config.DATA_DIR})")
    except OSError as e:
        report(FAIL, "Data folder not writable", str(e))

    from .services.audio import ffmpeg_exe
    exe = ffmpeg_exe()
    report(OK if exe else FAIL, "ffmpeg available (MP3/M4A/OGG uploads, large files)" if exe else "ffmpeg missing",
           "" if exe else "Run: python manage.py setup  (installs imageio-ffmpeg)")
    report(OK, f"Config: {config.USER_CONFIG if config.USER_CONFIG.exists() else 'project .env'} · data: {config.DATA_DIR}")

    dist = config.ROOT / "frontend" / "dist" / "index.html"
    report(OK if dist.exists() else FAIL, "Dashboard build present" if dist.exists() else "Dashboard build missing",
           "" if dist.exists() else "frontend/dist is missing: re-extract the zip")

    man = config.SAMPLE_DIR / "manifest.json"
    if man.exists():
        try:
            entries = json.loads(man.read_text(encoding="utf-8-sig"))
            bad = [e.get("file") for e in entries if not (config.SAMPLE_DIR / str(e.get("file"))).is_file()]
            report(OK if not bad else WARN, f"manifest.json: {len(entries)} entries" + (f", missing files: {bad}" if bad else ""))
        except Exception as e:  # noqa: BLE001
            report(FAIL, "manifest.json is not valid JSON", str(e))
    else:
        report(WARN, "No sample-recordings/manifest.json", "Run setup.bat (creates two spoken samples) or add your own")

    s = socket.socket()
    try:
        s.bind(("0.0.0.0", 8000))
        report(OK, "Port 8000 is free")
    except OSError:
        report(WARN, "Port 8000 is in use", "Fine if Fieldnotes is already running; otherwise close the other program")
    finally:
        s.close()

    if online and key:
        check_groq(config)
    return summary()


def check_groq(config) -> None:
    import httpx

    h = {"Authorization": f"Bearer {config.GROQ_API_KEY}"}
    try:
        r = httpx.get("https://api.groq.com/openai/v1/models", headers=h, timeout=20)
    except httpx.HTTPError as e:
        report(FAIL, "Cannot reach api.groq.com", f"{e}. Check internet / VPN / firewall / proxy.")
        return
    if r.status_code == 401:
        report(FAIL, "Groq rejected the key (401)", "Key is wrong, deleted or expired. Create a new one at console.groq.com/keys")
        return
    if r.status_code != 200:
        report(FAIL, f"Groq models API returned {r.status_code}", r.text[:200])
        return
    ids = {m["id"] for m in r.json().get("data", [])}
    report(OK, "Groq key accepted")
    for model, what in ((config.GROQ_ASR_MODEL, "speech model"), (config.LLM_MODEL, "LLM model")):
        if "groq.com" in config.LLM_BASE_URL or what == "speech model":
            if model in ids:
                report(OK, f"{what} available: {model}")
            else:
                alts = sorted(i for i in ids if ("whisper" in i) == (what == "speech model"))[:8]
                report(FAIL, f"{what} not available: {model}",
                       f"Set a model from this list in .env: {', '.join(alts)}")

    sample = next(iter(sorted(config.SAMPLE_DIR.glob("*.wav"))), None)
    if sample:
        try:
            from .providers.transcriber import GroqTranscriber

            t0 = time.time()
            segs, dur, lang = GroqTranscriber().transcribe(sample)
            words = " ".join(s.text for s in segs)[:90]
            report(OK if segs else WARN, f"Speech-to-text on {sample.name}: {len(segs)} segments in {time.time() - t0:.1f}s",
                   f'"{words}…"' if segs else "No speech detected in this file")
        except Exception as e:  # noqa: BLE001
            report(FAIL, "Speech-to-text call failed", str(e)[:300])

    try:
        from .providers.llm import OpenAICompatLLM

        t0 = time.time()
        out = OpenAICompatLLM().complete_json(
            "Reply with a JSON object only.", 'Return {"status": "ok", "sum": 2+3 as a number}.')
        report(OK, f"LLM JSON call works ({time.time() - t0:.1f}s): {json.dumps(out)[:80]}")
    except Exception as e:  # noqa: BLE001
        report(FAIL, "LLM call failed", str(e)[:300])


def summary() -> int:
    fails = [r for r in results if r[0] == FAIL]
    print("\n" + ("All good. Run: python manage.py start" if not fails else f"{len(fails)} problem(s) above. Fix the [FAIL] lines, "
          "or send this whole output for help."))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(online="--offline" not in sys.argv))
