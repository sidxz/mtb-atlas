.PHONY: install build build-force check refresh diff summary api web test lint fmt typecheck

install:
	uv venv --python 3.12
	uv pip install -e '.[dev]'

build:
	uv run atlas build

build-force:
	uv run atlas build --force

# Has anything released since the store was built? Six small requests.
check:
	uv run atlas check

# Re-download one source and rebuild only what it feeds: make refresh SOURCE=chembl
refresh:
	uv run atlas refresh $(SOURCE)

# What the last refresh did to the numbers.
diff:
	uv run atlas diff

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
