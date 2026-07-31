.PHONY: protocol test lint typecheck check-ownership check ci

protocol:
	python3 scripts/generate_protocol_ts.py

test:
	uv run pytest -q

lint:
	uv run ruff check .

typecheck:
	uv run mypy backend scripts

check-ownership:
	uv run python scripts/check_ownership.py

check: protocol lint typecheck test check-ownership

ci: check
