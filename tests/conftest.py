from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from portolan.catalog import Catalog
from portolan.compiler import compile_har
from portolan.runtime import Executor
from portolan.testing.carrier_portal import create_app
from portolan.testing.sessions import BASE_URL, record_carrier_portal_session

CREDS = {"username": "broker@example.com", "password": "hunter2"}


@pytest.fixture(scope="session")
def portal_har(tmp_path_factory: pytest.TempPathFactory):
    path = tmp_path_factory.mktemp("rec") / "portal.har"
    record_carrier_portal_session(path)
    return path


@pytest.fixture(scope="session")
def portal_catalog(portal_har) -> Catalog:
    return compile_har(portal_har, app="acme", base_url=BASE_URL)


@pytest.fixture
def portal_app():
    return create_app()


@pytest.fixture
def executor(portal_catalog, portal_app, tmp_path) -> Executor:
    client = TestClient(portal_app, base_url=BASE_URL)
    return Executor(portal_catalog, client=client, credentials=dict(CREDS), audit_log=tmp_path / "audit.jsonl")
