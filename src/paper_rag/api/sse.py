"""Server-sent events with heartbeats (keeps Cloudflare's ~100 s idle timeout at bay)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import StreamingResponse

log = logging.getLogger(__name__)

HEARTBEAT_S = 15.0
SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


def format_event(event: dict[str, Any]) -> str:
    return f"event: {event.get('type', 'message')}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


async def _pump(request: Request, events: AsyncIterator[dict[str, Any]], on_close: Callable[[], None] | None):
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def producer() -> None:
        try:
            async for event in events:
                await queue.put(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("SSE producer failed")
            await queue.put({"type": "error", "message": "Internal server error."})
        finally:
            await queue.put(None)

    task = asyncio.create_task(producer())
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
            except TimeoutError:
                if await request.is_disconnected():
                    break
                yield ": ping\n\n"
                continue
            if event is None:
                break
            yield format_event(event)
    finally:
        task.cancel()
        if on_close:
            on_close()


def sse_response(request: Request, events: AsyncIterator[dict[str, Any]],
                 on_close: Callable[[], None] | None = None) -> StreamingResponse:
    return StreamingResponse(_pump(request, events, on_close), media_type="text/event-stream", headers=SSE_HEADERS)
