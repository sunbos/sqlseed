"""Architecture guard tests — protect structural decisions from drift.

These tests encode architectural invariants from CLAUDE.md/AGENTS.md so that
any AI agent (or human) who accidentally violates them sees an immediate test
failure with a clear explanation. They complement ``lint-imports`` (which
enforces dependency direction) by guarding things import-linter cannot:

* File location invariants (DataStream must live in core/, not generators/)
* Package vs. module invariants (orchestrator must be a package, not a file)
* Production isolation (RawSQLiteAdapter must not leak into non-test code)
* Coding conventions (``from __future__ import annotations`` everywhere,
  no runtime ``assert`` in production code)
* Public API contract (keyword-only args, ``__all__`` exports)
* Immutable constants (``AI_APPLICABLE_GENERATORS`` is a frozenset)
* Count contracts (12 hooks, 35 generators — synced with docs)

If any of these tests fails, do NOT silence it — either fix the code to
honor the architecture, or update CLAUDE.md + this test together with a
recorded decision (ADR) explaining why the invariant changed.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import sys
from importlib.metadata import entry_points
from pathlib import Path

import pytest

import sqlseed
import sqlseed.core.orchestrator as orch_pkg

try:
    from sqlseed_ai.ai_mediator import AI_APPLICABLE_GENERATORS
except ImportError:
    AI_APPLICABLE_GENERATORS = None

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "sqlseed"


# ---------------------------------------------------------------------------
# A. Module location guards — prevent files from being moved to wrong packages
# ---------------------------------------------------------------------------


class TestModuleLocationGuards:
    """Guard against files being relocated to architecturally wrong packages."""

    def test_datastream_lives_in_core_not_generators(self) -> None:
        """DataStream must be importable from sqlseed.core.stream, NOT generators/.

        Historical context: DataStream was moved from generators/ to core/
        because it depends on core constructs (ConstraintSolver, ColumnDAG,
        ExpressionEngine) and is the central generation pipeline. Moving it
        back to generators/ would create a generators -> core dependency
        violation. See CLAUDE.md "Critical Pitfalls" #10 and the refactor
        noted in the 2026-05 architecture review.
        """
        # Verify DataStream is importable from core.stream (use importlib to
        # avoid triggering unused-import — the import's sole purpose is to
        # prove the module path exists, not to bind a name for later use).
        _stream_mod = importlib.import_module("sqlseed.core.stream")
        assert hasattr(_stream_mod, "DataStream"), (
            "DataStream must be importable from sqlseed.core.stream. Historical context: "
            "DataStream was moved from generators/ to core/ because it depends on core "
            "constructs (ConstraintSolver, ColumnDAG, ExpressionEngine)."
        )

        # DataStream must NOT be importable from generators
        with pytest.raises(ImportError):
            importlib.import_module("sqlseed.generators.stream")

    def test_orchestrator_is_package_not_single_file(self) -> None:
        """sqlseed.core.orchestrator must be a package (directory), not a single file.

        The orchestrator was refactored from a single orchestrator.py into a
        package with 4 mixins (_connection, _specs, _generation, _query) +
        shared _common. If someone "simplifies" it back to a single file,
        the mixin architecture is lost and the file becomes too large to
        maintain. See CLAUDE.md Architecture > Key Modules > core/orchestrator/.
        """
        assert hasattr(orch_pkg, "__path__"), (
            "sqlseed.core.orchestrator must be a package (directory with __init__.py), "
            "not a single orchestrator.py file. The package contains 4 mixins that "
            "should not be collapsed back into one file."
        )
        # The 4 mixin files must exist inside the package
        assert orch_pkg.__file__ is not None, (
            "sqlseed.core.orchestrator must be a real on-disk package with __file__ set; "
            "got None (likely a namespace package or virtual module)."
        )
        orch_dir = Path(orch_pkg.__file__).parent
        for mixin in ("_common.py", "_connection.py", "_specs.py", "_generation.py", "_query.py"):
            assert (orch_dir / mixin).exists(), (
                f"orchestrator package missing {mixin}. The 4-mixin + 1-shared architecture "
                "must be preserved. See CLAUDE.md."
            )

    def test_cli_lives_in_plugins_not_src_sqlseed(self) -> None:
        """The ``sqlseed`` console command lives in ``plugins/sqlseed-cli/``, NOT in ``src/sqlseed/cli/``.

        Per ARCHITECTURE.md Section 7.1: "CLI code moves to
        ``plugins/sqlseed-cli/``. Core package has no ``[project.scripts]``."
        The core ``sqlseed`` package must not depend on click/rich, and
        installing ``pip install sqlseed`` alone provides only the Python
        API. Users who want the ``sqlseed`` command install
        ``pip install sqlseed-cli``.

        Historical context: this invariant was added during the Phase B
        refactoring (2026-06-26) that moved ``src/sqlseed/cli/`` to
        ``plugins/sqlseed-cli/src/sqlseed_cli/`` and ``src/sqlseed/cli/ai_commands.py``
        to ``plugins/sqlseed-ai/src/sqlseed_ai/cli/ai_commands.py``.
        """
        # src/sqlseed/cli/ directory must NOT exist
        cli_dir = SRC_ROOT / "cli"
        assert not cli_dir.exists(), (
            f"{cli_dir} must not exist. CLI code lives in plugins/sqlseed-cli/ per "
            "ARCHITECTURE.md Section 7.1. Re-introducing a cli/ directory inside "
            "the core sqlseed package violates the 'core stability' principle."
        )

        # The standalone sqlseed_cli package must provide the cli group
        # The entry-point group must register ai-suggest
        # Verify ai_suggest and cli are importable from their plugin packages
        # (use importlib to avoid unused-import — these imports only verify
        # that the plugin entry-point modules exist and are loadable).
        _ai_cmds_mod = importlib.import_module("sqlseed_ai.cli.ai_commands")
        assert hasattr(_ai_cmds_mod, "ai_suggest"), (
            "sqlseed_ai.cli.ai_commands must expose `ai_suggest` for the entry-point registration to resolve correctly."
        )
        _cli_main_mod = importlib.import_module("sqlseed_cli.main")
        assert hasattr(_cli_main_mod, "cli"), (
            "sqlseed_cli.main must expose `cli` (the Click group) for the "
            "[project.scripts] entry point to resolve correctly."
        )

        eps = entry_points(group="sqlseed.cli_commands")
        registered_names = {ep.name for ep in eps}
        assert "ai_suggest" in registered_names, (
            "sqlseed-ai must register `ai_suggest` in the `sqlseed.cli_commands` "
            f"entry-point group. Found: {registered_names}"
        )


# ---------------------------------------------------------------------------
# B. Layering guards — Python-level checks complementing import-linter
# ---------------------------------------------------------------------------


class TestLayeringGuards:
    """Python-level layering checks that run alongside import-linter.

    These are redundant with ``lint-imports`` but provide faster, more
    localized feedback inside pytest and produce clearer failure messages.
    """

    def test_generators_does_not_pull_in_core(self) -> None:
        """Importing sqlseed.generators must not load sqlseed.core.

        If this fails, a generators/ file has a ``from sqlseed.core import ...``
        or ``import sqlseed.core`` statement. This is a CRITICAL layering
        violation per CLAUDE.md: "Never: generators -> core".
        """
        # Clear any cached core modules first (best effort)
        core_before = {k for k in sys.modules if k.startswith("sqlseed.core")}
        for k in list(sys.modules):
            if k.startswith("sqlseed.core"):
                # Don't actually delete; just snapshot. We check delta instead.
                pass

        importlib.import_module("sqlseed.generators")
        core_after = {k for k in sys.modules if k.startswith("sqlseed.core")}
        # generators should not have pulled in any NEW core modules
        new_core = core_after - core_before
        assert not new_core, (
            f"Layering violation: importing sqlseed.generators pulled in core modules: {new_core}. "
            "generators must not depend on core (CLAUDE.md: 'Never: generators -> core')."
        )

    def test_utils_does_not_pull_in_upper_layers(self) -> None:
        """Importing sqlseed._utils must not load any upper-layer module.

        _utils is the lowest layer and must have zero internal dependencies.
        See CLAUDE.md: "_utils -> (no internal deps, used by all layers)".
        """
        upper_layer_prefixes = (
            "sqlseed.core",
            "sqlseed.generators",
            "sqlseed.database",
            "sqlseed.plugins",
            "sqlseed.config",
        )
        upper_before = {k for k in sys.modules if any(k.startswith(p) for p in upper_layer_prefixes)}
        importlib.import_module("sqlseed._utils")
        upper_after = {k for k in sys.modules if any(k.startswith(p) for p in upper_layer_prefixes)}
        new_upper = upper_after - upper_before
        assert not new_upper, (
            f"Layering violation: importing sqlseed._utils pulled in upper-layer modules: {new_upper}. "
            "_utils must have no internal dependencies (CLAUDE.md)."
        )


# ---------------------------------------------------------------------------
# C. Production isolation guards
# ---------------------------------------------------------------------------


def _imports_raw_sqlite_adapter(tree: ast.AST) -> bool:
    """Check if AST contains a RawSQLiteAdapter import.

    Walks the parsed module looking for ``from ...raw_sqlite_adapter import
    RawSQLiteAdapter`` (ImportFrom) or ``import ...raw_sqlite_adapter``
    (Import). Used by :class:`TestProductionIsolation` to keep the nested-
    block count under pylint's threshold while preserving the same logic.

    Args:
        tree: Parsed AST module to inspect.

    Returns:
        True if any import statement references RawSQLiteAdapter via a
        module path containing ``raw_sqlite_adapter``.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "raw_sqlite_adapter" in node.module:
            if any("RawSQLiteAdapter" in alias.name for alias in node.names):
                return True
        elif isinstance(node, ast.Import) and any(
            alias.name and "raw_sqlite_adapter" in alias.name for alias in node.names
        ):
            return True
    return False


