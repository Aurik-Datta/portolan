"""The operation catalog: Portolan's compiled output and the contract agents call.

A catalog is plain JSON so it can be diffed in code review, versioned in git,
and regenerated when the app changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

Risk = Literal["read", "write", "irreversible"]


class AuthSpec(BaseModel):
    """How to obtain credentials before calling operations."""

    kind: Literal["bearer_from_login"] = "bearer_from_login"
    login_method: str
    login_path: str
    credential_fields: list[str]
    token_json_path: str = Field(description="Dotted path to the token in the login response")
    header: str = "authorization"
    scheme: str = "Bearer"


class Operation(BaseModel):
    name: str
    method: str
    path_template: str
    description: str
    path_params: list[str] = []
    query_params: list[str] = []
    has_body: bool = False
    discriminator: dict[str, Any] = Field(
        default_factory=dict,
        description="Fixed body fields that select this operation on a shared endpoint, "
        "e.g. {'method': 'invoice.create'} for RPC-style APIs. Merged into the body at call time.",
    )
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] = {}
    risk: Risk = "read"
    observed: int = Field(1, description="How many times this operation appeared in recordings")
    example_request: dict[str, Any] = {}

    @property
    def side_effect(self) -> bool:
        return self.risk != "read"

    @property
    def key(self) -> str:
        base = f"{self.method} {self.path_template}"
        if self.discriminator:
            base += " [" + ",".join(f"{k}={v}" for k, v in sorted(self.discriminator.items())) + "]"
        return base


class Catalog(BaseModel):
    portolan_version: str = "0.1"
    app: str
    base_url: str
    generated_at: str
    sources: list[str] = []
    auth: AuthSpec | None = None
    operations: list[Operation] = []
    dropped: dict[str, int] = Field(default_factory=dict, description="Counts of filtered-out traffic by reason")

    def get(self, name: str) -> Operation:
        for op in self.operations:
            if op.name == name:
                return op
        raise KeyError(f"no operation named {name!r}; have: {', '.join(o.name for o in self.operations)}")

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(mode="json"), indent=2) + "\n")
        return path

    @classmethod
    def load(cls, path: str | Path) -> Catalog:
        return cls.model_validate_json(Path(path).read_text())
