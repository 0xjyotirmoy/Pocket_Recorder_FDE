"""LLM providers. Every call returns a parsed JSON object."""
import json
import logging
import re
import threading
import time
from typing import Protocol

import httpx

from .. import config

log = logging.getLogger("llm")


class LLMError(Exception):
    pass


class LLM(Protocol):
    model: str

    def complete_json(self, system: str, user: str) -> dict: ...


def extract_json(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        v = json.loads(t)
        if isinstance(v, dict):
            return v
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        try:
            v = json.loads(m.group(0))
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            pass
    raise LLMError("model did not return valid JSON")


class OpenAICompatLLM:
    """Works with Groq, Gemini (OpenAI-compatible endpoint), OpenRouter, Ollama, etc."""

    def __init__(self):
        if not config.LLM_API_KEY and "localhost" not in config.LLM_BASE_URL:
            raise LLMError("LLM_API_KEY (or GROQ_API_KEY) is not set in .env")
        self.model = config.LLM_MODEL
        self.url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
        self.client = httpx.Client(timeout=httpx.Timeout(120, connect=20))
        self.json_mode = True

    def complete_json(self, system: str, user: str) -> dict:
        last = "unknown error"
        for attempt in range(4):
            body = {
                "model": self.model,
                "temperature": 0.1,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            }
            if self.json_mode:
                body["response_format"] = {"type": "json_object"}
            try:
                r = self.client.post(
                    self.url, headers={"Authorization": f"Bearer {config.LLM_API_KEY}"}, json=body
                )
            except httpx.HTTPError as e:
                last = f"network error: {e}"
                time.sleep(2**attempt)
                continue
            if r.status_code == 200:
                try:
                    content = r.json()["choices"][0]["message"]["content"] or ""
                    return extract_json(content)
                except (KeyError, IndexError, ValueError, LLMError) as e:
                    last = f"bad model output: {e}"
                    continue
            last = f"LLM {r.status_code}: {r.text[:300]}"
            if r.status_code == 400 and "json_validate_failed" in r.text:
                continue  # model produced invalid JSON in JSON mode: just try again
            if r.status_code == 400 and self.json_mode:
                self.json_mode = False  # model/provider without JSON mode: retry as plain text
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(float(r.headers.get("retry-after") or 2**attempt), 30))
                continue
            break
        raise LLMError(last)


FAKE_STATE: dict = {}


class FakeLLM:
    """Deterministic stand-in used by tests and by LLM_PROVIDER=fake."""

    model = "fake"

    def complete_json(self, system: str, user: str) -> dict:
        if FAKE_STATE.get("raise"):
            raise LLMError("simulated LLM failure")
        ids = [int(i) for i in re.findall(r"\[S(\d+)\]", user)]
        if "TASK:EXTRACT" in system:
            sid = ids[1] if len(ids) > 1 else (ids[0] if ids else None)
            return {
                "title": "Vendor call",
                "summary": "The team agreed next steps with the vendor.",
                "topics": ["Purchase order", "Delivery logistics"],
                "keywords": ["purchase order", "delivery", "vendor", "Thursday"],
                "key_points": ["Purchase order timing agreed"],
                "decisions": ["Send the purchase order this week"],
                "action_items": [
                    {"who": "We", "what": "Send the purchase order", "due_text": "Thursday", "due_date": None, "segment_id": sid},
                    {"who": "Ghost", "what": "Hallucinated task", "due_text": None, "segment_id": 999999},
                ],
                "meetings": [],
                "people": [{"name": "Vendor", "role": "supplier", "segment_id": sid}],
            }
        question = (re.search(r"QUESTION:\s*(.*)", user) or [None, ""])[1].lower()
        if "TASK:ACTION" in system and FAKE_STATE.get("no_action"):
            return {"answer": "Which recipient?", "cited_segment_ids": []}  # model refuses -> server fallback
        if FAKE_STATE.get("hallucinate"):
            return {"answer": "Made up [S999999].", "cited_segment_ids": [999999], "action": None}
        if "TASK:ACTION" in system and re.search(r"\b(e-?mail|mail|draft)\b", question):
            return {
                "answer": "Here is a draft.",
                "cited_segment_ids": ids[:1], "tool": "draft_email",
                "args": {"to": "vendor@example.com", "subject": "PO", "body": "We will send the PO by Thursday."},
            }
        if "TASK:ACTION" in system:
            return {
                "answer": "I can add that to your calendar.",
                "cited_segment_ids": ids[:1], "tool": "create_calendar_event",
                "args": {"title": "PO follow-up", "start": "2026-11-06T10:00:00+05:30",
                         "end": "2026-11-06T10:30:00+05:30", "attendees": ["vendor@example.com"]},
            }
        if ids and "purchase" in question:
            return {"answer": f"We promised to send the purchase order by Thursday [S{ids[0]}].",
                    "cited_segment_ids": [ids[0]], "action": None}
        return {"answer": "No supporting evidence.", "cited_segment_ids": [], "action": None}


_llm = None
_lock = threading.Lock()


def get_llm() -> LLM:
    global _llm
    with _lock:
        if _llm is None:
            _llm = FakeLLM() if config.LLM_PROVIDER == "fake" else OpenAICompatLLM()
        return _llm
