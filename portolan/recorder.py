"""Record a real browser session to a HAR file with Playwright.

You drive; Portolan watches. Click through the workflows you care about,
then close the browser window and the HAR is saved with full response bodies.

Requires the optional extra:  pip install -e ".[record]" && playwright install chromium
"""

from __future__ import annotations

from pathlib import Path


def record(url: str, out: str | Path, storage_state: str | None = None, url_filter: str | None = None) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise SystemExit(
            'Recording needs Playwright: pip install -e ".[record]" && playwright install chromium'
        ) from exc

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            record_har_path=str(out),
            record_har_content="embed",
            record_har_url_filter=url_filter,
            storage_state=storage_state,
        )
        page = context.new_page()
        page.goto(url)
        print(f"Recording {url}. Use the app, then close the browser window to save.")
        try:
            page.wait_for_event("close", timeout=0)
        finally:
            context.close()  # flushes the HAR
            browser.close()
    print(f"Saved {out}")
    return out
