import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from test_graph import build_two_paper_graph

from paper_rag.agent.tools import ToolBox
from paper_rag.api.access import AccessManager
from paper_rag.api.admin import create_admin_app
from paper_rag.api.server import SESSION_COOKIE, create_public_app
from paper_rag.api.state import AppState
from paper_rag.ingest.vectorstore import VectorStore

ADMIN_TOKEN = "test-admin-token"


class FakeAgent:
    def __init__(self):
        self.questions: list[str] = []

    async def run(self, question, history=None):
        self.questions.append(question)
        yield {"type": "tool_call", "id": "t1", "name": "find_entities", "input": {"query": "RAG"}, "round": 0}
        yield {"type": "tool_result", "id": "t1", "name": "find_entities", "summary": "1 entities", "is_error": False,
               "node_ids": ["entity:retrieval augmented generation"], "link_ids": []}
        yield {"type": "text", "delta": "RAG uses DPR [rag p.2].", "round": 1}
        yield {"type": "citations", "passages": []}
        yield {"type": "done", "usage": {"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 0,
                                         "cache_creation_input_tokens": 0}, "node_ids": [], "link_ids": [],
               "model": "claude-opus-5"}


def make_state(settings, embedder, public: bool) -> AppState:
    kg = build_two_paper_graph()
    vs = VectorStore(settings.chroma_dir)
    access = AccessManager(settings.access_db_path, default_hours=1, default_quota=5) if public else None
    return AppState(settings, kg, vs, ToolBox(kg, vs, embedder), FakeAgent(), access, asyncio.Semaphore(2))


def sse_events(body: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in body.splitlines() if line.startswith("data: ")]


@pytest.fixture
def local_client(settings, embedder):
    return TestClient(create_public_app(make_state(settings, embedder, public=False)))


@pytest.fixture
def public(settings, embedder):
    state = make_state(settings, embedder, public=True)
    app = TestClient(create_public_app(state))
    admin = TestClient(create_admin_app(state.access, ADMIN_TOKEN, settings.frontend_dist, 8000),
                       headers={"x-admin-token": ADMIN_TOKEN})
    return state, app, admin


def request_access(app: TestClient, name="Ada") -> tuple[str, str]:
    r = app.post("/api/access/request", json={"name": name, "reason": "research"})
    assert r.status_code == 200, r.text
    return r.json()["request_id"], r.json()["claim_secret"]


def grant(app, admin, **approve) -> None:
    rid, secret = request_access(app)
    assert admin.post(f"/admin/api/requests/{rid}/approve", json=approve).status_code == 200
    r = app.get(f"/api/access/status/{rid}", headers={"x-claim-secret": secret})
    assert r.json()["status"] == "approved" and SESSION_COOKIE in r.cookies


# ---------------------------------------------------------------- local mode
def test_local_mode_is_open(local_client):
    assert local_client.get("/api/access/me").json() == {"gated": False, "authorized": True}
    graph = local_client.get("/api/graph").json()
    assert graph["stats"]["papers"] == 2 and graph["links"]
    assert local_client.get("/api/node/RAG").json()["type"] == "Method"
    assert local_client.post("/api/access/request", json={"name": "x"}).status_code == 404
    events = sse_events(local_client.post("/api/chat", json={"question": "What is RAG?"}).text)
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "text", "citations", "done"]


def test_frontend_fallback_when_not_built(local_client):
    r = local_client.get("/")
    assert r.status_code == 200 and "Frontend not built" in r.text


# ---------------------------------------------------------------- public mode
def test_public_mode_requires_approval(public):
    state, app, admin = public
    assert app.get("/api/graph").status_code == 401
    assert app.post("/api/chat", json={"question": "hi"}).status_code == 401
    assert app.get("/api/access/me").json()["authorized"] is False

    rid, secret = request_access(app)
    assert app.get(f"/api/access/status/{rid}", headers={"x-claim-secret": secret}).json()["status"] == "pending"
    assert [p["id"] for p in admin.get("/admin/api/state").json()["pending"]] == [rid]

    admin.post(f"/admin/api/requests/{rid}/approve", json={"quota": 2})
    assert app.get(f"/api/access/status/{rid}", headers={"x-claim-secret": "wrong"}).status_code == 404
    r = app.get(f"/api/access/status/{rid}", headers={"x-claim-secret": secret})
    assert r.json()["status"] == "approved"
    # the token is issued only once
    assert app.get(f"/api/access/status/{rid}", headers={"x-claim-secret": secret}).json()["status"] == "claimed"

    assert app.get("/api/graph").status_code == 200
    me = app.get("/api/access/me").json()
    assert me["authorized"] and me["questions_left"] == 2

    events = sse_events(app.post("/api/chat", json={"question": "q1"}).text)
    assert events[-1]["type"] == "done" and events[-1]["questions_left"] == 1
    session = admin.get("/admin/api/state").json()["sessions"][0]
    assert session["questions_used"] == 1 and session["cost_usd"] > 0

    assert app.post("/api/chat", json={"question": "q2"}).status_code == 200
    r = app.post("/api/chat", json={"question": "q3"})
    assert r.status_code == 429 and r.json()["error"] == "quota"


def test_deny_revoke_and_pause(public):
    state, app, admin = public
    rid, secret = request_access(app)
    admin.post(f"/admin/api/requests/{rid}/deny")
    assert app.get(f"/api/access/status/{rid}", headers={"x-claim-secret": secret}).json()["status"] == "denied"

    grant(app, admin)
    assert app.get("/api/graph").status_code == 200
    sid = admin.get("/admin/api/state").json()["sessions"][0]["id"]
    admin.post(f"/admin/api/sessions/{sid}/revoke")
    r = app.get("/api/graph")
    assert r.status_code == 401 and r.json()["error"] == "revoked"

    admin.post("/admin/api/pause", json={"paused": True})
    r = app.post("/api/access/request", json={"name": "Bob"})
    assert r.status_code == 503 and r.json()["error"] == "paused"


def test_abuse_limits(public):
    _, app, _ = public
    for _ in range(3):
        request_access(app)
    assert app.post("/api/access/request", json={"name": "Ada"}).status_code == 429
    assert app.post("/api/access/request", json={"name": "   "}).status_code == 400


def test_admin_routes_not_on_public_app(public):
    _, app, _ = public
    assert app.get("/admin/api/state").status_code == 404
    assert app.post("/admin/api/pause", json={"paused": True}).status_code in (404, 405)
    assert app.get("/admin.html").status_code == 404


def test_admin_requires_token(public, settings):
    state, _, _ = public
    bare = TestClient(create_admin_app(state.access, ADMIN_TOKEN, settings.frontend_dist, 8000))
    assert bare.get("/admin/api/state").status_code == 401
    assert bare.get("/").status_code == 401
    assert bare.get("/?token=nope").status_code == 401
    r = bare.get(f"/?token={ADMIN_TOKEN}", follow_redirects=False)
    assert r.status_code == 303 and "prag_admin" in r.cookies
    assert bare.get("/admin/api/state").status_code == 200


def test_admin_login_link_gives_unlimited_session(public):
    _, app, admin = public
    url = admin.post("/admin/api/app-session").json()["url"]
    code = url.split("code=", 1)[1]
    r = app.get(f"/api/access/redeem?code={code}", follow_redirects=False)
    assert r.status_code == 303
    me = app.get("/api/access/me").json()
    assert me["authorized"] and me["is_admin"] and me["questions_left"] is None
    # single use
    assert app.get(f"/api/access/redeem?code={code}", follow_redirects=False).status_code == 400