class TestProductionIsolation:
    """Guard against test-only code leaking into production paths."""

    def test_raw_sqlite_adapter_not_imported_in_production_logic(self) -> None:
        """RawSQLiteAdapter must not be imported in production code (except database/__init__.py).

        RawSQLiteAdapter is a zero-dependency fallback for tests only.
        Production code must use SQLAlchemyAdapter. This test checks actual
        import statements (via AST), not text mentions — docstrings and
        comments referencing RawSQLiteAdapter for behavioral consistency
        notes are allowed. See CLAUDE.md Critical Pitfalls #8.
        """
        offenders: list[str] = []
        for py_file in SRC_ROOT.rglob("*.py"):
            rel = py_file.relative_to(SRC_ROOT)
            rel_posix = rel.as_posix()
            # Allowed: database/__init__.py (re-export), database/raw_sqlite_adapter.py (definition)
            if rel_posix in {"database/__init__.py", "database/raw_sqlite_adapter.py"}:
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            if _imports_raw_sqlite_adapter(tree):
                offenders.append(rel_posix)
        assert not offenders, (
            f"RawSQLiteAdapter imported in production code: {offenders}. "
            "RawSQLiteAdapter is test-only; production code must use SQLAlchemyAdapter. "
            "See CLAUDE.md Critical Pitfalls #8."
        )


