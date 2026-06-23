# sqlseed Makefile
# Common development commands.

.PHONY: help install dev-install lint format type-check test test-core test-integration docs docs-serve docs-build clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies
	pip install -e .

dev-install: ## Install development dependencies
	pip install -e ".[dev,all]"
	pip install -e "./plugins/sqlseed-ai"
	pip install -e "./plugins/mcp-server-sqlseed"

lint: ## Run ruff linter
	ruff check src/ tests/ plugins/ examples/

format: ## Run ruff formatter
	ruff format src/ tests/ plugins/ examples/

type-check: ## Run mypy type checker
	mypy src/sqlseed/ plugins/

test: ## Run all tests
	pytest

test-core: ## Run core tests only
	pytest tests/test_core/ tests/test_config/ tests/test_database/ tests/test_generators/ tests/test_plugins/

test-integration: ## Run integration tests (requires Docker)
	pytest tests/integration/

docs: docs-serve ## Serve docs locally (alias)

docs-serve: ## Serve mkdocs locally
	mkdocs serve

docs-build: ## Build docs site
	mkdocs build --strict

clean: ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info src/*.egg-info plugins/*/build/ plugins/*/dist/ plugins/*/*.egg-info
	rm -rf .pytest_cache/ .mypy_cache/ .ruff_cache/
	rm -rf site/
	find . -type d -name __pycache__ -exec rm -rf {} +
