"""A fake insurance carrier portal used as a deterministic test target.

It behaves like the real thing in the ways that matter to Portolan:
- an HTML front end that calls internal JSON endpoints (the "hidden API")
- bearer-token login, with tokens that expire
- non-numeric business identifiers (POL-100234) alongside UUIDs
- read operations, write operations, and an irreversible one (bind)
- noise the compiler must ignore (telemetry beacons, static assets, HTML pages)

Nothing here talks to the network. Use `create_app()` with FastAPI's TestClient,
or run it with uvicorn to click around in a real browser:

    uvicorn portolan.testing.carrier_portal:app --port 8765
"""

from __future__ import annotations

import secrets
import time
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

USERS = {"broker@example.com": "hunter2"}
TOKEN_TTL_SECONDS = 15 * 60


class LoginIn(BaseModel):
    username: str
    password: str


class Insured(BaseModel):
    name: str
    province: str = Field(min_length=2, max_length=2)
    date_of_birth: str


class Vehicle(BaseModel):
    year: int
    make: str
    model: str


class Coverage(BaseModel):
    liability_limit: int
    deductible: int


class QuoteIn(BaseModel):
    line: str
    insured: Insured
    vehicle: Vehicle
    coverage: Coverage


class BindIn(BaseModel):
    effective_date: str
    payment_plan: str


PAGE = """<!doctype html>
<html><head><title>Acme Mutual Broker Portal</title></head>
<body>
<h1>Acme Mutual Broker Portal</h1>
<form id="login"><input name="username"><input name="password" type="password"><button>Sign in</button></form>
<div id="app"></div>
<script src="/static/app.js"></script>
</body></html>"""

APP_JS = """// The portal's front end. Every screen is backed by an /api/* call.
let token = null;
async function api(method, path, body) {
  const r = await fetch(path, {method, headers: {'Content-Type': 'application/json',
    ...(token ? {Authorization: 'Bearer ' + token} : {})}, body: body ? JSON.stringify(body) : undefined});
  navigator.sendBeacon && navigator.sendBeacon('/api/telemetry', JSON.stringify({event: method + ' ' + path}));
  return r.json();
}
document.getElementById('login').onsubmit = async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  token = (await api('POST', '/api/auth/login', {username: f.get('username'), password: f.get('password')})).token;
  const policies = await api('GET', '/api/policies?status=active');
  document.getElementById('app').textContent = JSON.stringify(policies, null, 2);
};
"""


def _seed_policies() -> dict[str, dict[str, Any]]:
    policies = {}
    for n, (name, line, premium) in enumerate(
        [("Jane Doe", "auto", 1840.0), ("Sam Lee", "home", 1210.5), ("Ana Ruiz", "auto", 2290.0)]
    ):
        number = f"POL-{100234 + n}"
        policies[number] = {
            "policy_number": number,
            "insured_name": name,
            "line": line,
            "status": "active",
            "annual_premium": premium,
            "effective_date": "2026-01-01",
            "expiry_date": "2027-01-01",
        }
    return policies


