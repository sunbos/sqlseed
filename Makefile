# sqlseed Makefile
# Common development commands.

.PHONY: help install dev-install lint format type-check test test-core test-integration lint-imports mutmut mutmut-report mutmut-clean docs docs-serve docs-build clean

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

lint-imports: ## Enforce architectural layer contracts (CLAUDE.md "Never" rules)
	lint-imports

# Mutation testing — detects self-proving mock-based tests by injecting faults
# into production code and checking whether the test suite catches them.
# Surviving mutants indicate tests that pass because the mock returned what
# the author expected, not because the code actually computes correctly.
# NOTE: mutmut 3.x does not support Windows natively. On Windows use mutmut 2.x
# (`pip install "mutmut<3"`) and set PYTHONUTF8=1.
mutmut: ## Run mutation tests on high-risk core modules (default: unique_adjuster)
	PYTHONUTF8=1 python -m mutmut run

mutmut-report: ## Show mutation test results and surviving mutant IDs
	PYTHONUTF8=1 python -m mutmut results
	@echo ""
	@echo "Inspect a specific survivor with:"
	@echo "  python -m mutmut show <mutant_id>"

mutmut-clean: ## Remove mutmut cache and survivor reports
	rm -f .mutmut-cache
	rm -f mutmut_*.log mutmut_results_*.txt

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
	rm -f .mutmut-cache
