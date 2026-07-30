.PHONY: protocol test lint typecheck check

protocol:
	python3 scripts/generate_protocol_ts.py

test:
	uv run pytest -q

lint:
	uv run ruff check .

typecheck:
	uv run mypy backend scripts

check: protocol lint typecheck test
