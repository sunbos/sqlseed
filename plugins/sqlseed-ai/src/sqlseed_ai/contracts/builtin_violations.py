"""Layer 1: Built-in sparse contract violations.

Closed set of known bad (generator, column_type, constraints) combinations.
Default for unlisted combos is COMPATIBLE — gaps are caught by Layer 5
property-based tests in CI.

Spec reference: Section 3.3. Seed entries derived from Rules #24, #26,
#28, #30 (most-validated during Loop 2 regression testing).
"""

from __future__ import annotations

from sqlseed_ai.contracts.matrix import ContractViolation, ViolationKind


def _is_code_like(name: str) -> bool:
    """Heuristic: column name looks like a code/identifier (UNIQUE needs template)."""
    if not name:
        return False
    lower = name.lower()
    suffixes = ("_code", "code", "_id", "sku", "_no", "number", "_key")
    return any(lower.endswith(s) for s in suffixes) or lower in ("code", "sku", "isbn")


BUILTIN_VIOLATIONS: set[ContractViolation] = {
    # === Type compatibility (Rule #30) ===
    ContractViolation(
        generator="integer",
        column_type="TIMESTAMP",
        constraints=frozenset(),
        kind=ViolationKind.CRASH,
        fix_strategy="switch_generator",
        fix_params={"target": "datetime"},
    ),
    ContractViolation(
        generator="integer",
        column_type="DATE",
        constraints=frozenset(),
        kind=ViolationKind.CRASH,
        fix_strategy="switch_generator",
        fix_params={"target": "date"},
    ),
    ContractViolation(
        generator="integer",
        column_type="TEXT",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="switch_generator",
        fix_params={"target": "string"},
    ),
    ContractViolation(
        generator="float",
        column_type="TEXT",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="switch_generator",
        fix_params={"target": "string"},
    ),
    ContractViolation(
        generator="string",
        column_type="INTEGER",
        constraints=frozenset(),
        kind=ViolationKind.CRASH,
        fix_strategy="switch_generator",
        fix_params={"target": "integer"},
    ),
    ContractViolation(
        generator="datetime",
        column_type="INTEGER",
        constraints=frozenset(),
        kind=ViolationKind.CRASH,
        fix_strategy="switch_generator",
        fix_params={"target": "integer"},
    ),
    # === Rule #26: random_float on INTEGER-family column ===
    ContractViolation(
        generator="random_float",
        column_type="INTEGER",
        constraints=frozenset(),
        kind=ViolationKind.CRASH,
        fix_strategy="coerce_float_to_int",
    ),
    ContractViolation(
        generator="random_float",
        column_type="BIGINT",
        constraints=frozenset(),
        kind=ViolationKind.CRASH,
        fix_strategy="coerce_float_to_int",
    ),
    ContractViolation(
        generator="random_float",
        column_type="SMALLINT",
        constraints=frozenset(),
        kind=ViolationKind.CRASH,
        fix_strategy="coerce_float_to_int",
    ),
    ContractViolation(
        generator="random_float",
        column_type="TINYINT",
        constraints=frozenset(),
        kind=ViolationKind.CRASH,
        fix_strategy="coerce_float_to_int",
    ),
    # === Rule #24: UNIQUE code-like columns need template ===
    ContractViolation(
        generator="choice",
        column_type="ANY",
        constraints=frozenset({"UNIQUE"}),
        kind=ViolationKind.UNIQUE_UNSATISFIABLE,
        fix_strategy="upgrade_to_template",
        predicate=lambda cfg: _is_code_like(cfg.get("name", "")),
    ),
    ContractViolation(
        generator="word",
        column_type="ANY",
        constraints=frozenset({"UNIQUE"}),
        kind=ViolationKind.UNIQUE_UNSATISFIABLE,
        fix_strategy="upgrade_to_template",
        predicate=lambda cfg: _is_code_like(cfg.get("name", "")),
    ),
    ContractViolation(
        generator="string",
        column_type="ANY",
        constraints=frozenset({"UNIQUE"}),
        kind=ViolationKind.UNIQUE_UNSATISFIABLE,
        fix_strategy="upgrade_to_template",
        predicate=lambda cfg: _is_code_like(cfg.get("name", "")),
    ),
    # === Rule #28: text/word on semantic columns ===
    ContractViolation(
        generator="text",
        column_type="TEXT",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="semantic_upgrade",
        predicate=lambda cfg: cfg.get("name", "").lower() in ("description", "desc", "comment", "note"),
    ),
    ContractViolation(
        generator="string",
        column_type="TEXT",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="semantic_upgrade",
        predicate=lambda cfg: cfg.get("name", "").lower().endswith("_email") or cfg.get("name", "").lower() == "email",
    ),
    ContractViolation(
        generator="string",
        column_type="TEXT",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="semantic_upgrade",
        predicate=lambda cfg: cfg.get("name", "").lower() in ("phone", "mobile", "telephone", "tel"),
    ),
    # === Cardinality: choice with insufficient pool on UNIQUE ===
    ContractViolation(
        generator="choice",
        column_type="ANY",
        constraints=frozenset({"UNIQUE"}),
        kind=ViolationKind.UNIQUE_UNSATISFIABLE,
        fix_strategy="expand_pool",
        predicate=lambda cfg: cfg.get("pool_size", 0) < cfg.get("row_count", 0),
    ),
    # === Rule #23: phone generator on phone-like column → pattern ===
    ContractViolation(
        generator="phone",
        column_type="ANY",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="upgrade_phone_to_pattern",
        predicate=lambda cfg: cfg.get("name", "").lower()
        in ("phone", "mobile", "telephone", "tel", "cell", "cellphone", "contact_number")
        or cfg.get("name", "").lower().endswith(("_phone", "_mobile", "_tel", "_telephone")),
    ),
    ContractViolation(
        generator="string",
        column_type="ANY",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="upgrade_phone_to_pattern",
        predicate=lambda cfg: cfg.get("name", "").lower()
        in ("phone", "mobile", "telephone", "tel", "cell", "cellphone", "contact_number")
        or cfg.get("name", "").lower().endswith(("_phone", "_mobile", "_tel", "_telephone")),
    ),
    # === Rule #25: text on UNIQUE code-like column → string ===
    ContractViolation(
        generator="text",
        column_type="ANY",
        constraints=frozenset({"UNIQUE"}),
        kind=ViolationKind.UNIQUE_UNSATISFIABLE,
        fix_strategy="downgrade_text_to_string",
        predicate=lambda cfg: _is_code_like(cfg.get("name", "")),
    ),
    # === Rule #18: date/datetime with end_year > current_year+1 ===
    ContractViolation(
        generator="date",
        column_type="ANY",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="cap_future_end_year",
        predicate=lambda cfg: isinstance(cfg.get("params", {}).get("end_year"), int)
        and cfg["params"]["end_year"] > __import__("datetime").datetime.now().year + 1,
    ),
    ContractViolation(
        generator="datetime",
        column_type="ANY",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="cap_future_end_year",
        predicate=lambda cfg: isinstance(cfg.get("params", {}).get("end_year"), int)
        and cfg["params"]["end_year"] > __import__("datetime").datetime.now().year + 1,
    ),
    # === Rule #15: pattern with unbounded regex quantifier {N,} ===
    ContractViolation(
        generator="pattern",
        column_type="ANY",
        constraints=frozenset(),
        kind=ViolationKind.SEMANTIC_ERROR,
        fix_strategy="bound_regex",
        predicate=lambda cfg: __import__("re").search(
            r"\{\d+,\}", str(cfg.get("params", {}).get("regex", ""))
        )
        is not None,
    ),
}
