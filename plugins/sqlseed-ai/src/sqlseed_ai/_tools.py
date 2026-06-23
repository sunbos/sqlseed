"""Gemma 4 native function calling tool definitions.

This module defines the OpenAI-style tool schemas consumed by Gemma 4's
native function calling capability. When the backend supports tool use,
:class:`SchemaAnalyzer` passes these definitions to the model so it can
return a structured ``analyze_schema`` invocation instead of free-form JSON.
"""

from __future__ import annotations

from typing import Any

GEMMA_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "type": "function",
        "function": {
            "name": "analyze_schema",
            "description": (
                "Analyze a database table schema and recommend data generation configuration. "
                "Use this tool to examine table structure, column types, constraints, and foreign keys, "
                "then produce a complete sqlseed JSON configuration for generating realistic test data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Name of the table to analyze",
                    },
                    "columns": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Column name"},
                                "type": {"type": "string", "description": "Column SQL type"},
                                "is_primary_key": {"type": "boolean", "description": "Whether column is primary key"},
                                "is_autoincrement": {
                                    "type": "boolean",
                                    "description": "Whether column auto-increments",
                                },
                                "nullable": {"type": "boolean", "description": "Whether column is nullable"},
                                "default": {"type": "string", "description": "Default value if any"},
                            },
                            "required": ["name", "type"],
                        },
                        "description": "List of column definitions in the table",
                    },
                    "foreign_keys": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "ref_table": {"type": "string"},
                                "ref_column": {"type": "string"},
                            },
                        },
                        "description": "Foreign key relationships",
                    },
                    "indexes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "columns": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "unique": {"type": "boolean"},
                            },
                        },
                        "description": "Table indexes",
                    },
                },
                "required": ["table_name", "columns"],
            },
        },
    },
)
