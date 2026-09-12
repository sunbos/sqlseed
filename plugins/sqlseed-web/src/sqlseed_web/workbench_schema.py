"""Read real schema and signature-derived generator metadata for the workbench.

Only tables in the adapter's default namespace are executable. References to
other namespaces or missing tables remain visible as read-only graph nodes.
Generator metadata describes parameter shapes; it is not a complete validator
for generator-specific rules such as nonempty choices or date boundaries.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import asdict
from datetime import date, datetime, time
from types import UnionType
from typing import TYPE_CHECKING, Any, Literal, Union, get_args, get_origin, get_type_hints

from fastapi.encoders import jsonable_encoder
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlseed.database.sqlalchemy_adapter import SQLAlchemyAdapter
from sqlseed.generators._dispatch import GeneratorDispatchMixin
from sqlseed.generators.base_provider import BaseProvider

from sqlseed_web.sqlite_target import sqlite_target

if TYPE_CHECKING:
    from sqlalchemy.engine.reflection import Inspector

    from sqlseed_web.state import Connection


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _target_identity(conn: Connection) -> tuple[str, str]:
    """Normalize physical targets and omit userinfo and query values from labels."""
    sqlite = sqlite_target(conn.target, conn.conn_id)
    if sqlite is not None:
        return _digest([sqlite.kind, sqlite.value]), sqlite.label
    url = make_url(conn.target)
    dialect = url.get_backend_name()
    host = (url.host or "").lower()
    port = url.port or (5432 if dialect == "postgresql" else None)
    # Query options can affect namespace/routing, so keep them in the opaque
    # hash, excluding authentication. Never expose query values in the label.
    credential_keys = {"user", "username", "password", "passfile", "token", "access_token", "api_key", "secret"}
    options = sorted((key, value) for key, value in url.query.items() if key.lower() not in credential_keys)
    identity = [dialect, host, port, url.database, options]
    label = URL.create(dialect, host=host, port=port, database=url.database).render_as_string()
    return _digest(identity), label


def _refresh_inspector(conn: Connection, adapter: SQLAlchemyAdapter) -> Inspector:
    """Refresh both metadata caches on the existing, serialized connection.

    Core exposes the adapter publicly but has no public reflection refresh API.
    Private cache access is confined here until such an API exists.
    SchemaInferrer delegates directly to the adapter and has no separate cache.
    """
    inspector = adapter._get_inspector()
    inspector.clear_cache()
    adapter._table_cache.clear()
    conn.orchestrator._relation.clear_cache()
    return inspector


def _foreign_keys(inspector: Inspector, table: str, columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve each Inspector constraint as one grouped foreign key."""
    nullability = {column["name"]: column["nullable"] for column in columns}
    keys: list[dict[str, Any]] = []
    for reflected in inspector.get_foreign_keys(table):
        source_columns = list(reflected.get("constrained_columns", []))
        key = {
            "columns": source_columns,
            "ref_table": reflected.get("referred_table", ""),
            "ref_schema": reflected.get("referred_schema"),
            "ref_columns": list(reflected.get("referred_columns", [])),
            # Under MATCH SIMPLE, one nullable member can disable a composite
            # reference. Keep the group rather than inventing individual FKs.
            "nullable": any(nullability.get(column, True) for column in source_columns),
        }
        key["id"] = "fk_" + _digest([table, reflected.get("name"), key, len(keys)])[:20]
        keys.append(key)
    return keys


def _sqlite_rowid_alias(conn: Connection, name: str, primary_key: list[str]) -> str | None:
    """Fallback for older core metadata without explicit rowid-alias facts.

    SQLite stores ordinary, descending-inline and WITHOUT ROWID primary keys
    in an index with origin ``pk``. A sole, exactly INTEGER rowid alias has no
    such index, including the table-level ``PRIMARY KEY(id DESC)`` exception.
    Using PRAGMA metadata avoids misreading keywords in defaults or comments.
    The core still honors explicit generator rules for implicit rowid aliases.
    """
    if len(primary_key) != 1:
        return None
    rows = conn.orchestrator.query(
        "SELECT name FROM pragma_table_info(?) WHERE pk = 1 AND upper(type) = 'INTEGER' "
        "AND NOT EXISTS (SELECT 1 FROM pragma_index_list(?) WHERE origin = 'pk')",
        (name, name),
    )
    return str(rows[0]["name"]) if rows else None


