.PHONY: protocol test lint typecheck check-ownership audit-chain-export seed purge check ci

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

audit-chain-export:
	uv run python -m backend.app.audit.export_cli

seed:
	uv run python -m backend.app.cli.seed

purge:
	uv run python -m backend.app.cli.purge

check: protocol lint typecheck test check-ownership

ci: check
