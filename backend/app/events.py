"""In-process event bus -> Server-Sent Events (GET /events).

The worker thread publishes ("recording", id, status) as soon as anything changes; every open
dashboard gets it immediately and refreshes only what changed. No polling delay, no extra infra."""
import asyncio
import json
import threading
import time

_subs: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
_lock = threading.Lock()


def publish(kind: str, **data) -> None:
    msg = json.dumps({"kind": kind, "ts": time.time(), **data})
    with _lock:
        subs = list(_subs)
    for loop, q in subs:
        try:
            loop.call_soon_threadsafe(q.put_nowait, msg)
        except RuntimeError:  # loop closed
            pass


async def stream():
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    sub = (loop, q)
    with _lock:
        _subs.add(sub)
    try:
        yield "retry: 3000\n\n"
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15)
                yield f"data: {msg}\n\n"
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
    finally:
        with _lock:
            _subs.discard(sub)
