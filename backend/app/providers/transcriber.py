"""Speech-to-text providers. All return (segments, duration_s, language)."""
import logging
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from .. import config
from ..services.audio import ffmpeg, ffprobe_duration, wav_duration

log = logging.getLogger("asr")

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_LIMIT = 24 * 1024 * 1024  # free tier is 25 MB; keep a margin
CHUNK_S = 600
OVERLAP_S = 5


@dataclass
class Seg:
    start: float
    end: float
    text: str


Result = tuple[list[Seg], float | None, str | None]


class Transcriber(Protocol):
    name: str

    def transcribe(self, path: Path) -> Result: ...


class FakeTranscriber:
    """Deterministic transcriber for tests and UI work without API keys."""

    name = "fake"
    LINES = [
        "Thanks for joining the vendor call.",
        "We will send the purchase order by Thursday.",
        "Please confirm the delivery address before Friday.",
    ]

    def transcribe(self, path: Path) -> Result:
        if "fail" in Path(path).name.lower():
            raise RuntimeError("simulated transcription failure")
        dur = wav_duration(Path(path)) or 12.0
        step = max(dur / len(self.LINES), 0.5)
        segs = [Seg(round(i * step, 2), round((i + 1) * step, 2), t) for i, t in enumerate(self.LINES)]
        return segs, dur, "en"


def _parse_groq(res: dict, offset: float) -> list[Seg]:
    out: list[Seg] = []
    for s in res.get("segments") or []:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        # Whisper invents text in silence: high no-speech probability + low confidence
        if (s.get("no_speech_prob") or 0) > 0.6 and (s.get("avg_logprob") or 0) < -1.0:
            continue
        out.append(Seg(round(float(s["start"]) + offset, 2), round(float(s["end"]) + offset, 2), text))
    if not out and (res.get("text") or "").strip():
        out.append(Seg(offset, offset + float(res.get("duration") or 0), res["text"].strip()))
    return out


class GroqTranscriber:
    name = "groq"

    def __init__(self):
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set in .env")
        self.client = httpx.Client(timeout=httpx.Timeout(600, connect=20))

    def _post(self, path: Path) -> dict:
        data = {
            "model": config.GROQ_ASR_MODEL,
            "response_format": "verbose_json",
            "temperature": "0",
            "timestamp_granularities[]": "segment",
        }
        if config.ASR_LANGUAGE:
            data["language"] = config.ASR_LANGUAGE
        last = "unknown error"
        for attempt in range(5):
            try:
                with open(path, "rb") as f:
                    r = self.client.post(
                        GROQ_URL,
                        headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                        data=data,
                        files={"file": (path.name, f)},
                    )
            except httpx.HTTPError as e:
                last = f"network error: {e}"
                time.sleep(2**attempt)
                continue
            if r.status_code == 200:
                return r.json()
            last = f"Groq ASR {r.status_code}: {r.text[:300]}"
            if r.status_code == 429 or r.status_code >= 500:
                wait = float(r.headers.get("retry-after") or 2**attempt)
                log.warning("%s, retrying in %.0fs", last, wait)
                time.sleep(min(wait, 60))
                continue
            break  # 4xx other than 429: do not retry
        raise RuntimeError(last)

    def transcribe(self, path: Path) -> Result:
        path = Path(path)
        tmp = Path(tempfile.mkdtemp(prefix="asr_"))
        try:
            dur = wav_duration(path)
            src = path
            if src.stat().st_size > GROQ_LIMIT:
                src = tmp / "audio.flac"
                ffmpeg(["-i", str(path), "-ar", "16000", "-ac", "1", "-map", "0:a", "-c:a", "flac", str(src)])
            if src.stat().st_size <= GROQ_LIMIT:
                res = self._post(src)
                return _parse_groq(res, 0.0), dur or res.get("duration"), res.get("language")

            total = dur or ffprobe_duration(path)
            if not total:
                raise RuntimeError("audio too large and its duration is unknown; cannot chunk")
            segs: list[Seg] = []
            lang = None
            offset, idx = 0.0, 0
            while offset < total:
                chunk = tmp / f"chunk{idx}.flac"
                ffmpeg(["-ss", str(offset), "-t", str(CHUNK_S + OVERLAP_S), "-i", str(path),
                        "-ar", "16000", "-ac", "1", "-map", "0:a", "-c:a", "flac", str(chunk)])
                res = self._post(chunk)
                lang = lang or res.get("language")
                lo = offset + (OVERLAP_S / 2 if idx else 0)
                hi = offset + CHUNK_S + OVERLAP_S / 2
                segs += [s for s in _parse_groq(res, offset) if lo <= s.start < hi]
                offset += CHUNK_S
                idx += 1
            return segs, total, lang
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class LocalWhisperTranscriber:
    name = "local"

    def __init__(self):
        from faster_whisper import WhisperModel  # optional dependency

        self.model = WhisperModel(config.WHISPER_MODEL, device="auto", compute_type="int8")

    def transcribe(self, path: Path) -> Result:
        segments, info = self.model.transcribe(
            str(path), vad_filter=True, language=config.ASR_LANGUAGE, condition_on_previous_text=False
        )
        out = [Seg(round(s.start, 2), round(s.end, 2), s.text.strip()) for s in segments if s.text.strip()]
        return out, info.duration, info.language


class FallbackTranscriber:
    """Groq first; on failure use local faster-whisper for that recording."""

    def __init__(self, primary: Transcriber):
        self.primary = primary
        self.name = f"{primary.name}+local"
        self._local: LocalWhisperTranscriber | None = None

    def transcribe(self, path: Path) -> Result:
        try:
            return self.primary.transcribe(path)
        except Exception as e:  # noqa: BLE001
            log.warning("primary ASR failed (%s); falling back to local whisper", e)
            if self._local is None:
                self._local = LocalWhisperTranscriber()
            return self._local.transcribe(path)


def build_transcriber() -> Transcriber:
    p = config.ASR_PROVIDER
    if p == "fake":
        return FakeTranscriber()
    if p == "local":
        return LocalWhisperTranscriber()
    try:
        primary = GroqTranscriber()
    except RuntimeError:
        if config.ASR_FALLBACK == "local":
            return LocalWhisperTranscriber()
        raise
    return FallbackTranscriber(primary) if config.ASR_FALLBACK == "local" else primary
