"""A fake legacy ERP: the shape of app Portolan is weakest on today.

What makes it hard (on purpose):
- RPC style: every operation is POST /rpc with {"method": "invoice.create", ...}.
  A path-based compiler collapses all of them into one meaningless "rpc" tool.
- Cookie session plus a CSRF token that must be echoed in a header.
- Numeric ids inside bodies rather than in paths.

Run it for manual exploration:  uvicorn portolan.testing.legacy_erp:app --port 8766
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import Cookie, FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


class LoginIn(BaseModel):
    user: str
    pass_: str | None = None
    password: str | None = None


class RpcIn(BaseModel):
    method: str
    params: dict[str, Any] = {}


def create_app() -> FastAPI:
    app = FastAPI(title="Northwind Ledger 2009 (fixture)")
    state: dict[str, Any] = {
        "sessions": {},  # session id -> csrf token
        "invoices": {
            1001: {"id": 1001, "customer": "Acme Co", "amount": 1250.0, "currency": "CAD", "status": "open"},
            1002: {"id": 1002, "customer": "Globex", "amount": 480.5, "currency": "CAD", "status": "paid"},
        },
        "next_id": 1003,
    }
    app.state.erp = state
    app.state.expire_sessions = state["sessions"].clear

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return "<html><body><h1>Northwind Ledger</h1><script src='/js/ledger.min.js'></script></body></html>"

    @app.post("/session")
    def login(body: LoginIn, response: Response) -> dict[str, Any]:
        if body.user != "clerk" or (body.password or body.pass_) != "ledger2009":
            raise HTTPException(401, "bad credentials")
        sid, csrf = secrets.token_hex(16), secrets.token_hex(20)
        state["sessions"][sid] = csrf
        response.set_cookie("LEDGERSESSID", sid, httponly=True)
        return {"ok": True, "csrf_token": csrf, "user": {"name": "clerk", "role": "ap"}}

    @app.post("/rpc")
    def rpc(
        body: RpcIn,
        ledgersessid: str | None = Cookie(None, alias="LEDGERSESSID"),
        x_csrf_token: str | None = Header(None),
    ) -> dict[str, Any]:
        if not ledgersessid or state["sessions"].get(ledgersessid) is None:
            raise HTTPException(401, "session expired")
        if state["sessions"][ledgersessid] != x_csrf_token:
            raise HTTPException(403, "bad csrf token")
        p = body.params
        invoices = state["invoices"]
        if body.method == "invoice.list":
            items = [i for i in invoices.values() if p.get("status") in (None, i["status"])]
            return {"result": items, "error": None}
        if body.method == "invoice.get":
            inv = invoices.get(int(p["id"]))
            if inv is None:
                return {"result": None, "error": {"code": 404, "message": "not found"}}
            return {"result": inv, "error": None}
        if body.method == "invoice.create":
            inv = {"id": state["next_id"], "customer": p["customer"], "amount": float(p["amount"]),
                   "currency": p.get("currency", "CAD"), "status": "open"}
            invoices[inv["id"]] = inv
            state["next_id"] += 1
            return {"result": inv, "error": None}
        if body.method == "invoice.void":
            inv = invoices.get(int(p["id"]))
            if inv is None or inv["status"] != "open":
                return {"result": None, "error": {"code": 409, "message": "cannot void"}}
            inv["status"] = "void"
            return {"result": inv, "error": None}
        return {"result": None, "error": {"code": 400, "message": f"unknown method {body.method}"}}

    return app


app = create_app()