def _table_schema(conn: Connection, adapter: SQLAlchemyAdapter, inspector: Inspector, name: str) -> dict[str, Any]:
    columns = [asdict(column) for column in adapter.get_column_info(name)]
    primary_key = adapter.get_primary_keys(name)
    needs_rowid_fallback = any(column.get("is_rowid_alias") is None for column in columns)
    rowid_alias = (
        _sqlite_rowid_alias(conn, name, primary_key)
        if adapter.dialect.name == "sqlite" and needs_rowid_fallback
        else None
    )
    for column in columns:
        if column.get("is_rowid_alias") is None:
            column["is_rowid_alias"] = column["name"] == rowid_alias
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    indexes = adapter.get_index_info(name)
    for constraint in (*adapter.get_unique_constraints(name), *indexes):
        if constraint.unique and constraint.columns and not getattr(constraint, "is_partial", False):
            unique.setdefault(constraint.columns, {"name": constraint.name, "columns": list(constraint.columns)})
    table: dict[str, Any] = {
        "name": name,
        "columns": columns,
        "primary_key": primary_key,
        "unique_constraints": sorted(unique.values(), key=lambda item: (item["columns"], item["name"])),
        "checks": sorted(
            [{"name": check.name, "expression": check.expression} for check in adapter.get_check_constraints(name)],
            key=lambda item: (item["name"], item["expression"]),
        ),
        "foreign_keys": _foreign_keys(inspector, name, columns),
        "row_count": adapter.get_row_count(name),
        "mapping": {},
    }
    # Preserve conditional facts in the schema hash without turning their
    # predicates into unconditional generation rules or parsing them in Web.
    conditional = [
        {"name": index.name, "columns": list(index.columns), "unique": index.unique, "predicate": index.predicate}
        for index in indexes
        if getattr(index, "is_partial", False)
    ]
    if conditional:
        table["conditional_indexes"] = sorted(conditional, key=lambda item: item["name"])
    try:
        table["mapping"] = {
            column: jsonable_encoder(asdict(spec))
            for column, spec in conn.orchestrator.get_column_mapping(name).items()
        }
    except (RuntimeError, ValueError, KeyError, SQLAlchemyError) as exc:
        # Reflection must remain useful if the mapping resolver cannot handle
        # one table; exception text can contain credentials or sampled values.
        table["mapping_error"] = f"Generator mapping unavailable ({type(exc).__name__})."
    return table


def inspect_connection(conn: Connection) -> dict[str, Any]:
    """Inspect the current default namespace after refreshing cached metadata.

    The caller must hold the registry's connection operation lock so metadata
    refresh cannot race a fill, preview, or connection disposal.
    """
    conn.orchestrator.get_table_names()  # Public API ensures lazy connection.
    adapter = conn.orchestrator.database_adapter
    if not isinstance(adapter, SQLAlchemyAdapter):
        # An unsupported runtime adapter follows the existing RuntimeError API contract.
        raise RuntimeError("The workbench requires a SQLAlchemyAdapter connection.")  # noqa: TRY004
    inspector = _refresh_inspector(conn, adapter)
    table_names = sorted(adapter.get_table_names())
    tables = [_table_schema(conn, adapter, inspector, name) for name in table_names]
    default_schema = inspector.default_schema_name
    nodes = {name: {"id": name, "name": name, "readonly": False} for name in table_names}
    edges: list[dict[str, Any]] = []
    for table in tables:
        for key in table["foreign_keys"]:
            ref_schema = key["ref_schema"]
            local_reference = ref_schema in (None, default_schema) and key["ref_table"] in nodes
            source = key["ref_table"] if local_reference or not ref_schema else f"{ref_schema}.{key['ref_table']}"
            if source not in nodes:
                nodes[source] = {
                    "id": source,
                    "name": key["ref_table"],
                    "schema": ref_schema,
                    "readonly": True,
                }
            edges.append(
                {
                    "id": key["id"],
                    "source": source,
                    "target": table["name"],
                    "sourceColumns": key["ref_columns"],
                    "targetColumns": key["columns"],
                    "nullable": key["nullable"],
                }
            )
    structural_tables = [
        {key: value for key, value in table.items() if key not in {"row_count", "mapping", "mapping_error"}}
        for table in tables
    ]
    target_key, target_label = _target_identity(conn)
    return {
        "schema_hash": _digest([adapter.dialect.name, default_schema, structural_tables]),
        "target_key": target_key,
        "target_label": target_label,
        "dialect": adapter.dialect.name,
        "provider": conn.provider,
        "locale": conn.locale,
        "tables": tables,
        "nodes": list(nodes.values()),
        "edges": edges,
    }


def _annotation_type(annotation: Any) -> str:
    """Map annotations to UI input shapes without claiming semantic validation."""
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        types = {_annotation_type(item) for item in get_args(annotation) if item is not type(None)}
        return next(iter(types)) if len(types) == 1 else "json"
    if origin is Literal:
        types = {_annotation_type(type(item)) for item in get_args(annotation)}
        return next(iter(types)) if len(types) == 1 else "json"
    if origin in (list, tuple, set):
        return "array"
    if origin is dict:
        return "object"
    return {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        bytes: "bytes",
        date: "date",
        datetime: "datetime",
        time: "time",
        type(None): "null",
    }.get(annotation, "json")


def generator_catalog() -> dict[str, Any]:
    """Describe actual dispatch methods; skip/FK remain separate column modes."""
    names = sorted(GeneratorDispatchMixin.GENERATOR_MAP)
    params_by_name: dict[str, list[str]] = {}
    entries: list[dict[str, Any]] = []
    for name in names:
        method = getattr(BaseProvider, GeneratorDispatchMixin.GENERATOR_MAP[name])
        signature = inspect.signature(method)
        annotations = get_type_hints(method)
        params: list[dict[str, Any]] = []
        for parameter in signature.parameters.values():
            if parameter.name == "self" or parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
                continue
            annotation = annotations.get(parameter.name, Any)
            required = parameter.default is inspect.Parameter.empty
            param = {
                "name": parameter.name,
                "type": _annotation_type(annotation),
                "required": required,
                "default": None if required else jsonable_encoder(parameter.default),
            }
            if get_origin(annotation) is Literal:
                param["choices"] = list(get_args(annotation))
            params.append(param)
        params_by_name[name] = [parameter["name"] for parameter in params]
        entries.append(
            {
                "id": name,
                "label": name.replace("_", " "),
                "params": params,
                "output_type": _annotation_type(annotations.get("return", Any)),
                "description": (inspect.getdoc(method) or "").split("\n\n", 1)[0].replace("\n", " "),
            }
        )
    return {"names": names, "params": params_by_name, "entries": entries}
