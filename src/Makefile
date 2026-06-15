all: format lint typecheck test

format:
	uv run ruff format .

lint:
	uv run ruff check --fix .

typecheck:
	uv run mypy .

test:
	uv run pytest -v

test-update-golden:
	uv run pytest . -v --update-goldens