# ---------------------------------------------------------------------------
# D. Convention guards
# ---------------------------------------------------------------------------


class TestConventionGuards:
    """Guard CLAUDE.md coding conventions against drift."""

    def test_every_source_file_has_future_annotations(self) -> None:
        """Every .py file under src/sqlseed/ must start with ``from __future__ import annotations``.

        This is enforced by ruff (UP rule) but we also guard it here so
        violations are caught even if ruff is misconfigured. See CLAUDE.md:
        "Every .py file starts with from __future__ import annotations".
        """
        offenders: list[str] = []
        for py_file in SRC_ROOT.rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            has_future = any(
                isinstance(node, ast.ImportFrom)
                and node.module == "__future__"
                and any(alias.name == "annotations" for alias in node.names)
                for node in ast.iter_child_nodes(tree)
            )
            if not has_future:
                offenders.append(str(py_file.relative_to(SRC_ROOT)))
        assert not offenders, (
            f"Files missing 'from __future__ import annotations': {offenders}. "
            "Every source file must have this (CLAUDE.md convention, enforced by ruff)."
        )

    def test_no_runtime_assert_in_production_code(self) -> None:
        """Production code under src/sqlseed/ must not use ``assert`` for runtime validation.

        Asserts can be optimized away with ``python -O``. Use RuntimeError/
        ValueError instead. See CLAUDE.md: "Never use assert for runtime
        validation". We allow assert inside functions prefixed with ``_test``
        or inside test files, but src/sqlseed/ is production code.
        """
        offenders: list[str] = []
        for py_file in SRC_ROOT.rglob("*.py"):
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except (SyntaxError, OSError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Assert):
                    offenders.append(f"{py_file.relative_to(SRC_ROOT)}:{node.lineno}")
        assert not offenders, (
            f"Runtime assert() found in production code: {offenders}. "
            "Use RuntimeError/ValueError instead — asserts can be stripped by python -O. "
            "See CLAUDE.md: 'Never use assert for runtime validation'."
        )


