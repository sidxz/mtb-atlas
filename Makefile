.PHONY: install build build-force summary api web test lint fmt typecheck

install:
	uv venv --python 3.12
	uv pip install -e '.[dev]'

build:
	uv run atlas build

build-force:
	uv run atlas build --force

summary:
	uv run atlas summary

api:
	uv run uvicorn atlas.api:app --reload --port 8099

web:
	cd web && npm run dev

typecheck:
	cd web && npm run typecheck

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
