"""Prompt templates for staged LLM analysis.

Spec §6.1: each stage has its own prompt + few-shot examples.
"""

from __future__ import annotations

# Stage 1: structure analysis
# Input: StructuralFeatures (filtered by stage1 relevance) + few-shot
# Output: JSON with tables/fk_graph/topological_order/naming_conventions/complexity

STAGE1_SYSTEM_PROMPT = """You are a database structure analyst. Analyze the schema and produce a JSON structure summary.

Output JSON schema:
{
  "tables": [
    {
      "name": "<table_name>",
      "purpose": "<one-sentence business purpose>",
      "anchor_columns": ["<pk_or_unique_col>", ...],
      "naming_prefix": "<PREFIX-> (4-letter table abbreviation + dash)",
      "complexity": <int: column_count * constraint_count>
    }
  ],
  "fk_graph": [
    {"parent": "<table>", "child": "<table>", "col": "<fk_col>"}
  ],
  "topological_order": ["<table1>", "<table2>", ...],
  "naming_conventions": {"<table>": "<PREFIX->"}
}

Rules:
- naming_prefix: first 4 chars of table name, uppercased, + "-"
- anchor_columns: PK columns + UNIQUE columns (max 3 per table)
- topological_order: FK parents before children
- Respond with ONLY valid JSON, no prose."""

STAGE1_USER_TEMPLATE = """Analyze this database schema (dialect: {dialect}):

Tables:
{tables_summary}

Foreign keys:
{fk_summary}

Produce the JSON structure summary."""

# Stage 2: per_column analysis (single column)
# Input: 1 column constraints + structure summary + cross-column CHECKs
# Output: {column, generator, params, derive_from, expression}

STAGE2_PER_COLUMN_SYSTEM_PROMPT = """You are a database test data engineer. Output JSON config for ONE column only.

Available generators: string(min_length,max_length,charset), integer(min_value,max_value),
float(min_value,max_value,precision), boolean, name, first_name, last_name, username,
email, phone, address, company, city, country, state, zip_code, country_code,
job_title, url, ipv4, uuid, date(start_year,end_year), datetime(start_year,end_year),
timestamp, text(min_length,max_length), sentence, password, word, choice,
json(schema), pattern(regex), template, weighted_choice.

template generator: params={"template":"FORMAT","sequence_start":0,"sequence_step":1}.
  FORMAT MUST contain {sequence} or {random_digits:N} placeholder.
  Use TABLE-SPECIFIC prefix (provided in context), never literal "PREFIX".

Output JSON: {"column":"<name>","generator":"<type>","params":{...},"derive_from":null,"expression":null}

Cross-column CHECK constraints: if this column is bounded by another column,
set "derive_from":["<other_col>"] and "expression":"<formula>" instead of "generator".

Respond with ONLY valid JSON, no prose."""

STAGE2_PER_COLUMN_USER_TEMPLATE = """Analyze column for table "{table_name}" (prefix: {naming_prefix}):

Column:
  name: {column_name}
  type: {column_type}
  nullable: {nullable}
  default: {default}
  is_pk: {is_pk}
  is_autoincrement: {is_autoincrement}
  is_computed: {is_computed}
  is_unique: {is_unique}

Cross-column CHECK constraints in this table:
{cross_column_checks}

Foreign keys in this table:
{foreign_keys}

Produce the JSON column config."""