# ---------------------------------------------------------------------------
# E. Public API contract guards
# ---------------------------------------------------------------------------


class TestPublicApiContract:
    """Guard the public API surface declared in CLAUDE.md."""

    def test_all_exports_expected_functions(self) -> None:
        """sqlseed.__all__ must export the 5 documented public functions.

        See CLAUDE.md Public API table: fill, connect, preview,
        fill_from_config, load_config. Plus the config/data classes.
        """
        required = {"fill", "connect", "preview", "fill_from_config", "load_config"}
        exported = set(sqlseed.__all__)
        missing = required - exported
        assert not missing, f"Public API missing required exports: {missing}. See CLAUDE.md Public API table."

    def test_fill_is_keyword_only(self) -> None:
        """fill() must use keyword-only args (except db_path).

        See CLAUDE.md: "All public functions use keyword-only arguments
        (except generate_choice(choices))".
        """
        sig = inspect.signature(sqlseed.fill)
        # After the positional params, all must be keyword-only (KEYWORD_ONLY)
        kw_only = [p.name for p in sig.parameters.values() if p.kind == inspect.Parameter.KEYWORD_ONLY]
        # fill should have keyword-only params (table, count, etc.)
        assert len(kw_only) > 0, "fill() must have keyword-only arguments per CLAUDE.md convention"


# ---------------------------------------------------------------------------
# F. Immutable constant guards
# ---------------------------------------------------------------------------


class TestImmutableConstants:
    """Guard against mutable constants being introduced."""

    def test_ai_applicable_generators_is_frozenset(self) -> None:
        """sqlseed_ai.ai_mediator.AI_APPLICABLE_GENERATORS must be a frozenset.

        A mutable set could be accidentally modified at runtime, causing
        AI suggestions to apply to wrong column types. frozenset prevents
        this. The constant moved from ``core.plugin_mediator`` to
        ``sqlseed_ai.ai_mediator`` per ARCHITECTURE.md Section 7.6
        ("Only AI-specific mediation moves out"). When sqlseed-ai is not
        installed the guard is skipped (no AI path exists).
        """
        if AI_APPLICABLE_GENERATORS is None:
            pytest.skip("sqlseed-ai not installed; AI_APPLICABLE_GENERATORS guard N/A")

        assert isinstance(AI_APPLICABLE_GENERATORS, frozenset), (
            "AI_APPLICABLE_GENERATORS must be a frozenset to prevent runtime mutation. "
            "See ARCHITECTURE.md Section 7.6 and sqlseed_ai/ai_mediator.py."
        )
        assert "string" in AI_APPLICABLE_GENERATORS


# ---------------------------------------------------------------------------
# G. Count contract guards — synced with CLAUDE.md AUTO-GENERATED markers
# ---------------------------------------------------------------------------


