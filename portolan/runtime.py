"""Execute catalog operations against the live app.

Safety model (the part customers actually pay for):
- reads run immediately
- writes return a dry-run preview unless `confirm=True`
- every call, dry run or real, is appended to an audit log
- auth is handled here, once, so agents never see credentials
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from portolan.catalog import Catalog, Operation


class OperationError(Exception):
    pass


def _dig(value: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def credentials_from_env(catalog: Catalog, prefix: str = "PORTOLAN_") -> dict[str, str]:
    """PORTOLAN_USERNAME, PORTOLAN_PASSWORD, ... one per credential field the login form takes."""
    if not catalog.auth:
        return {}
    names = {f: prefix + f.upper() for f in catalog.auth.credential_fields}
    return {f: os.environ[var] for f, var in names.items() if var in os.environ}


class Executor:
    def __init__(
        self,
        catalog: Catalog,
        client: httpx.Client | None = None,
        credentials: dict[str, str] | None = None,
        audit_log: str | Path | None = None,
    ) -> None:
        self.catalog = catalog
        self.client = client or httpx.Client(base_url=catalog.base_url, timeout=30)
        self.credentials = credentials if credentials is not None else credentials_from_env(catalog)
        self.audit_log = Path(audit_log) if audit_log else None
        self._auth_header: dict[str, str] = {}

    # ------------------------------------------------------------ auth

    def login(self) -> None:
        auth = self.catalog.auth
        if auth is None:
            return
        missing = [f for f in auth.credential_fields if f not in self.credentials]
        if missing:
            raise OperationError(
                f"login needs {missing}; set " + ", ".join(f"PORTOLAN_{f.upper()}" for f in missing)
            )
        response = self.client.request(auth.login_method, auth.login_path, json=self.credentials)
        if response.status_code >= 400:
            raise OperationError(f"login failed with HTTP {response.status_code}")
        token = _dig(response.json(), auth.token_json_path)
        value = f"{auth.scheme} {token}".strip()
        self._auth_header = {auth.header: value}

    # ------------------------------------------------------------ calls

    def build_request(self, op: Operation, args: dict[str, Any]) -> dict[str, Any]:
        missing = [r for r in op.input_schema.get("required", []) if r not in args]
        if missing:
            raise OperationError(f"{op.name}: missing required argument(s) {missing}")
        unknown = set(args) - set(op.input_schema.get("properties", {})) - {"confirm"}
        if unknown:
            raise OperationError(f"{op.name}: unknown argument(s) {sorted(unknown)}")
        path = op.path_template
        for p in op.path_params:
            path = path.replace("{" + p + "}", str(args[p]))
        params = {q: args[q] for q in op.query_params if q in args}
        request: dict[str, Any] = {"method": op.method, "url": path}
        if params:
            request["params"] = params
        if "body" in args or op.discriminator:
            body = args.get("body", {})
            request["json"] = {**op.discriminator, **body} if isinstance(body, dict) else body
        return request

    def call(self, name: str, args: dict[str, Any] | None = None, confirm: bool = False) -> dict[str, Any]:
        args = dict(args or {})
        confirm = bool(args.pop("confirm", confirm))
        op = self.catalog.get(name)
        request = self.build_request(op, args)

        if op.side_effect and not confirm:
            result = {
                "dry_run": True,
                "operation": op.name,
                "risk": op.risk,
                "would_send": request,
                "message": "This operation changes data. Re-run with confirm=true to execute.",
            }
            self._audit(op, args, result)
            return result

        if self.catalog.auth and not self._auth_header:
            self.login()
        response = self._send(request)
        if response.status_code == 401 and self.catalog.auth:
            # Session expired. A 401 means the request was rejected before running, so retrying is safe.
            self.login()
            response = self._send(request)

        try:
            data: Any = response.json()
        except ValueError:
            data = response.text
        result = {"status": response.status_code, "ok": response.is_success, "data": data}
        self._audit(op, args, result)
        return result

    def _send(self, request: dict[str, Any]) -> httpx.Response:
        return self.client.request(**request, headers=self._auth_header)

    def _audit(self, op: Operation, args: dict[str, Any], result: dict[str, Any]) -> None:
        if not self.audit_log:
            return
        self.audit_log.parent.mkdir(parents=True, exist_ok=True)
        line = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "operation": op.name,
            "risk": op.risk,
            "args": args,
            "dry_run": result.get("dry_run", False),
            "status": result.get("status"),
        }
        with self.audit_log.open("a") as f:
            f.write(json.dumps(line) + "\n")
