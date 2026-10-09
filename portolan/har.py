"""Read and write HAR 1.2 files, and filter them down to API traffic.

A HAR is what browsers (and Playwright) export when you record a session. It is
Portolan's raw input: every request the app's front end made, with bodies.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

STATIC_EXT = re.compile(r"\.(js|mjs|css|map|png|jpe?g|gif|svg|ico|webp|woff2?|ttf|eot|html?)$", re.I)

# Paths that are almost always instrumentation rather than product behaviour.
NOISE_PATH = re.compile(
    r"/(telemetry|analytics|track(ing)?|collect|beacon|metrics|log(s|ging)?|events?|rum|sentry|_next/data)(/|$)",
    re.I,
)


@dataclass
class Exchange:
    """One observed request/response pair."""

    method: str
    url: str
    path: str
    query: dict[str, list[str]]
    request_headers: dict[str, str]
    request_json: Any
    status: int
    response_headers: dict[str, str]
    response_mime: str
    response_json: Any
    started: str = ""
    raw_request_text: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def origin(self) -> str:
        parts = urlsplit(self.url)
        return f"{parts.scheme}://{parts.netloc}"


def _headers(items: list[dict[str, str]]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in items or []}


def _maybe_json(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def load_exchanges(path: str | Path) -> list[Exchange]:
    """Parse every entry in a HAR file, in recorded order."""
    data = json.loads(Path(path).read_text())
    out: list[Exchange] = []
    for entry in data["log"]["entries"]:
        req, resp = entry["request"], entry["response"]
        url = req["url"]
        parts = urlsplit(url)
        post = req.get("postData") or {}
        content = resp.get("content") or {}
        out.append(
            Exchange(
                method=req["method"].upper(),
                url=url,
                path=parts.path or "/",
                query={k: v for k, v in parse_qs(parts.query, keep_blank_values=True).items()},
                request_headers=_headers(req.get("headers", [])),
                request_json=_maybe_json(post.get("text")),
                raw_request_text=post.get("text"),
                status=int(resp.get("status", 0)),
                response_headers=_headers(resp.get("headers", [])),
                response_mime=(content.get("mimeType") or "").split(";")[0].strip().lower(),
                response_json=_maybe_json(content.get("text")),
                started=entry.get("startedDateTime", ""),
            )
        )
    return out


def is_api_call(ex: Exchange) -> tuple[bool, str]:
    """Decide whether an exchange is product API traffic. Returns (keep, reason)."""
    if STATIC_EXT.search(ex.path):
        return False, "static asset"
    if NOISE_PATH.search(ex.path):
        return False, "instrumentation"
    if ex.status >= 400 or ex.status == 0:
        return False, f"status {ex.status}"
    is_json = ex.response_mime.endswith("json") or ex.request_json is not None
    if not is_json:
        return False, f"non-JSON response ({ex.response_mime or 'empty'})"
    return True, "api"


def filter_api(exchanges: list[Exchange]) -> tuple[list[Exchange], list[tuple[Exchange, str]]]:
    kept, dropped = [], []
    for ex in exchanges:
        keep, reason = is_api_call(ex)
        (kept if keep else dropped).append(ex if keep else (ex, reason))
    return kept, dropped


class HarWriter:
    """Builds a HAR from httpx traffic. Used to record scripted sessions without a browser."""

    def __init__(self, creator: str = "portolan") -> None:
        self.entries: list[dict[str, Any]] = []
        self.creator = creator

    def add(self, response: httpx.Response, elapsed_ms: float = 0.0) -> None:
        request = response.request
        body = request.content.decode() if request.content else None
        entry: dict[str, Any] = {
            "startedDateTime": datetime.now(UTC).isoformat(),
            "time": elapsed_ms,
            "request": {
                "method": request.method,
                "url": str(request.url),
                "httpVersion": "HTTP/1.1",
                "headers": [{"name": k, "value": v} for k, v in request.headers.items()],
                "queryString": [{"name": k, "value": v} for k, v in request.url.params.multi_items()],
                "cookies": [],
                "headersSize": -1,
                "bodySize": len(request.content or b""),
            },
            "response": {
                "status": response.status_code,
                "statusText": response.reason_phrase,
                "httpVersion": "HTTP/1.1",
                "headers": [{"name": k, "value": v} for k, v in response.headers.items()],
                "cookies": [],
                "content": {
                    "size": len(response.content),
                    "mimeType": response.headers.get("content-type", ""),
                    "text": response.text,
                },
                "redirectURL": "",
                "headersSize": -1,
                "bodySize": len(response.content),
            },
            "cache": {},
            "timings": {"send": 0, "wait": elapsed_ms, "receive": 0},
        }
        if body is not None:
            entry["request"]["postData"] = {
                "mimeType": request.headers.get("content-type", ""),
                "text": body,
            }
        self.entries.append(entry)

    def to_dict(self) -> dict[str, Any]:
        return {
            "log": {
                "version": "1.2",
                "creator": {"name": self.creator, "version": "0.1"},
                "pages": [],
                "entries": self.entries,
            }
        }

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path


class RecordingClient:
    """Wraps an httpx.Client so every call lands in a HarWriter."""

    def __init__(self, client: httpx.Client, writer: HarWriter | None = None) -> None:
        self.client = client
        self.writer = writer or HarWriter()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        response = self.client.request(method, url, **kwargs)
        self.writer.add(response, response.elapsed.total_seconds() * 1000 if _has_elapsed(response) else 0.0)
        return response

    def get(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("POST", url, **kw)


def _has_elapsed(response: httpx.Response) -> bool:
    try:
        _ = response.elapsed
        return True
    except RuntimeError:
        return False
