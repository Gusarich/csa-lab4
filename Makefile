.PHONY: lint-fix lint

MARKDOWNLINT_VERSION ?= 0.48.0
NPM_CONFIG_CACHE ?= /tmp/csa-lab4-npm-cache
MARKDOWNLINT = npm_config_cache="$(NPM_CONFIG_CACHE)" npx --yes markdownlint-cli@$(MARKDOWNLINT_VERSION)

lint-fix:
	$(MARKDOWNLINT) . --config .markdownlint.yaml --ignore "TASK/**" --fix

lint:
	$(MARKDOWNLINT) . --config .markdownlint.yaml --ignore "TASK/**"