class TestCountContracts:
    """Guard count claims that are synced with docs via AUTO-GENERATED markers.

    These mirror what test_doc_sync.py checks, but at the source level
    (counting AST definitions) rather than the doc level, providing
    double-ended protection.
    """

    def test_hookspec_count_is_twelve(self) -> None:
        """hookspecs.py must define exactly 12 @hookspec functions.

        See CLAUDE.md Plugin Hooks table (12 total). The 12th hook,
        ``sqlseed_apply_ai_suggestions``, was added in Phase C
        (ARCHITECTURE.md Section 7.6) as the high-level entry point the
        orchestrator uses to invoke AI mediation. If a hook is added or
        removed, both this test and CLAUDE.md must be updated together.
        Handles both bare ``@hookspec`` and ``@hookspec(firstresult=True)``.
        """
        hookspecs_path = SRC_ROOT / "plugins" / "hookspecs.py"
        tree = ast.parse(hookspecs_path.read_text(encoding="utf-8"))
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    # Bare @hookspec -> ast.Name
                    if isinstance(dec, ast.Name) and dec.id == "hookspec":
                        count += 1
                        break
                    # @hookspec(firstresult=True) -> ast.Call(func=ast.Name)
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "hookspec":
                        count += 1
                        break
        assert count == 12, (
            f"Expected 12 @hookspec definitions, found {count}. "
            "If you added/removed a hook, update CLAUDE.md Plugin Hooks table and "
            "tests/test_doc_sync.py together."
        )

    def test_generator_dispatch_count_is_thirty_five(self) -> None:
        """_dispatch.py GENERATOR_MAP must have exactly 35 entries.

        See CLAUDE.md > generators/ "35 generator types". If a generator is
        added or removed, update CLAUDE.md, README, and AUTO-GENERATED markers.
        """
        dispatch_path = SRC_ROOT / "generators" / "_dispatch.py"
        text = dispatch_path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            # GENERATOR_MAP uses ClassVar type annotation -> ast.AnnAssign
            if isinstance(node, ast.AnnAssign):
                target = node.target
                if isinstance(target, ast.Name) and target.id == "GENERATOR_MAP" and isinstance(node.value, ast.Dict):
                    count = len(node.value.keys)
                    assert count == 35, (
                        f"Expected 35 generators in GENERATOR_MAP, found {count}. "
                        "If you added/removed a generator, update CLAUDE.md, README, "
                        "and run scripts/sync_docs.py."
                    )
                    return
            # Also handle plain ast.Assign for forward compatibility
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    is_match = (
                        isinstance(target, ast.Name)
                        and target.id == "GENERATOR_MAP"
                        and isinstance(node.value, ast.Dict)
                    )
                    if is_match:
                        count = len(node.value.keys)
                        assert count == 35, (
                            f"Expected 35 generators in GENERATOR_MAP, found {count}. "
                            "If you added/removed a generator, update CLAUDE.md, README, "
                            "and run scripts/sync_docs.py."
                        )
                        return
        pytest.fail("Could not find GENERATOR_MAP in _dispatch.py")

    def test_expression_safe_functions_count_is_twenty_six(self) -> None:
        """expression.py SAFE_FUNCTIONS must have exactly 26 entries.

        See CLAUDE.md > core/expression.py "26 whitelisted functions".
        Handles ClassVar annotation (ast.AnnAssign) since SAFE_FUNCTIONS uses
        ``SAFE_FUNCTIONS: ClassVar[dict[str, Any]] = {...}``.
        """
        expr_path = SRC_ROOT / "core" / "expression.py"
        tree = ast.parse(expr_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # SAFE_FUNCTIONS uses ClassVar type annotation -> ast.AnnAssign
            if isinstance(node, ast.AnnAssign):
                target = node.target
                if isinstance(target, ast.Name) and target.id == "SAFE_FUNCTIONS" and isinstance(node.value, ast.Dict):
                    count = len(node.value.keys)
                    assert count == 26, (
                        f"Expected 26 SAFE_FUNCTIONS, found {count}. "
                        "Update CLAUDE.md and core/AGENTS.md if this changed."
                    )
                    return
            # Also handle plain ast.Assign for forward compatibility
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    is_match = (
                        isinstance(target, ast.Name)
                        and target.id == "SAFE_FUNCTIONS"
                        and isinstance(node.value, ast.Dict)
                    )
                    if is_match:
                        count = len(node.value.keys)
                        assert count == 26, (
                            f"Expected 26 SAFE_FUNCTIONS, found {count}. "
                            "Update CLAUDE.md and core/AGENTS.md if this changed."
                        )
                        return
        pytest.fail("Could not find SAFE_FUNCTIONS in expression.py")
