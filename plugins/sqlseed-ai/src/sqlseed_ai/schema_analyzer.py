"""Whole/partial database semantic analyzer.

Analyzes database schema (target + context tables) via LLM to produce
business-aware YAML configs. This is the core of "understanding
whole-database business logic":

1. Target tables: LLM generates full YAML column configs.
2. Context tables: FK parents, schema-only (no YAML generated).
3. On-demand: full database, partial tables, or partial with deps.

The analyzer does NOT generate data — it outputs a GeneratorConfig
dict that users can save as YAML, review, edit, and feed back to
core for data generation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlseed_ai.dependency_resolver import DependencyResolver, ResolvedTables

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.config import AIConfig

    from sqlseed.database._protocol import DatabaseAdapter, ForeignKeyInfo

logger = get_logger(__name__)


@dataclass(frozen=True)
class AnalysisRequest:
    """Request bundle for LLM semantic analysis.

    Attributes:
        target_tables: Tables to generate YAML for.
        context_tables: FK parent tables (schema-only context).
        all_tables_schema: Full schema dict for target + context tables.
        foreign_keys: All FK relationships in the analyzed scope, keyed by
            table name. Typed as ``dict[str, list[ForeignKeyInfo]]`` so mypy
            strict can verify ``fk.column`` / ``fk.ref_table`` access in
            ``_build_user_prompt``.
    """
    target_tables: list[str]
    context_tables: list[str]
    all_tables_schema: dict[str, dict[str, Any]] = field(default_factory=dict)
    foreign_keys: dict[str, list[ForeignKeyInfo]] = field(default_factory=dict)


class SchemaSemanticAnalyzer:
    """Analyze database schema via LLM to produce business YAML configs.

    On-demand analysis modes:
    - Full database: tables=None (analyze all tables)
    - Partial tables: tables=["orders", "items"] (analyze specified)
    - Dependency-aware: include_dependencies=True (default, includes FK parents as context)

    The LLM sees target + context schema but outputs YAML ONLY for targets.
    Context tables provide relationship understanding.
    """

    def __init__(self, config: AIConfig | None = None) -> None:
        self._config = config
        self._sa: Any = None  # Lazy-init SchemaAnalyzer

    @property
    def _analyzer(self) -> Any:
        """Lazy-init SchemaAnalyzer for LLM calls."""
        if self._sa is None:
            from sqlseed_ai.analyzer import SchemaAnalyzer
            self._sa = SchemaAnalyzer(config=self._config)
        return self._sa

    def build_request(
        self,
        db: DatabaseAdapter,
        *,
        tables: list[str] | None = None,
        include_dependencies: bool = True,
        max_depth: int = 5,
    ) -> AnalysisRequest:
        """Build an AnalysisRequest from database + table selection.

        Args:
            db: Database adapter for schema introspection.
            tables: Target tables. None means all tables in database.
            include_dependencies: If True, resolve FK parents as context.
            max_depth: Max FK recursion depth (default 5).

        Returns:
            AnalysisRequest with target/context separation and full schema.
        """
        target_tables = db.get_table_names() if tables is None else list(tables)

        resolver = DependencyResolver(db, max_depth=max_depth)
        resolved: ResolvedTables = resolver.resolve(
            target_tables, include_dependencies=include_dependencies
        )

        all_tables = set(target_tables) | set(resolved.context_tables)
        all_tables_schema: dict[str, dict[str, Any]] = {}
        for table in all_tables:
            all_tables_schema[table] = self._get_table_schema(db, table)

        return AnalysisRequest(
            target_tables=target_tables,
            context_tables=resolved.context_tables,
            all_tables_schema=all_tables_schema,
            foreign_keys=resolved.foreign_keys,
        )

    def analyze(
        self,
        db: DatabaseAdapter,
        *,
        tables: list[str] | None = None,
        include_dependencies: bool = True,
        max_depth: int = 5,
    ) -> dict[str, Any]:
        """Analyze database and return GeneratorConfig dict.

        Args:
            db: Database adapter.
            tables: Target tables (None = all).
            include_dependencies: Include FK parents as context.
            max_depth: FK recursion depth limit.

        Returns:
            GeneratorConfig dict (can be serialized to YAML).
        """
        request = self.build_request(
            db,
            tables=tables,
            include_dependencies=include_dependencies,
            max_depth=max_depth,
        )

        messages = self._build_llm_messages(request)
        config_dict = self._call_llm(messages)
        return self._filter_to_targets(config_dict, request.target_tables)

    def _get_table_schema(self, db: DatabaseAdapter, table: str) -> dict[str, Any]:
        """Get full schema for a single table.

        Uses ColumnInfo.type (not type_name). Length parsed downstream
        from the type string.
        """
        try:
            columns = db.get_column_info(table)
            fks = db.get_foreign_keys(table)
            checks = []
            if hasattr(db, "get_check_constraints"):
                checks = db.get_check_constraints(table)
            return {
                "columns": [
                    {
                        "name": c.name,
                        "type": c.type,
                        "nullable": c.nullable,
                        "is_pk": c.is_primary_key,
                        "is_autoincrement": c.is_autoincrement,
                        "default": c.default,
                        "is_computed": getattr(c, "is_computed", False),
                    }
                    for c in columns
                ],
                "foreign_keys": [
                    {"column": fk.column, "ref_table": fk.ref_table, "ref_column": fk.ref_column}
                    for fk in fks
                ],
                "check_constraints": [
                    {"name": c.name, "columns": list(c.columns), "expression": c.expression}
                    for c in checks
                ],
            }
        except (ValueError, RuntimeError, OSError) as e:
            logger.debug("Failed to get schema for table", table=table, error=str(e))
            return {"columns": [], "foreign_keys": [], "check_constraints": []}

    def _build_llm_messages(self, request: AnalysisRequest) -> list[dict[str, str]]:
        """Build LLM messages with target/context separation."""
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(request)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _build_system_prompt(self) -> str:
        """Build system prompt for whole-DB analysis."""
        lines = [
            "You are a database semantic analyzer. Your task is to analyze database schema "
            "and generate a YAML test data configuration file that captures business logic.",
            "",
            "## Output Format",
            "Output ONLY a valid JSON object (will be converted to YAML) with this structure:",
            "{",
            '  "tables": [',
            "    {",
            '      "name": "<table_name>",',
            '      "count": 1000,',
            '      "columns": [',
            "        {",
            '          "name": "<column_name>",',
            '          "generator": "<generator_name>",',
            '          "params": {...},',
            '          "constraints": {"unique": false, "min_value": null, "max_value": null, "regex": null},',
            '          "derive_from": null,',
            '          "expression": null',
            "        }",
            "      ]",
            "    }",
            "  ]",
            "}",
            "",
            "## Critical Rules",
            "1. GENERATE YAML ONLY for TARGET tables. NEVER generate config for CONTEXT tables.",
            "2. Skip PRIMARY KEY AUTOINCREMENT columns (DB auto-fills).",
            "3. Skip columns with DEFAULT values (DB auto-fills).",
            "4. Skip GENERATED/computed columns (DB auto-fills).",
            "5. Skip FOREIGN KEY columns — they are auto-resolved by core from parent tables.",
            "6. For UNIQUE columns, set constraints.unique=true and choose a generator that ensures uniqueness.",
            "7. For CHECK constraints:",
            "   - CHECK(x IN ('A','B')) -> use \"choice\" generator with params.choices",
            "   - CHECK(x BETWEEN low AND high) -> use \"integer\"/\"float\" with min_value/max_value",
            "   - CHECK(length(x) BETWEEN low AND high) -> use \"string\" with min_length/max_length",
            "   - Cross-column CHECK (e.g., sale_price >= cost_price) -> use \"derive_from\" with an expression",
            "8. Choose generators based on column NAME semantics:",
            "   - email columns -> \"email\" generator",
            "   - phone columns -> \"pattern\" generator with regex params",
            "   - *_name (person) -> \"name\" generator",
            "   - *_name (non-person) -> \"word\" generator",
            "   - *_code, *_no, sku -> \"string\" with alphanumeric charset and fixed length",
            "   - timestamps (*_at, *_date) -> \"datetime\" generator",
            "9. If business semantics are unclear, choose a type-appropriate generator (schema-valid fallback).",
            "10. Output ONLY JSON, no explanations, no markdown fences.",
        ]
        return "\n".join(lines)

    def _build_user_prompt(self, request: AnalysisRequest) -> str:
        """Build user prompt with target/context separation and full schema."""
        lines: list[str] = []

        lines.append("# Database Schema Analysis Request")
        lines.append("")

        lines.append("## TARGET TABLES (GENERATE YAML for these)")
        for t in request.target_tables:
            lines.append(f"- {t}")
        lines.append("")

        if request.context_tables:
            lines.append("## CONTEXT TABLES (for understanding relationships, DO NOT generate YAML)")
            for t in request.context_tables:
                lines.append(f"- {t}")
            lines.append("")

        if request.foreign_keys:
            lines.append("## Foreign Key Relationships")
            for table, fks in request.foreign_keys.items():
                for fk in fks:
                    lines.append(
                        f"- {table}.{fk.column} -> {fk.ref_table}.{fk.ref_column}"
                    )
            lines.append("")
            lines.append("NOTE: Foreign-key columns are auto-resolved by core. Do NOT include them in columns list.")
            lines.append("")

        lines.append("## Full Schema (Target + Context Tables)")
        for table in sorted(set(request.target_tables) | set(request.context_tables)):
            schema = request.all_tables_schema.get(table, {})
            lines.append(f"### Table: {table}")
            cols = schema.get("columns", [])
            if cols:
                lines.append("Columns:")
                for c in cols:
                    attrs = []
                    if c.get("is_pk"):
                        attrs.append("PK")
                    if c.get("is_autoincrement"):
                        attrs.append("AUTOINCREMENT")
                    if not c.get("nullable", True):
                        attrs.append("NOT NULL")
                    if c.get("default") is not None:
                        attrs.append(f"DEFAULT={c['default']}")
                    if c.get("is_computed"):
                        attrs.append("GENERATED")
                    attr_str = f" [{', '.join(attrs)}]" if attrs else ""
                    lines.append(f"  - {c['name']}: {c['type']}{attr_str}")

            fks = schema.get("foreign_keys", [])
            if fks:
                lines.append("Foreign Keys:")
                for fk in fks:
                    lines.append(f"  - {fk['column']} -> {fk['ref_table']}.{fk['ref_column']}")

            checks = schema.get("check_constraints", [])
            if checks:
                lines.append("CHECK Constraints:")
                for chk in checks:
                    cols_str = ", ".join(chk.get("columns", []))
                    lines.append(f"  - CHECK ({chk['expression']}) [columns: {cols_str}]")
            lines.append("")

        lines.append("## Task")
        lines.append(
            "Generate the JSON config for TARGET tables only. "
            "Use CONTEXT tables to understand relationships and business semantics."
        )
        return "\n".join(lines)

    def _call_llm(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Call LLM and return parsed config dict."""
        raise NotImplementedError("Implemented in Task 5.3")

    def _filter_to_targets(
        self, config_dict: dict[str, Any], target_tables: list[str]
    ) -> dict[str, Any]:
        """Ensure config only contains target tables (not context)."""
        if "tables" not in config_dict:
            return config_dict
        target_set = set(target_tables)
        config_dict["tables"] = [
            t for t in config_dict["tables"] if t.get("name") in target_set
        ]
        return config_dict
