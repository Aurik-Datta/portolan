"""Scripted browsing sessions against fixture apps.

These stand in for a human clicking through the portal with a recorder running:
they make the same calls the front end would, in the same order, and save a HAR.
Because they run in-process (no browser, no network), they are free and
deterministic, which makes them the backbone of the eval loop.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from portolan.har import HarWriter, RecordingClient
from portolan.testing import legacy_erp
from portolan.testing.carrier_portal import create_app

BASE_URL = "http://portal.test"
ERP_BASE_URL = "http://erp.test"


def record_carrier_portal_session(out: str | Path | None = None) -> HarWriter:
    """Log in, browse policies, create two quotes, bind one. Returns the HAR."""
    client = TestClient(create_app(), base_url=BASE_URL)
    rec = RecordingClient(client)

    # Front end loads: HTML + JS (noise the compiler must drop).
    rec.get("/")
    rec.get("/static/app.js")

    token = rec.post("/api/auth/login", json={"username": "broker@example.com", "password": "hunter2"}).json()[
        "token"
    ]
    auth = {"Authorization": f"Bearer {token}"}

    def beacon(event: str) -> None:
        rec.post("/api/telemetry", content=f'{{"event": "{event}"}}', headers={"content-type": "text/plain"})

    rec.get("/api/me", headers=auth)
    beacon("me")

    policies = rec.get("/api/policies", params={"status": "active"}, headers=auth).json()["items"]
    rec.get("/api/policies", params={"status": "active", "page": 2}, headers=auth)
    beacon("policies")

    # Open two different policies so the compiler sees the id vary.
    for p in policies[:2]:
        rec.get(f"/api/policies/{p['policy_number']}", headers=auth)
        rec.get(f"/api/policies/{p['policy_number']}/documents", headers=auth)

    rec.get("/quotes/new")

    quote_ids = []
    for insured, vehicle, deductible in [
        ({"name": "Priya Shah", "province": "ON", "date_of_birth": "1991-04-12"},
         {"year": 2021, "make": "Toyota", "model": "Corolla"}, 500),
        ({"name": "Marc Tremblay", "province": "QC", "date_of_birth": "1985-11-02"},
         {"year": 2018, "make": "Honda", "model": "Civic"}, 1000),
    ]:
        quote = rec.post(
            "/api/quotes",
            json={
                "line": "auto",
                "insured": insured,
                "vehicle": vehicle,
                "coverage": {"liability_limit": 2_000_000, "deductible": deductible},
            },
            headers=auth,
        ).json()
        quote_ids.append(quote["quote_id"])
        rec.get(f"/api/quotes/{quote['quote_id']}", headers=auth)
        beacon("quote")

    rec.post(
        f"/api/quotes/{quote_ids[0]}/bind",
        json={"effective_date": "2026-11-01", "payment_plan": "monthly"},
        headers=auth,
    )

    if out is not None:
        rec.writer.save(out)
    return rec.writer


def record_legacy_erp_session(out: str | Path | None = None) -> HarWriter:
    """Log in, list invoices, open one, create one, void one. All through POST /rpc."""
    client = TestClient(legacy_erp.create_app(), base_url=ERP_BASE_URL)
    rec = RecordingClient(client)

    rec.get("/")
    csrf = rec.post("/session", json={"user": "clerk", "password": "ledger2009"}).json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf}

    def rpc(method: str, **params: object) -> dict:
        return rec.post("/rpc", json={"method": method, "params": params}, headers=headers).json()

    rpc("invoice.list", status="open")
    rpc("invoice.list")
    rpc("invoice.get", id=1001)
    rpc("invoice.get", id=1002)
    created = rpc("invoice.create", customer="Initech", amount=990.0, currency="CAD")["result"]
    rpc("invoice.create", customer="Umbrella", amount=120.25)
    rpc("invoice.void", id=created["id"])

    if out is not None:
        rec.writer.save(out)
    return rec.writer
