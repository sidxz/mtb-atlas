.PHONY: install build build-force summary test lint fmt

install:
	uv venv --python 3.12
	uv pip install -e '.[dev]'

build:
	uv run atlas build

build-force:
	uv run atlas build --force

summary:
	uv run atlas summary

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
