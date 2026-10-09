import pytest

from portolan.compiler import classify_risk, is_id_segment, operation_name, templatize
from portolan.har import Exchange, is_api_call


@pytest.mark.parametrize(
    "segment,expected",
    [
        ("123", True),
        ("POL-100234", True),
        ("2c1d5539-0b6e-4a8a-9f3e-6a1f0d6c2b11", True),
        ("a3f9c2e17b04d5e6", True),
        ("v2", False),
        ("api", False),
        ("policies", False),
        ("new", False),
        # digits alone don't make an id: versions, product names, feature slugs
        ("v2beta", False),
        ("oauth2", False),
        ("2fa-setup", False),
        ("x86_64", False),
        ("covid19", False),
        # but real ids still do: long digit runs, random mixed-case tokens
        ("INV2024001", True),
        ("V1StGXR8_Z5jdHi6B-myT", True),
    ],
)
def test_id_segments(segment, expected):
    assert is_id_segment(segment) is expected


def _exchange(method: str, path: str, response_json=None, status: int = 200) -> Exchange:
    return Exchange(
        method=method, url=f"http://app.test{path}", path=path, query={}, request_headers={},
        request_json={"x": 1} if method != "GET" else None, status=status, response_headers={},
        response_mime="application/json" if response_json is not None else "", response_json=response_json,
    )


@pytest.mark.parametrize(
    "method,path,response,keep",
    [
        # unambiguous instrumentation is always noise
        ("POST", "/api/telemetry", {"ok": True}, False),
        ("POST", "/collect", {"ok": True}, False),
        ("GET", "/api/analytics/config", {"sample_rate": 0.1}, False),
        # events / logs / metrics are often real resources: keep them when they carry data
        ("GET", "/api/events", {"items": [{"id": 1}]}, True),
        ("GET", "/api/calendar/events/12", {"id": 12, "title": "Renewal"}, True),
        ("POST", "/api/calendar/events", {"id": 13, "title": "Call"}, True),
        ("GET", "/api/audit/logs", {"items": []}, True),
        ("GET", "/api/metrics/revenue", {"total": 1200.0}, True),
        # ...and drop them when they're fire-and-forget writes that return nothing useful
        ("POST", "/api/logs", {"ok": True}, False),
        ("POST", "/api/events", None, False),
        ("PUT", "/metrics", {}, False),
    ],
)
def test_noise_filter(method, path, response, keep):
    assert is_api_call(_exchange(method, path, response))[0] is keep


def test_templatize_names_params_after_parent_resource():
    template, names, values = templatize("/api/policies/POL-100234/documents/DOC-100234-1")
    assert template == "/api/policies/{policy_id}/documents/{document_id}"
    assert names == ["policy_id", "document_id"]
    assert values == ["POL-100234", "DOC-100234-1"]


@pytest.mark.parametrize(
    "method,template,name",
    [
        ("GET", "/api/policies", "list_policies"),
        ("GET", "/api/policies/{policy_id}", "get_policy"),
        ("GET", "/api/policies/{policy_id}/documents", "list_policy_documents"),
        ("POST", "/api/quotes", "create_quote"),
        ("POST", "/api/quotes/{quote_id}/bind", "bind_quote"),
        ("DELETE", "/api/v2/users/{user_id}", "delete_user"),
        ("PATCH", "/api/accounts/{account_id}", "update_account"),
        ("GET", "/api/me", "get_me"),
    ],
)
def test_operation_names(method, template, name):
    assert operation_name(method, template) == name


def test_risk_classification():
    assert classify_risk("GET", "list_policies") == "read"
    assert classify_risk("POST", "create_quote") == "write"
    assert classify_risk("POST", "bind_quote") == "irreversible"
    assert classify_risk("DELETE", "remove_thing") == "irreversible"


def test_catalog_from_portal(portal_catalog):
    keys = {op.key for op in portal_catalog.operations}
    assert "POST /api/quotes/{quote_id}/bind" in keys
    # noise, HTML, static assets and the login call are not tools
    assert not any("telemetry" in k or "login" in k or k.endswith(" /") for k in keys)
    assert portal_catalog.dropped["instrumentation"] == 5


def test_auth_detected_and_login_hidden(portal_catalog):
    auth = portal_catalog.auth
    assert auth is not None
    assert auth.login_path == "/api/auth/login"
    assert auth.credential_fields == ["password", "username"]
    assert (auth.header, auth.scheme, auth.token_json_path) == ("authorization", "Bearer", "token")


def test_schemas_inferred(portal_catalog):
    op = portal_catalog.get("create_quote")
    body = op.input_schema["properties"]["body"]
    assert body["properties"]["vehicle"]["properties"]["year"]["type"] == "integer"
    assert body["properties"]["insured"]["properties"]["date_of_birth"]["format"] == "date"
    assert op.output_schema["properties"]["quote_id"]["format"] == "uuid"

    listing = portal_catalog.get("list_policies")
    assert listing.input_schema["required"] == ["status"]  # page was only sent once
    assert listing.input_schema["properties"]["page"]["type"] == "integer"


def test_examples_are_redacted(portal_har):
    from portolan.compiler import redact

    assert redact({"username": "u", "password": "p", "nested": {"api_key": "k"}}) == {
        "username": "u", "password": "***", "nested": {"api_key": "***"}
    }
