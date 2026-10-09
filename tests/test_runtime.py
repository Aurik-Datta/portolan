import json

import pytest

from portolan.runtime import OperationError

QUOTE = {
    "line": "auto",
    "insured": {"name": "T Test", "province": "ON", "date_of_birth": "1990-01-01"},
    "vehicle": {"year": 2020, "make": "Kia", "model": "Soul"},
    "coverage": {"liability_limit": 1_000_000, "deductible": 500},
}


def test_read_runs_immediately(executor):
    result = executor.call("list_policies", {"status": "active"})
    assert result["ok"] and result["data"]["total"] == 3


def test_write_is_dry_run_without_confirm(executor, portal_app):
    result = executor.call("create_quote", {"body": QUOTE})
    assert result["dry_run"] is True
    assert result["would_send"]["json"] == QUOTE
    assert portal_app.state.portal["quotes"] == {}  # nothing happened


def test_write_executes_with_confirm(executor, portal_app):
    result = executor.call("create_quote", {"body": QUOTE}, confirm=True)
    assert result["ok"]
    assert result["data"]["quote_id"] in portal_app.state.portal["quotes"]


def test_confirm_can_come_from_args(executor):
    assert executor.call("create_quote", {"body": QUOTE, "confirm": True})["ok"]


def test_relogin_after_session_expiry(executor, portal_app):
    assert executor.call("get_me")["ok"]
    portal_app.state.expire_sessions()
    assert executor.call("get_me")["ok"]


def test_missing_and_unknown_arguments(executor):
    with pytest.raises(OperationError, match="missing"):
        executor.call("get_policy", {})
    with pytest.raises(OperationError, match="unknown"):
        executor.call("get_policy", {"policy_id": "POL-100234", "nope": 1})


def test_audit_log_records_every_call(executor, tmp_path):
    executor.call("get_me")
    executor.call("create_quote", {"body": QUOTE})
    lines = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert [(entry["operation"], entry["dry_run"]) for entry in lines] == [("get_me", False), ("create_quote", True)]


def test_discriminator_is_merged_into_body(portal_catalog):
    from portolan.catalog import Operation
    from portolan.runtime import Executor

    op = Operation(
        name="invoice_create", method="POST", path_template="/rpc", description="",
        discriminator={"method": "invoice.create"},
        input_schema={"type": "object", "properties": {"body": {}}, "required": []},
    )
    request = Executor(portal_catalog, client=None, credentials={}).build_request(op, {"body": {"params": {"a": 1}}})
    assert request["json"] == {"method": "invoice.create", "params": {"a": 1}}
    assert op.key == "POST /rpc [method=invoice.create]"
