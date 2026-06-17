.PHONY: all check format format-check lint lint-fix typecheck test test-update-golden markdown-lint markdown-lint-fix fix

PYTHON_DIR ?= src
UV ?= uv
MARKDOWNLINT_VERSION ?= 0.48.0
NPM_CONFIG_CACHE ?= /tmp/csa-lab4-npm-cache
MARKDOWNLINT = npm_config_cache="$(NPM_CONFIG_CACHE)" npx --yes markdownlint-cli@$(MARKDOWNLINT_VERSION)

all: check

check: format-check lint typecheck test markdown-lint

format:
	cd $(PYTHON_DIR) && $(UV) run ruff format .

format-check:
	cd $(PYTHON_DIR) && $(UV) run ruff format --check .

lint:
	cd $(PYTHON_DIR) && $(UV) run ruff check .

lint-fix:
	cd $(PYTHON_DIR) && $(UV) run ruff check --fix .

typecheck:
	cd $(PYTHON_DIR) && $(UV) run mypy .

test:
	cd $(PYTHON_DIR) && $(UV) run pytest -v

test-update-golden:
	cd $(PYTHON_DIR) && $(UV) run pytest . -v --update-goldens

markdown-lint:
	$(MARKDOWNLINT) . --config .markdownlint.yaml --ignore "TASK/**"

markdown-lint-fix:
	$(MARKDOWNLINT) . --config .markdownlint.yaml --ignore "TASK/**" --fix

fix: format lint-fix markdown-lint-fix
