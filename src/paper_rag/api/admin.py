"""Admin console app. Bound to 127.0.0.1 on its own port, which the Cloudflare tunnel never exposes.

Loopback checks alone are not enough (cloudflared also connects from 127.0.0.1), so isolation comes
from the separate port, plus a per-start admin token (printed to the terminal) exchanged for a cookie.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from paper_rag.api.access import AccessError, AccessManager
from paper_rag.api.sse import sse_response

ADMIN_COOKIE = "prag_admin"

LOCKED_HTML = """<!doctype html><meta charset="utf-8"><title>Admin</title>
<body style="font-family:system-ui;background:#0b0f19;color:#e6e9f2;padding:3rem">
<h1>Admin console</h1><p>Open the admin URL printed in the server terminal (it contains a one-time token).</p></body>"""


class ApproveBody(BaseModel):
    hours: float | None = None
    quota: int | None = None
    unlimited: bool = False


class PauseBody(BaseModel):
    paused: bool


def create_admin_app(access: AccessManager, admin_token: str, dist: Path, app_port: int) -> FastAPI:
    app = FastAPI(title="Paper RAG admin", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(AccessError)
    async def _access_error(_: Request, exc: AccessError) -> JSONResponse:
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status)

    def authed(request: Request) -> bool:
        supplied = request.cookies.get(ADMIN_COOKIE) or request.headers.get("x-admin-token") or ""
        return secrets.compare_digest(supplied, admin_token)

    def require_admin(request: Request) -> None:
        if not authed(request):
            raise HTTPException(401, "Admin token required")

    @app.get("/admin/api/state", dependencies=[Depends(require_admin)])
    def get_state() -> dict[str, Any]:
        return access.snapshot()

    @app.get("/admin/api/events", dependencies=[Depends(require_admin)])
    async def events(request: Request) -> Response:
        async def feed() -> AsyncIterator[dict[str, Any]]:
            seen = -1
            while not await request.is_disconnected():
                if access.version != seen:
                    seen = access.version
                    yield {"type": "snapshot", **access.snapshot()}
                await asyncio.sleep(1.0)

        return sse_response(request, feed())

    @app.post("/admin/api/requests/{request_id}/approve", dependencies=[Depends(require_admin)])
    def approve(request_id: str, body: ApproveBody) -> dict[str, str]:
        access.approve(request_id, body.hours, body.quota, body.unlimited)
        return {"status": "approved"}

    @app.post("/admin/api/requests/{request_id}/deny", dependencies=[Depends(require_admin)])
    def deny(request_id: str) -> dict[str, str]:
        access.deny(request_id)
        return {"status": "denied"}

    @app.post("/admin/api/sessions/{session_id}/revoke", dependencies=[Depends(require_admin)])
    def revoke(session_id: str) -> dict[str, str]:
        access.revoke(session_id)
        return {"status": "revoked"}

    @app.post("/admin/api/pause", dependencies=[Depends(require_admin)])
    def pause(body: PauseBody) -> dict[str, bool]:
        access.set_paused(body.paused)
        return {"paused": body.paused}

    @app.post("/admin/api/app-session", dependencies=[Depends(require_admin)])
    def app_session() -> dict[str, str]:
        code = access.create_admin_login_code()
        return {"url": f"http://127.0.0.1:{app_port}/api/access/redeem?code={code}"}

    @app.get("/{path:path}", include_in_schema=False)
    def console(path: str, request: Request, token: str | None = None) -> Response:
        if token is not None:
            if not secrets.compare_digest(token, admin_token):
                return HTMLResponse(LOCKED_HTML, status_code=401)
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(ADMIN_COOKIE, admin_token, httponly=True, samesite="strict", path="/")
            return response
        candidate = (dist / path).resolve()
        if path.startswith("assets/") and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        if not authed(request):
            return HTMLResponse(LOCKED_HTML, status_code=401)
        if not (dist / "admin.html").exists():
            return HTMLResponse("<p>Frontend not built. Run <code>npm run build</code> in <code>frontend/</code>.</p>")
        return FileResponse(dist / "admin.html")

    return app
