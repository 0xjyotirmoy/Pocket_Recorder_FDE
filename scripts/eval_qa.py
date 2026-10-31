"""Evaluation harness: asks golden questions against the running server and scores the answers.

    python manage.py eval            (or: python scripts/eval_qa.py --server http://localhost:8000)

Checks per question: grounded vs. abstain as expected, expected words present, cited recording correct.
Edit scripts/golden_qa.json to match the recordings you test with (the build-day samples)."""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

p = argparse.ArgumentParser()
p.add_argument("--server", default="http://localhost:8000")
p.add_argument("--file", default=str(Path(__file__).with_name("golden_qa.json")))
a = p.parse_args()

cases = json.loads(Path(a.file).read_text(encoding="utf-8"))
ok = 0
print(f"\n{'#':>2}  {'result':6}  {'time':>5}  question")
for i, c in enumerate(cases, 1):
    t0 = time.time()
    try:
        r = httpx.post(f"{a.server}/chat", json={"message": c["q"]}, timeout=120).json()
    except Exception as e:  # noqa: BLE001
        print(f"{i:>2}  ERROR   {'':>5}  {c['q']}  ({e})")
        continue
    dt = time.time() - t0
    problems = []
    if c.get("expect") == "abstain" and r.get("grounded"):
        problems.append("should say it's not in the recordings")
    if c.get("expect") == "grounded" and not r.get("grounded"):
        problems.append("abstained but the answer exists")
    if c.get("expect") == "action" and not r.get("pending_action"):
        problems.append("no confirm card")
    if c.get("tool") and (r.get("pending_action") or {}).get("tool") != c["tool"]:
        problems.append(f"expected {c['tool']}")
    text = (r.get("answer") or "").lower() + json.dumps(r.get("pending_action") or {}).lower()
    for w in c.get("contains", []):
        if w.lower() not in text:
            problems.append(f"missing '{w}'")
    if c.get("recording") and not any(c["recording"].lower() in (s.get("title") or "").lower() for s in r.get("sources", [])):
        problems.append(f"no source from '{c['recording']}'")
    ok += not problems
    print(f"{i:>2}  {'PASS' if not problems else 'FAIL':6}  {dt:4.1f}s  {c['q']}")
    if problems:
        print(f"{'':>17}{'; '.join(problems)}\n{'':>17}answer: {(r.get('answer') or '')[:140]}")
print(f"\n{ok}/{len(cases)} passed")
sys.exit(0 if ok == len(cases) else 1)
