"""The scoreboard. Every change to the compiler should move these numbers, not vibes.

An eval spec (evals/*.json) names a fixture app, a scripted session that records
traffic against it, the operations a correct compiler should find, and scenarios
that execute the compiled operations against a *fresh* copy of the app.

Metrics:
    recall      expected operations that were discovered
    precision   compiled operations that were expected (noise lowers it)
    risk        discovered operations with the correct read/write/irreversible label
    auth        login flow detected and replayed
    scenarios   scenario steps that behaved as expected end to end
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from portolan.catalog import Catalog, Operation
from portolan.compiler import compile_har
from portolan.runtime import Executor, OperationError

REF = re.compile(r"^\{\{steps\.(\d+)\.(.+)\}\}$")
METRICS = ("recall", "precision", "risk", "auth", "scenarios", "score")


def _load(target: str) -> Callable[..., Any]:
    module, attr = target.split(":")
    return getattr(importlib.import_module(module), attr)


def norm(key: str) -> str:
    return re.sub(r"\{[^}]+\}", "{*}", key)


def _dig(value: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


@dataclass
class EvalResult:
    app: str
    recall: float
    precision: float
    risk: float
    auth: float
    scenarios: float
    missing: list[str] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)
    wrong_risk: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return round((self.recall + self.precision + self.risk + self.auth + self.scenarios) / 5, 3)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "score": self.score}


def _resolve(value: Any, history: list[dict[str, Any]]) -> Any:
    if isinstance(value, str):
        m = REF.match(value)
        if m:
            return _dig(history[int(m.group(1))], m.group(2))
        return value
    if isinstance(value, list):
        return [_resolve(v, history) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, history) for k, v in value.items()}
    return value


def _find(catalog: Catalog, key: str) -> Operation | None:
    for op in catalog.operations:
        if norm(op.key) == norm(key):
            return op
    return None


def run_scenarios(spec: dict[str, Any], catalog: Catalog, workdir: Path) -> tuple[int, int, list[str]]:
    from fastapi.testclient import TestClient

    passed = total = 0
    failures: list[str] = []
    for scenario in spec.get("scenarios", []):
        app = _load(spec["fixture"])()  # fresh state per scenario
        client = TestClient(app, base_url=spec["base_url"])
        executor = Executor(catalog, client=client, credentials=spec.get("credentials", {}),
                            audit_log=workdir / f"{spec['app']}.audit.jsonl")
        history: list[dict[str, Any]] = []
        for i, step in enumerate(scenario["steps"]):
            label = f"{scenario['name']} / step {i}"
            if step.get("action") == "expire_sessions":
                app.state.expire_sessions()  # fixture hook: invalidate every issued token
                history.append({})
                continue
            total += 1
            try:
                op = _find(catalog, step["op"])
                if op is None:
                    raise OperationError(f"operation {step['op']} not in catalog")
                args: dict[str, Any] = {}
                for name, value in zip(op.path_params, _resolve(step.get("path", []), history)):
                    args[name] = value
                args.update(_resolve(step.get("query", {}), history))
                if "body" in step:
                    args["body"] = _resolve(step["body"], history)
                result = executor.call(op.name, args, confirm=step.get("confirm", False))
                history.append(result)
                if step.get("expect_dry_run"):
                    assert result.get("dry_run"), "expected a dry-run preview, got a real call"
                else:
                    assert not result.get("dry_run"), "got a dry run; step needs confirm"
                    expected_status = step.get("expect_status", 200)
                    assert result["status"] == expected_status, f"HTTP {result['status']}: {result['data']}"
                    if "expect_path" in step:
                        _dig(result["data"], step["expect_path"])
                passed += 1
            except (AssertionError, OperationError, KeyError, IndexError, TypeError) as exc:
                failures.append(f"{label}: {exc}")
                history.append({})
    return passed, total, failures


def run_eval(spec_path: str | Path, workdir: str | Path = "evals/results") -> EvalResult:
    spec_path = Path(spec_path)
    spec = json.loads(spec_path.read_text())
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    har = workdir / f"{spec['app']}.har"
    _load(spec["session"])(har)
    catalog = compile_har(har, app=spec["app"], base_url=spec["base_url"])
    catalog.save(workdir / f"{spec['app']}.catalog.json")

    expected = {norm(e["key"]): e for e in spec["expect"]["operations"]}
    found = {norm(op.key): op for op in catalog.operations}

    missing = sorted(set(expected) - set(found))
    unexpected = sorted(set(found) - set(expected))
    hits = set(expected) & set(found)
    wrong_risk = sorted(k for k in hits if found[k].risk != expected[k]["risk"])
    for path in spec["expect"].get("must_not_include", []):
        for op in catalog.operations:
            if op.path_template == path and op.key not in unexpected:
                unexpected.append(op.key)

    auth_ok = 1.0 if bool(catalog.auth) == spec["expect"].get("auth", False) else 0.0
    passed, total, failures = run_scenarios(spec, catalog, workdir)

    result = EvalResult(
        app=spec["app"],
        recall=round(len(hits) / len(expected), 3) if expected else 1.0,
        precision=round(len(hits) / len(found), 3) if found else 0.0,
        risk=round((len(hits) - len(wrong_risk)) / len(hits), 3) if hits else 0.0,
        auth=auth_ok,
        scenarios=round(passed / total, 3) if total else 1.0,
        missing=missing,
        unexpected=sorted(unexpected),
        wrong_risk=wrong_risk,
        failures=failures,
    )
    (workdir / f"{spec['app']}.result.json").write_text(json.dumps(result.to_dict(), indent=2) + "\n")
    return result


def format_table(results: list[EvalResult]) -> str:
    cols = ["app", "recall", "precision", "risk", "auth", "scenarios", "score"]
    rows = [[r.app, *(f"{getattr(r, c):.2f}" for c in cols[1:])] for r in results]
    widths = [max(len(c), *(len(row[i]) for row in rows)) for i, c in enumerate(cols)]
    line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths))  # noqa: E731
    out = [line(cols), line(["-" * w for w in widths]), *(line(r) for r in rows)]
    for r in results:
        for label, items in [("missing", r.missing), ("unexpected", r.unexpected),
                             ("wrong risk", r.wrong_risk), ("failed", r.failures)]:
            for item in items:
                out.append(f"  [{r.app}] {label}: {item}")
    return "\n".join(out)


def regressions(results: list[EvalResult], baseline: dict[str, dict[str, float]]) -> list[str]:
    """Metrics that dropped below the accepted baseline. Apps not in the baseline yet are skipped."""
    out = []
    for r in results:
        accepted = baseline.get(r.app)
        if accepted is None:
            continue
        current = r.to_dict()
        for metric in METRICS:
            if metric in accepted and current[metric] < accepted[metric] - 1e-9:
                out.append(f"{r.app}: {metric} {accepted[metric]:.2f} -> {current[metric]:.2f}")
    return out
