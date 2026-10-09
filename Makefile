.PHONY: install test eval check baseline demo lint portal erp

# Use the project venv when there is one (local dev), plain python otherwise (CI).
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python)

install:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest -q

eval:
	$(PY) -m portolan.cli eval

# Everything a change must pass: lint, tests, and no scoreboard metric below the baseline.
check: lint test
	$(PY) -m portolan.cli eval --check-baseline evals/baseline.json

# Accept the current scores as the new baseline (commit evals/baseline.json).
baseline:
	$(PY) -m portolan.cli eval --write-baseline evals/baseline.json

demo:
	$(PY) -m portolan.cli demo

lint:
	$(PY) -m ruff check portolan tests

# Run fixtures on real ports, e.g. to try `portolan record` against them in a browser.
portal:
	$(PY) -m uvicorn portolan.testing.carrier_portal:app --port 8765

erp:
	$(PY) -m uvicorn portolan.testing.legacy_erp:app --port 8766
