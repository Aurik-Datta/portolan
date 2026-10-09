.PHONY: install test eval baseline demo lint portal erp

install:
	pip install -e ".[dev]"

test:
	python -m pytest -q

eval:
	python -m portolan.cli eval

# Accept the current scores as the new baseline (commit evals/baseline.json).
baseline:
	python -m portolan.cli eval --write-baseline evals/baseline.json

demo:
	python -m portolan.cli demo

lint:
	ruff check portolan tests

# Run fixtures on real ports, e.g. to try `portolan record` against them in a browser.
portal:
	python -m uvicorn portolan.testing.carrier_portal:app --port 8765

erp:
	python -m uvicorn portolan.testing.legacy_erp:app --port 8766