def create_app() -> FastAPI:
    app = FastAPI(title="Acme Mutual Broker Portal (fixture)")
    state: dict[str, Any] = {
        "tokens": {},
        "policies": _seed_policies(),
        "quotes": {},
        "telemetry": 0,
    }

    def require_auth(authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "missing token")
        token = authorization.removeprefix("Bearer ")
        expires = state["tokens"].get(token)
        if expires is None or expires < time.time():
            raise HTTPException(401, "token expired")
        return token

    # Hooks for evals and tests: inspect side effects, simulate session expiry.
    app.state.portal = state
    app.state.expire_sessions = state["tokens"].clear

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE

    @app.get("/quotes/new", response_class=HTMLResponse)
    def new_quote_page() -> str:
        return PAGE

    @app.get("/static/app.js", response_class=PlainTextResponse)
    def app_js() -> str:
        return APP_JS

    @app.post("/api/telemetry", status_code=204)
    async def telemetry(request: Request) -> None:
        await request.body()
        state["telemetry"] += 1

    @app.post("/api/logs")
    async def client_logs(request: Request) -> dict[str, bool]:
        # The front end ships its console logs here: JSON in, bare ack out. Noise, despite being JSON.
        await request.body()
        return {"ok": True}

    @app.post("/api/auth/login")
    def login(body: LoginIn) -> dict[str, Any]:
        if USERS.get(body.username) != body.password:
            raise HTTPException(401, "bad credentials")
        token = secrets.token_urlsafe(24)
        state["tokens"][token] = time.time() + TOKEN_TTL_SECONDS
        return {"token": token, "expires_in": TOKEN_TTL_SECONDS}

    @app.get("/api/me")
    def me(authorization: str | None = Header(None)) -> dict[str, Any]:
        require_auth(authorization)
        return {"broker_code": "BRK-0042", "name": "Example Brokerage", "province": "ON"}

    @app.get("/api/policies")
    def list_policies(
        status: str | None = None, page: int = 1, authorization: str | None = Header(None)
    ) -> dict[str, Any]:
        require_auth(authorization)
        items = [p for p in state["policies"].values() if status is None or p["status"] == status]
        return {"items": items, "page": page, "total": len(items)}

    @app.get("/api/policies/{policy_number}")
    def get_policy(policy_number: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        require_auth(authorization)
        if policy_number not in state["policies"]:
            raise HTTPException(404, "no such policy")
        return state["policies"][policy_number]

    @app.get("/api/policies/{policy_number}/documents")
    def list_documents(policy_number: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        require_auth(authorization)
        if policy_number not in state["policies"]:
            raise HTTPException(404, "no such policy")
        return {
            "items": [
                {"document_id": f"DOC-{policy_number[-6:]}-1", "kind": "declarations", "format": "pdf"},
                {"document_id": f"DOC-{policy_number[-6:]}-2", "kind": "pink_slip", "format": "pdf"},
            ]
        }

    @app.get("/api/policies/{policy_number}/events")
    def list_policy_events(policy_number: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        # A policy's activity history: a real resource whose name looks like telemetry.
        require_auth(authorization)
        policy = state["policies"].get(policy_number)
        if policy is None:
            raise HTTPException(404, "no such policy")
        ref = policy_number[-6:]
        return {
            "items": [
                {"event_id": f"EVT-{ref}-1", "type": "issued", "at": f"{policy['effective_date']}T09:00:00Z"},
                {"event_id": f"EVT-{ref}-2", "type": "renewal_notice_sent", "at": "2026-11-15T09:00:00Z"},
            ]
        }

    @app.post("/api/quotes")
    def create_quote(body: QuoteIn, authorization: str | None = Header(None)) -> dict[str, Any]:
        require_auth(authorization)
        base = 900 if body.line == "auto" else 700
        premium = base + body.coverage.liability_limit / 2000 - body.coverage.deductible / 10
        quote = {
            "quote_id": str(uuid.uuid4()),
            "status": "quoted",
            "line": body.line,
            "insured_name": body.insured.name,
            "annual_premium": round(premium, 2),
            "valid_until": "2026-12-31",
        }
        state["quotes"][quote["quote_id"]] = quote
        return quote

    @app.get("/api/quotes/{quote_id}")
    def get_quote(quote_id: str, authorization: str | None = Header(None)) -> dict[str, Any]:
        require_auth(authorization)
        if quote_id not in state["quotes"]:
            raise HTTPException(404, "no such quote")
        return state["quotes"][quote_id]

    @app.post("/api/quotes/{quote_id}/bind")
    def bind_quote(quote_id: str, body: BindIn, authorization: str | None = Header(None)) -> dict[str, Any]:
        require_auth(authorization)
        quote = state["quotes"].get(quote_id)
        if quote is None:
            raise HTTPException(404, "no such quote")
        if quote["status"] != "quoted":
            raise HTTPException(409, "quote already bound")
        number = f"POL-{100234 + len(state['policies'])}"
        quote["status"] = "bound"
        state["policies"][number] = {
            "policy_number": number,
            "insured_name": quote["insured_name"],
            "line": quote["line"],
            "status": "active",
            "annual_premium": quote["annual_premium"],
            "effective_date": body.effective_date,
            "expiry_date": "2027-" + body.effective_date[5:],
        }
        return {"policy_number": number, "status": "bound", "quote_id": quote_id}

    return app


app = create_app()
