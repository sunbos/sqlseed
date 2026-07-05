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

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlseed_ai.dependency_resolver import DependencyResolver, ResolvedTables

from sqlseed._utils.logger import get_logger
from sqlseed._utils.sql_safe import quote_identifier

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


def apply_auto_fix_rules_1_13(
    config: dict[str, Any],
    schema: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply auto-fix rules #1-#13 to a config dict.

    P3 #5 fix: extracted from SchemaSemanticAnalyzer._auto_fix_config as
    a public function so Stage3Validator can call it without accessing
    a private method of another class.

    The existing SchemaSemanticAnalyzer._auto_fix_config method now
    delegates to this function (preserved for backward compatibility).

    Args:
        config: Parsed config dict from LLM (single-table {"name":...}
            or multi-table {"tables":[...]} format).
        schema: Optional table schema dict (used by Fixes 5, 6, and 8).
            When None, those fixes are skipped.

    Returns:
        The same dict with fixes applied in-place.
    """
    if "tables" in config:
        tables = config["tables"]
    elif "name" in config:
        tables = [config]
    else:
        return config

    for table in tables:
        if not isinstance(table, dict):
            continue
        columns = table.get("columns", [])
        if not isinstance(columns, list):
            continue
        for col in columns:
            if not isinstance(col, dict):
                continue
            col_name = col.get("name", "<unknown>")
            derive_from = col.get("derive_from")
            generator = col.get("generator")
            # Fix 1: mutual exclusivity — derive_from wins
            if derive_from and generator:
                logger.warning(
                    "Auto-fix: stripping generator+params (derive_from takes precedence)",
                    column=col_name,
                    generator=generator,
                )
                col.pop("generator", None)
                col.pop("params", None)
                # Re-read derive_from after stripping generator
                derive_from = col.get("derive_from")
                generator = None
            # Fix 2: weighted_choices in params but generator is "choice"
            params = col.get("params")
            if generator == "choice" and isinstance(params, dict) and "weighted_choices" in params:
                logger.warning(
                    "Auto-fix: generator 'choice' has weighted_choices, fixing to 'weighted_choice'",
                    column=col_name,
                )
                col["generator"] = "weighted_choice"
            # Fix 3 & 4: single-column derive_from expression corrections
            expression = col.get("expression")
            if derive_from and expression and isinstance(expression, str):
                is_single = isinstance(derive_from, str) or (isinstance(derive_from, list) and len(derive_from) == 1)
                if is_single:
                    # Fix 3: replace value[0] with value (scalar, not subscriptable)
                    if "value[0]" in expression:
                        logger.warning(
                            "Auto-fix: replacing value[0] with value (single-column derive_from)",
                            column=col_name,
                        )
                        expression = expression.replace("value[0]", "value")
                        col["expression"] = expression
                    # Fix 4: replace source column name with "value" if
                    # the LLM used the column name directly instead of
                    # the "value" keyword (causes NameNotDefined at eval)
                    if isinstance(derive_from, str):
                        src_col = derive_from
                    elif isinstance(derive_from, list) and derive_from:
                        src_col = derive_from[0]
                    else:
                        src_col = ""
                    if src_col and src_col in expression and not re.search(r"\bvalue\b", expression):
                        logger.warning(
                            "Auto-fix: replacing source column name with 'value' (single-column derive_from)",
                            column=col_name,
                            source_column=src_col,
                        )
                        col["expression"] = re.sub(r"\b" + re.escape(src_col) + r"\b", "value", expression)
            # Fix 7: orphan expression cleanup
            # If generator is set (source mode) and derive_from is null,
            # but expression is set, the expression is meaningless in
            # source mode — remove it to avoid confusion.
            if generator and not derive_from and col.get("expression"):
                logger.warning(
                    "Auto-fix: removing orphan expression (generator set, derive_from is null)",
                    column=col_name,
                )
                col.pop("expression", None)

            # Fix 9: name column generator correction.
            # Columns ending in _name should use readable generators, not
            # string/text (which produce random gibberish). Person name
            # columns (full_name, first_name, last_name, etc.) get the
            # appropriate person-name generator; merchant/company names get
            # "company"; all other *_name columns get "word".
            if (
                isinstance(col_name, str)
                and col_name.endswith("_name")
                and col.get("generator") in ("string", "text")
                and not col.get("derive_from")
            ):
                old_gen = col.get("generator")
                name_lower = col_name.lower()
                if "merchant" in name_lower or "company" in name_lower:
                    new_gen = "company"
                elif name_lower in ("full_name", "person_name") or name_lower == "name":
                    new_gen = "name"
                elif name_lower in ("first_name", "fname"):
                    new_gen = "first_name"
                elif name_lower in ("last_name", "lname", "surname"):
                    new_gen = "last_name"
                else:
                    new_gen = "word"
                logger.warning(
                    "Auto-fix: correcting name column generator (string/text -> readable)",
                    table=table.get("name"),
                    column=col_name,
                    old_generator=old_gen,
                    new_generator=new_gen,
                )
                col["generator"] = new_gen
                col.pop("params", None)

            # Fix 10: add max_value to integer generator when missing.
            # Without max_value, the generator can produce absurdly large
            # numbers (e.g., stock=503893). Add a reasonable default based
            # on column name heuristics.
            if (
                col.get("generator") == "integer"
                and isinstance(col.get("params"), dict)
                and "max_value" not in col["params"]
            ):
                if col_name and isinstance(col_name, str):
                    name_lower = col_name.lower()
                    if "quantity" in name_lower:
                        default_max = 100
                    elif "count" in name_lower or "stock" in name_lower:
                        default_max = 9999
                    else:
                        default_max = 99999
                else:
                    default_max = 99999
                logger.warning(
                    "Auto-fix: adding max_value to integer generator",
                    table=table.get("name"),
                    column=col_name,
                    max_value=default_max,
                )
                col["params"]["max_value"] = default_max

            # Fix 11: enforce semantic generators for email/phone columns.
            # *_email -> email; phone-like columns (phone, mobile, telephone,
            # tel, cell, cellphone, contact_number) -> phone.
            # Detect ANY non-matching generator (not just "string") because LLMs
            # sometimes assign "name", "text", or "word" to email/phone columns,
            # producing semantically wrong data (e.g. person names in email
            # columns). The "pattern" generator is preserved (custom regex may
            # be intentional for site-specific email/phone formats).
            if isinstance(col_name, str) and not col.get("derive_from"):
                gen = col.get("generator")
                if (col_name.endswith("_email") or col_name == "email") and gen not in (
                    "email",
                    "pattern",
                    None,
                ):
                    logger.warning(
                        "Auto-fix: correcting email column generator (non-email -> email)",
                        table=table.get("name"),
                        column=col_name,
                        original_generator=gen,
                    )
                    col["generator"] = "email"
                    col.pop("params", None)
                elif (
                    col_name
                    in (
                        "phone",
                        "mobile",
                        "telephone",
                        "tel",
                        "cell",
                        "cellphone",
                        "contact_number",
                    )
                    or col_name.endswith("_phone")
                    or col_name.endswith("_mobile")
                ) and gen not in ("phone", "pattern", None):
                    logger.warning(
                        "Auto-fix: correcting phone column generator (non-phone -> phone)",
                        table=table.get("name"),
                        column=col_name,
                        original_generator=gen,
                    )
                    col["generator"] = "phone"
                    col.pop("params", None)

            # Fix 12: phone+regex mismatch. The `phone` generator does NOT
            # accept a `regex` parameter (only `pattern` does). When the LLM
            # produces `generator: phone` with `params: {regex: ...}`, convert
            # to `generator: pattern` so the regex is honored. Without this
            # fix, fill crashes with:
            #   TypeError: _gen_phone() got an unexpected keyword argument 'regex'
            if col.get("generator") == "phone" and isinstance(col.get("params"), dict) and "regex" in col["params"]:
                regex_val = col["params"]["regex"]
                logger.warning(
                    "Auto-fix: converting phone+regex to pattern generator (phone does not accept regex param)",
                    table=table.get("name"),
                    column=col_name,
                    regex=regex_val,
                )
                col["generator"] = "pattern"
                col["params"] = {"regex": regex_val}

        # Fix 5: remove GENERATED columns from config
        if schema:
            table_name = table.get("name")
            if isinstance(table_name, str) and table_name in schema:
                table_schema = schema[table_name]
                generated_cols = {
                    c["name"] for c in table_schema.get("columns", []) if isinstance(c, dict) and c.get("is_computed")
                }
                if generated_cols:
                    logger.warning(
                        "Auto-fix: removing GENERATED columns from config",
                        table=table_name,
                        columns=list(generated_cols),
                    )
                    table["columns"] = [
                        c for c in columns if isinstance(c, dict) and c.get("name") not in generated_cols
                    ]

        # Fix 6: enforce UNIQUE indexes as constraints.unique=true
        if schema:
            table_name = table.get("name")
            if isinstance(table_name, str) and table_name in schema:
                table_schema = schema[table_name]
                unique_cols: set[str] = set()
                # From explicit UNIQUE indexes (CREATE INDEX ... UNIQUE)
                for idx in table_schema.get("unique_indexes", []):
                    if isinstance(idx, dict) and idx.get("unique"):
                        for col_in_idx in idx.get("columns", []):
                            unique_cols.add(col_in_idx)
                # From column-level UNIQUE (SQLite PRAGMA auto-indexes)
                for col_name_unique in table_schema.get("unique_columns", []):
                    unique_cols.add(col_name_unique)
                if unique_cols:
                    for c in table.get("columns", []):
                        if isinstance(c, dict) and c.get("name") in unique_cols:
                            constraints = c.get("constraints")
                            if not isinstance(constraints, dict):
                                constraints = {}
                                c["constraints"] = constraints
                            if not constraints.get("unique"):
                                logger.warning(
                                    "Auto-fix: setting constraints.unique=true (UNIQUE index detected in schema)",
                                    table=table_name,
                                    column=c.get("name"),
                                )
                                constraints["unique"] = True

        # Fix 8: cross-column CHECK — convert source-mode columns to derive_from.
        # When a column is in source mode but bounded by another column via
        # a CHECK like "col >= 0 AND col <= other_col", generating it
        # independently risks CHECK violations (e.g., discount=0.5 but
        # price_per_unit=0.01). Convert to derive_from so the value is
        # always within [0, other_col].
        if schema:
            table_name = table.get("name")
            if isinstance(table_name, str) and table_name in schema:
                table_schema = schema[table_name]
                checks = table_schema.get("check_constraints", [])
                valid_cols = {
                    c["name"]
                    for c in table_schema.get("columns", [])
                    if isinstance(c, dict) and isinstance(c.get("name"), str)
                }
                for c in table.get("columns", []):
                    if not isinstance(c, dict):
                        continue
                    col_name = c.get("name")
                    if not isinstance(col_name, str):
                        continue
                    # Only fix source-mode columns (has generator, no derive_from)
                    if not c.get("generator") or c.get("derive_from"):
                        continue
                    # Find a cross-column CHECK involving this column
                    for chk in checks:
                        if not isinstance(chk, dict):
                            continue
                        chk_cols = set(chk.get("columns", []))
                        if col_name not in chk_cols or len(chk_cols) <= 1:
                            continue
                        expr = chk.get("expression", "")
                        if not isinstance(expr, str):
                            continue
                        # Pattern: {col} <= {other_col} (upper bound is another column)
                        upper_pat = re.search(
                            rf"\b{re.escape(col_name)}\s*<=\s*([a-zA-Z_]\w*)",
                            expr,
                            re.IGNORECASE,
                        )
                        # Pattern: {col} >= 0 or {col} > 0 (lower bound is zero)
                        lower_zero_pat = re.search(
                            rf"\b{re.escape(col_name)}\s*>=?\s*0\b",
                            expr,
                            re.IGNORECASE,
                        )
                        if upper_pat and lower_zero_pat:
                            other_col = upper_pat.group(1)
                            # Validate other_col is a real column (not the same column)
                            if other_col == col_name or other_col not in valid_cols:
                                continue
                            logger.warning(
                                "Auto-fix: converting source-mode column to derive_from "
                                "(cross-column CHECK constraint detected)",
                                table=table_name,
                                column=col_name,
                                source_column=other_col,
                                check_expression=expr,
                            )
                            c["derive_from"] = [other_col]
                            c["expression"] = "round(random_float(0, value), 2)"
                            c.pop("generator", None)
                            c.pop("params", None)
                            break  # Only convert once per column
                        # Lower-bound branch: col >= other_col (where other_col is
                        # a real column, not 0). Handles constraints like:
                        #   end_date >= start_date  →  end_date = start_date + random_int(0, 30)
                        #   sale_price >= cost_price →  sale_price = cost_price + random_int(0, 100)
                        # Only triggers when the upper-bound pattern did NOT match
                        # (i.e., no "col <= other_col AND col >= 0" pair found).
                        lower_col_pat = re.search(
                            rf"\b{re.escape(col_name)}\s*>=?\s*([a-zA-Z_]\w*)",
                            expr,
                            re.IGNORECASE,
                        )
                        if lower_col_pat:
                            other_col = lower_col_pat.group(1)
                            # Validate other_col is a real column (not same col, not a number)
                            if other_col == col_name or other_col not in valid_cols:
                                continue
                            # Detect strict inequality (> vs >=) for min offset
                            match_str = lower_col_pat.group(0)
                            min_offset = 1 if (">" in match_str and ">=" not in match_str) else 0
                            # Determine delta based on column type from schema
                            col_type_upper = ""
                            for schema_col in table_schema.get("columns", []):
                                if isinstance(schema_col, dict) and schema_col.get("name") == col_name:
                                    col_type_upper = str(schema_col.get("type", "")).upper()
                                    break
                            if "DATE" in col_type_upper:
                                # Date columns return ISO date strings from the
                                # generator. simpleeval cannot do date arithmetic
                                # on strings (no date_parse in SAFE_FUNCTIONS), so
                                # we use expression "value" (end = start) to
                                # guarantee the constraint. The transform_row hook
                                # in the AI plugin converts the string to a
                                # datetime.date object for the DB.
                                expr_str = "value"
                            elif "INT" in col_type_upper:
                                delta: int | float = 100
                                expr_str = f"value + random_int({min_offset}, {delta})"
                            elif any(t in col_type_upper for t in ("REAL", "FLOAT", "DOUBLE", "DECIMAL")):
                                delta = 1000.0
                                expr_str = f"round(value + random_float({min_offset}, {delta}), 2)"
                            else:
                                delta = 100
                                expr_str = f"value + random_int({min_offset}, {delta})"
                            logger.warning(
                                "Auto-fix: converting source-mode column to derive_from "
                                "(lower-bound cross-column CHECK constraint detected)",
                                table=table_name,
                                column=col_name,
                                source_column=other_col,
                                check_expression=expr,
                                expression=expr_str,
                            )
                            c["derive_from"] = [other_col]
                            c["expression"] = expr_str
                            c.pop("generator", None)
                            c.pop("params", None)
                            break  # Only convert once per column

        # Fix 13: detect UNIQUE NOT NULL columns omitted by the LLM and
        # add them with a `template` generator. Small LLMs sometimes skip
        # UNIQUE NOT NULL columns (e.g., employee_id), causing the fill to
        # use a default `string` generator that produces random gibberish
        # like 'c3fb3bIiGoq57nU' instead of readable codes like 'EMP-0001'.
        # We detect such columns in the schema and add them to the config
        # with a template generator derived from the column name.
        if schema:
            table_name = table.get("name")
            if isinstance(table_name, str) and table_name in schema:
                table_schema = schema[table_name]
                # Collect UNIQUE columns from indexes and column-level UNIQUE
                unique_cols = set()
                for idx in table_schema.get("unique_indexes", []):
                    if isinstance(idx, dict) and idx.get("unique"):
                        for col_in_idx in idx.get("columns", []):
                            unique_cols.add(col_in_idx)
                for col_name_unique in table_schema.get("unique_columns", []):
                    unique_cols.add(col_name_unique)
                # Find NOT NULL columns (from schema column info)
                not_null_cols: dict[str, str] = {}  # name -> type
                for sc in table_schema.get("columns", []):
                    if isinstance(sc, dict) and isinstance(sc.get("name"), str) and not sc.get("nullable", True):
                        not_null_cols[sc["name"]] = str(sc.get("type", ""))
                # Find UNIQUE NOT NULL columns missing from config
                configured_cols = {
                    c.get("name")
                    for c in table.get("columns", [])
                    if isinstance(c, dict) and isinstance(c.get("name"), str)
                }
                for col_name_schema, _col_type in not_null_cols.items():
                    if col_name_schema not in unique_cols:
                        continue
                    if col_name_schema in configured_cols:
                        continue
                    # Skip auto-increment PKs and columns with defaults
                    for sc in table_schema.get("columns", []):
                        if isinstance(sc, dict) and sc.get("name") == col_name_schema:
                            if sc.get("is_autoincrement") or sc.get("is_primary_key"):
                                break
                            if sc.get("default") is not None:
                                break
                            # Skip GENERATED columns
                            if sc.get("is_computed"):
                                break
                            # Skip foreign-key columns (auto-resolved by core)
                            if sc.get("is_foreign_key"):
                                break
                            # Derive a prefix from the column name
                            first_part = col_name_schema.split("_")[0] if "_" in col_name_schema else col_name_schema
                            prefix = first_part[:4].upper()
                            template_str = f"{prefix}-{{sequence:04d}}"
                            logger.warning(
                                "Auto-fix: adding missing UNIQUE NOT NULL column with template generator",
                                table=table_name,
                                column=col_name_schema,
                                template=template_str,
                            )
                            table.setdefault("columns", []).append(
                                {
                                    "name": col_name_schema,
                                    "generator": "template",
                                    "params": {"template": template_str},
                                    "constraints": {"unique": True},
                                }
                            )
                            break
    return config


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
        resolved: ResolvedTables = resolver.resolve(target_tables, include_dependencies=include_dependencies)

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
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        """Analyze database and return GeneratorConfig dict.

        For multiple target tables, calls LLM per-table to avoid
        overwhelming small models. Each LLM call sees the FULL schema
        (target + context) for relationship understanding, but generates
        YAML for ONLY ONE table. Results are combined into a single dict.

        Args:
            db: Database adapter.
            tables: Target tables (None = all).
            include_dependencies: Include FK parents as context.
            max_depth: FK recursion depth limit.
            progress_callback: Optional callable ``(table: str, index: int, total: int) -> None``
                invoked before each table's LLM call. Use for CLI progress display.

        Returns:
            GeneratorConfig dict (can be serialized to YAML).
        """
        request = self.build_request(
            db,
            tables=tables,
            include_dependencies=include_dependencies,
            max_depth=max_depth,
        )

        # Single table (or empty): original single-call behavior
        if len(request.target_tables) <= 1:
            if progress_callback is not None and request.target_tables:
                progress_callback(request.target_tables[0], 1, 1)
            messages = self._build_llm_messages(request)
            config_dict = self._call_llm(messages)
            self._auto_fix_config(config_dict, request.all_tables_schema)
            return self._filter_to_targets(config_dict, request.target_tables)

        # Multiple tables: per-table LLM calls (small-model friendly)
        # Each call sees full schema (target + context) but generates YAML
        # for only ONE table. This keeps prompt size manageable for 2B-7B
        # parameter models like Gemma 4 E2B while preserving whole-DB context.
        all_tables_config: list[dict[str, Any]] = []
        total = len(request.target_tables)
        for idx, table in enumerate(request.target_tables, 1):
            if progress_callback is not None:
                progress_callback(table, idx, total)
            logger.info("Analyzing table via LLM", table=table, total=total, index=idx)
            single_request = AnalysisRequest(
                target_tables=[table],
                context_tables=request.context_tables,
                all_tables_schema=request.all_tables_schema,
                foreign_keys=request.foreign_keys,
            )
            messages = self._build_llm_messages(single_request)
            try:
                table_config = self._call_llm(messages)
            except (ValueError, RuntimeError, OSError) as e:
                logger.warning("LLM call failed for table, skipping", table=table, error=str(e))
                continue

            self._auto_fix_config(table_config, request.all_tables_schema)

            # Accept both formats: {"tables":[...]} (multi) and
            # {"name":...,"columns":[...]} (single). Normalize to list.
            table_list = table_config.get("tables", []) if isinstance(table_config, dict) else []
            if not table_list and isinstance(table_config, dict) and "name" in table_config:
                # LLM returned single-table format; wrap in list.
                table_list = [table_config]
            if table_list:
                all_tables_config.extend(table_list)
            else:
                logger.warning("LLM returned no config for table", table=table)

        return {"tables": all_tables_config}

    def _get_table_schema(self, db: DatabaseAdapter, table: str) -> dict[str, Any]:
        """Get full schema for a single table.

        Uses ColumnInfo.type (not type_name). Length parsed downstream
        from the type string. Includes UNIQUE indexes so the LLM can set
        constraints.unique=true correctly.

        Also detects column-level UNIQUE via SQLite PRAGMA (SQLAlchemy's
        get_indexes() does not return auto-indexes for column-level UNIQUE
        constraints like ``email TEXT UNIQUE NOT NULL``).
        """
        try:
            columns = db.get_column_info(table)
            fks = db.get_foreign_keys(table)
            checks = []
            if hasattr(db, "get_check_constraints"):
                checks = db.get_check_constraints(table)
            indexes: list[Any] = []
            if hasattr(db, "get_index_info"):
                indexes = db.get_index_info(table)
            # Detect column-level UNIQUE via PRAGMA (SQLite fallback).
            # SQLAlchemy's get_indexes() misses auto-indexes for column-level
            # UNIQUE constraints. This PRAGMA query catches them.
            unique_columns: list[str] = []
            try:
                safe_table = quote_identifier(table)
                result = db.execute(f"PRAGMA index_list({safe_table})")
                rows = result.fetchall() if hasattr(result, "fetchall") else []
                for row in rows:
                    # row: (seq, name, unique, origin, partial)
                    if len(row) >= 3 and row[2]:
                        idx_name = row[1]
                        idx_result = db.execute(f"PRAGMA index_info({quote_identifier(idx_name)})")
                        idx_rows = idx_result.fetchall() if hasattr(idx_result, "fetchall") else []
                        for ir in idx_rows:
                            # ir: (seqno, cid, name)
                            if len(ir) >= 3 and ir[2]:
                                unique_columns.append(ir[2])
            except Exception as exc:
                logger.debug("PRAGMA index_list fallback failed", table=table, error=str(exc))
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
                    {"column": fk.column, "ref_table": fk.ref_table, "ref_column": fk.ref_column} for fk in fks
                ],
                "check_constraints": [
                    {"name": c.name, "columns": list(c.columns), "expression": c.expression} for c in checks
                ],
                "unique_indexes": [
                    {"name": idx.name, "columns": list(idx.columns), "unique": idx.unique}
                    for idx in indexes
                    if getattr(idx, "unique", False)
                ],
                "unique_columns": unique_columns,
            }
        except (ValueError, RuntimeError, OSError) as e:
            logger.debug("Failed to get schema for table", table=table, error=str(e))
            return {
                "columns": [],
                "foreign_keys": [],
                "check_constraints": [],
                "unique_indexes": [],
                "unique_columns": [],
            }

    def _build_llm_messages(self, request: AnalysisRequest) -> list[dict[str, str]]:
        """Build LLM messages with target/context separation."""
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(request)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _build_system_prompt(self) -> str:
        """Build system prompt for whole-DB analysis.

        Compact tier: includes P0-P3 capabilities (template, weighted_choice,
        lookup, multi-column derive_from) but kept under ~1000 tokens to fit
        small-context models (e.g., LM Studio's default 2048 n_ctx).
        """
        return """You are a database test data engineer. Output JSON config for the TARGET table only.

Generators: string(min_length,max_length,charset), integer(min_value,max_value),
float(min_value,max_value,precision), boolean, name, first_name, last_name, username,
email, phone, address, company, city, country, state, zip_code, country_code,
job_title, url, ipv4, uuid, date(start_year,end_year), datetime(start_year,end_year),
timestamp, text(min_length,max_length), sentence, password, word, choice,
json(schema), pattern(regex), template, weighted_choice.

template generator: params={"template":"FORMAT","sequence_start":0,"sequence_step":1}.
  FORMAT MUST contain {sequence} or {random_digits:N} or {random_string:N} placeholder.
  Example: params={"template":"CAT-{sequence:04d}"} -> CAT-0001, CAT-0002, ...
  Use for *_code/*_no/sku/username (UNIQUE business codes).
  Use TABLE-SPECIFIC prefix: MER- for merchants, PROD- for products, ITEM- for items,
  ORD- for orders, CAT- for categories, USER- for users. NEVER use literal "PREFIX".
  NEVER use literal "XXXX" or "0000" in place of {sequence}. The template MUST contain
  the {sequence} placeholder for UNIQUE columns, otherwise all rows will have the same value.
choice generator: params={"choices":["a","b","c"]}. Uniform random selection.
weighted_choice generator: params={"weighted_choices":{"active":80,"suspended":15,"closed":5}}.
  Weighted random selection. Use for status/role CHECK IN columns.
  IMPORTANT: generator MUST be "weighted_choice" (NOT "choice") when using weighted_choices.
lookup(table,column,key): cross-table value fetch. Use in derive_from expressions.
  Example: {"name":"unit_price","derive_from":"item_id","expression":"lookup('items','price',value)"}

## Available expression functions
In derive_from expressions, you can use these functions:
  len, int, str, float, abs, min, max, round, upper, lower, strip, concat,
  random_float(min,max), random_int(min,max), random_choice(list), lookup(table,col,key).
Example: {"name":"discount","derive_from":"price_per_unit","expression":"round(random_float(0,value),2)"}
Use random_float for random derived values bounded by another column (e.g., discounts, margins).

## CRITICAL: value vs value[0]
- SINGLE-column derive_from: "value" is the SCALAR value. Use "value" (NOT "value[0]").
  RIGHT: {"name":"sale_price","derive_from":"cost_price","expression":"round(value*1.2,2)"}
  WRONG: {"name":"sale_price","derive_from":"cost_price","expression":"round(value[0]*1.2,2)"}
  WRONG: {"name":"sale_price","derive_from":"cost_price",  # using column NAME, not "value"
           "expression":"round(cost_price*1.2,2)"}
- MULTI-column derive_from: "value" is a LIST. Use "value[0]", "value[1]", etc.
  RIGHT: {"name":"total","derive_from":["price","qty"],"expression":"round(value[0]*value[1],2)"}
- The expression engine ONLY knows the keyword "value". It does NOT know source column names.
  NEVER use the source column name in the expression — ALWAYS use "value" (or "value[N]" for multi-column).

## derive_from is MUTUALLY EXCLUSIVE with generator
A column is EITHER generated (has "generator"+"params") OR derived (has "derive_from"+"expression").
NEVER include both "generator" and "derive_from" in the same column.
When using derive_from, OMIT "generator" and "params" entirely.
derive_from must be column NAME(s), NOT a formula:
  Single source: "derive_from":"cost_price"
  Multi source: "derive_from":["price_per_unit","quantity"]
  WRONG: "derive_from":"quantity * price_per_unit" (this is a formula, not a column name)
  Formula goes in "expression", not in "derive_from".

RIGHT example (derived column):
  {"name":"sale_price","derive_from":"cost_price","expression":"round(value*1.2,2)"}
WRONG example (will be REJECTED):
  {"name":"item_total","generator":"float","params":{"min_value":0},
   "derive_from":"quantity * price_per_unit","expression":"round(value[0]*value[1],2)"}

Rules:
1. SKIP entirely (do NOT include in columns list):
   - PK AUTOINCREMENT columns
   - DEFAULT columns (e.g., created_at DEFAULT CURRENT_TIMESTAMP)
   - GENERATED columns (e.g., item_total GENERATED ALWAYS AS (...) STORED)
     GENERATED columns are computed by the database — NEVER generate or derive them.
   - Foreign-key columns (auto-resolved by core)
2. UNIQUE cols -> "constraints":{"unique":true}. Use template generator for UNIQUE codes.
3. *_code/*_no/sku -> template generator with table-specific prefix
   (MER-, PROD-, ITEM-, ORD-, CAT-, USER-). Template MUST contain {sequence:04d}.
   NEVER use literal "PREFIX" or "XXXX" — use {sequence} placeholder.
4. Enum CHECK (col IN ('a','b')) -> weighted_choice with weighted_choices.
   CRITICAL: The keys in weighted_choices MUST match the EXACT values from the CHECK IN
   constraint. Read the schema's CHECK constraint to get valid values.
   Example: CHECK(role IN ('admin','manager','staff')) -> weighted_choices:{"admin":50,"manager":30,"staff":20}
   WRONG: using 'active'/'suspended'/'closed' when the CHECK values are 'admin'/'manager'/'staff'.
5. Cross-col CHECK (price2>=price1) -> ALWAYS use derive_from + expression returning VALUE.
   NEVER generate both columns independently — independent random values WILL violate the CHECK.
   RIGHT: {"name":"sale_price","derive_from":"cost_price","expression":"round(value*1.2,2)"}.
   If sale_price has CHECK(sale_price >= cost_price), sale_price MUST derive from cost_price.
6. Multi-col CHECK (discount<=price_per_unit) -> derive_from as LIST of column names:
   {"derive_from":["price_per_unit","quantity"],"expression":"round(value[0]*0.05*min(value[1],5)/5,2)"}.
7. Cross-table sync (B=A.col for FK) -> derive_from + lookup('A','col',value).
8. *_name non-person -> word; merchant_name -> company; username -> template.
9. phone -> pattern generator with params={"regex":"^[0-9]{3}-[0-9]{3}-[0-9]{4}$"}.
   Do NOT use "string" with "expression" for phone.
10. string params: min_length+max_length (NOT "length").
11. expression MUST RETURN A VALUE, NOT a boolean.
12. NEVER skip a table. Always provide config for all non-skipped columns.
13. Never use "foreign_key" generator (FK cols are skipped).
14. email columns -> use "email" generator (NOT "string").

Generator selection by column name:
- *_name non-person (category_name, product_name, item_name) -> word (readable words, NOT string)
- merchant_name / company_name -> company (company names, NOT text/sentence)
- *_email / email -> email (valid email format, NOT string)
- *_phone / phone -> phone or pattern(regex) (phone format, NOT string)
- *_code / *_no / sku -> template (UNIQUE business codes with sequence)
- *_status / role -> weighted_choice (enum with realistic distribution, NOT choice)
- *_price / *_amount -> float with precision=2 (monetary values)
- *_count / quantity* -> integer with max_value (avoid absurdly large numbers)

Output format (MUST wrap in "tables" list):
{"tables":[{"name":"<table>","count":1000,"columns":[
  {"name":"col","generator":"type","params":{},"constraints":{"unique":false},
   "derive_from":null,"expression":null},
  {"name":"derived_col","derive_from":["src1","src2"],"expression":"round(value[0]+value[1],2)"}
]}]}
Output ONLY raw JSON. No markdown, no explanation."""

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
                    lines.append(f"- {table}.{fk.column} -> {fk.ref_table}.{fk.ref_column}")
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

            uniques = schema.get("unique_indexes", [])
            if uniques:
                lines.append("UNIQUE Indexes (set constraints.unique=true for these columns):")
                for u in uniques:
                    cols_str = ", ".join(u.get("columns", []))
                    lines.append(f"  - UNIQUE ({cols_str})")
            lines.append("")

        lines.append("## Task")
        lines.append(
            "Generate the JSON config for TARGET tables only. "
            "Use CONTEXT tables to understand relationships and business semantics."
        )
        return "\n".join(lines)

    def _call_llm(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Call LLM via SchemaAnalyzer and return parsed config dict.

        Delegates to existing SchemaAnalyzer._call_llm_once for actual
        API call, model fallback, and JSON parsing.

        Retries up to 2 times on empty response (small models like Gemma 4
        E2B sometimes return empty content or unparsable text on the first
        call due to non-determinism). A response is considered empty if it
        has no ``tables`` key and no ``name`` key.
        """
        max_attempts = 5  # 1 initial + 4 retries (Gemma 4 E2B is non-deterministic)
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                result: dict[str, Any] | None = self._analyzer._call_llm_once(
                    messages, stage="legacy_single_shot", table_name="(multi_table)"
                )
                if result is None:
                    result = {}
                # Check if result is non-empty (has tables or name)
                if isinstance(result, dict) and (result.get("tables") or result.get("name")):
                    return result
                # Empty response — retry if attempts remain
                if attempt < max_attempts:
                    logger.warning(
                        "LLM returned empty config, retrying",
                        attempt=attempt,
                        max_attempts=max_attempts,
                    )
                    continue
                return result
            except (ValueError, RuntimeError, OSError) as e:
                last_error = e
                if attempt < max_attempts:
                    logger.warning(
                        "LLM call failed, retrying",
                        attempt=attempt,
                        max_attempts=max_attempts,
                        error=str(e)[:200],
                    )
                    continue
                logger.error("LLM call failed in SchemaSemanticAnalyzer", error=str(e))
                raise
        # Should not reach here, but just in case
        if last_error is not None:
            raise last_error
        return {}

    def _auto_fix_config(
        self,
        config: dict[str, Any],
        schema: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Auto-fix common LLM mistakes (delegates to public function).

        P3 #5 fix: delegates to apply_auto_fix_rules_1_13() public function.
        Preserved for backward compatibility.

        Also applies Rule #14 (strip invalid generator params) to ensure LLM-
        returned params like email's ``min_length``/``example`` are stripped
        before validation. Without this, the non-staged path (used by
        ``ai-suggest`` without ``--staged-pipeline``) crashes with
        ``ConfigurationError`` on invalid params. The staged path applies
        Rule #14 separately in ``Stage3Validator.validate()`` and is not
        affected by this call (it does not route through ``_auto_fix_config``).
        """
        config = apply_auto_fix_rules_1_13(config, schema)
        # Apply Rule #14: strip invalid generator params (e.g., email's
        # min_length/example) that LLMs sometimes hallucinate.
        # Lazy import to avoid circular dependency at module load time.
        from sqlseed_ai.staged_analyzer import Stage3Validator

        validator = Stage3Validator()
        if "tables" in config:
            tables = config["tables"]
        elif "name" in config:
            tables = [config]
        else:
            return config
        for table in tables:
            if not isinstance(table, dict):
                continue
            for col in table.get("columns", []):
                if isinstance(col, dict):
                    validator._apply_rule_14_strip_invalid_params(col)
        return config

    def _filter_to_targets(self, config_dict: dict[str, Any], target_tables: list[str]) -> dict[str, Any]:
        """Ensure config only contains target tables (not context)."""
        if "tables" not in config_dict:
            return config_dict
        target_set = set(target_tables)
        config_dict["tables"] = [t for t in config_dict["tables"] if t.get("name") in target_set]
        return config_dict
