from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, ClassVar

from sqlseed._utils.logger import get_logger
from sqlseed._utils.metrics import MetricsCollector
from sqlseed._utils.progress import create_progress
from sqlseed.core.column_dag import ColumnDAG
from sqlseed.core.constraints import ConstraintSolver
from sqlseed.core.expression import ExpressionEngine
from sqlseed.core.mapper import ColumnMapper, GeneratorSpec
from sqlseed.core.relation import RelationResolver, SharedPool
from sqlseed.core.result import GenerationResult
from sqlseed.core.schema import SchemaInferrer
from sqlseed.core.transform import load_transform
from sqlseed.database.raw_sqlite_adapter import RawSQLiteAdapter
from sqlseed.database.sqlite_utils_adapter import SQLiteUtilsAdapter
from sqlseed.generators.registry import ProviderRegistry
from sqlseed.generators.stream import DataStream
from sqlseed.plugins.manager import PluginManager

if TYPE_CHECKING:
    from sqlseed.database._protocol import DatabaseAdapter

logger = get_logger(__name__)


class DataOrchestrator:
    def __init__(
        self,
        db_path: str,
        *,
        provider_name: str = "mimesis",
        locale: str = "en_US",
        optimize_pragma: bool = True,
    ) -> None:
        self._db_path = db_path
        self._provider_name = provider_name
        self._locale = locale
        self._optimize_pragma = optimize_pragma

        self._db: DatabaseAdapter = self._create_adapter()
        self._schema = SchemaInferrer(self._db)
        self._mapper = ColumnMapper()
        self._relation = RelationResolver(self._db)
        self._registry = ProviderRegistry()
        self._metrics = MetricsCollector()
        self._plugins = PluginManager()
        self._shared_pool = SharedPool()

        self._connected = False

    def _create_adapter(self) -> DatabaseAdapter:
        try:
            import sqlite_utils  # noqa: F401
        except ImportError:
            logger.debug("sqlite-utils not available, falling back to raw sqlite3")
            return RawSQLiteAdapter()
        return SQLiteUtilsAdapter()

    def _ensure_connected(self) -> None:
        if not self._connected:
            self._db.connect(self._db_path)
            self._connected = True
            self._plugins.load_plugins()
            self._plugins.hook.sqlseed_register_providers(registry=self._registry)
            self._plugins.hook.sqlseed_register_column_mappers(mapper=self._mapper)
            self._registry.register_from_entry_points()
            try:
                provider = self._registry.ensure_provider(self._provider_name)
                self._registry.set_default(self._provider_name)
            except (ImportError, ValueError):
                logger.warning(
                    "Provider not available, falling back to 'base'",
                    provider_name=self._provider_name,
                )
                self._provider_name = "base"
            provider = self._registry.get(self._provider_name)
            provider.set_locale(self._locale)

    def fill_table(
        self,
        table_name: str,
        *,
        count: int = 1000,
        columns: dict[str, Any] | None = None,
        seed: int | None = None,
        batch_size: int = 5000,
        clear_before: bool = False,
        column_configs: list[Any] | None = None,
        transform: str | None = None,
    ) -> GenerationResult:
        self._ensure_connected()
        start_time = time.monotonic()
        total_inserted = 0
        batch_count = 0

        try:
            if self._optimize_pragma:
                self._db.optimize_for_bulk_write(count)

            if clear_before:
                self._db.clear_table(table_name)

            column_infos = self._schema.get_column_info(table_name)
            user_configs = self._resolve_user_configs(columns, column_configs)
            generator_specs = self._mapper.map_columns(column_infos, user_configs)
            generator_specs = self._resolve_foreign_keys(table_name, generator_specs)
            generator_specs = self._apply_ai_suggestions(table_name, column_infos, generator_specs)
            generator_specs = self._apply_template_pool(table_name, column_infos, generator_specs, count)

            dag = ColumnDAG()
            col_configs_list = list(user_configs.values()) if user_configs else None
            dag_nodes = dag.build(generator_specs, col_configs_list)

            expr_engine = ExpressionEngine()
            constraint_solver = ConstraintSolver()

            transform_fn = None
            if transform:
                transform_fn = load_transform(transform)

            provider = self._registry.get(self._provider_name)

            self._plugins.hook.sqlseed_before_generate(
                table_name=table_name,
                count=count,
                config=None,
            )

            stream = DataStream(
                dag_nodes=dag_nodes,
                provider=provider,
                expr_engine=expr_engine,
                constraint_solver=constraint_solver,
                transform_fn=transform_fn,
                seed=seed,
            )

            progress = create_progress()
            with progress:
                task_id = progress.add_task(f"Generating {table_name}", total=count)
                for batch in stream.generate(count, batch_size):
                    batch_count += 1

                    self._plugins.hook.sqlseed_before_insert(
                        table_name=table_name,
                        batch_number=batch_count,
                        batch_size=len(batch),
                    )

                    current_batch = self._apply_batch_transforms(table_name, batch)

                    inserted = self._db.batch_insert(table_name, iter(current_batch), batch_size)
                    total_inserted += inserted

                    self._metrics.record(f"{table_name}.batch_insert", float(inserted))

                    self._plugins.hook.sqlseed_after_insert(
                        table_name=table_name,
                        batch_number=batch_count,
                        rows_inserted=inserted,
                    )

                    progress.update(task_id, advance=len(batch))

        except Exception as e:
            logger.error("Failed to fill table", table_name=table_name, error=e)
            return GenerationResult(
                table_name=table_name,
                count=total_inserted,
                elapsed=time.monotonic() - start_time,
                errors=[str(e)],
            )
        finally:
            if self._optimize_pragma:
                self._db.restore_settings()

        elapsed = time.monotonic() - start_time

        self._metrics.record(f"{table_name}.total_elapsed", elapsed)
        self._metrics.record(f"{table_name}.total_rows", float(total_inserted))

        self._plugins.hook.sqlseed_after_generate(
            table_name=table_name,
            count=total_inserted,
            elapsed=elapsed,
        )

        self._register_shared_pool(table_name, generator_specs)

        return GenerationResult(
            table_name=table_name,
            count=total_inserted,
            elapsed=elapsed,
            batch_count=batch_count,
        )

    def preview_table(
        self,
        table_name: str,
        *,
        count: int = 5,
        columns: dict[str, Any] | None = None,
        seed: int | None = None,
        transform: str | None = None,
        column_configs: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_connected()

        column_infos = self._schema.get_column_info(table_name)
        user_configs = self._resolve_user_configs(columns, column_configs)
        generator_specs = self._mapper.map_columns(column_infos, user_configs)
        generator_specs = self._resolve_foreign_keys(table_name, generator_specs)

        dag = ColumnDAG()
        col_configs_list = list(user_configs.values()) if user_configs else None
        dag_nodes = dag.build(generator_specs, col_configs_list)

        expr_engine = ExpressionEngine()
        constraint_solver = ConstraintSolver()

        transform_fn = None
        if transform:
            transform_fn = load_transform(transform)

        provider = self._registry.get(self._provider_name)

        stream = DataStream(
            dag_nodes=dag_nodes,
            provider=provider,
            expr_engine=expr_engine,
            constraint_solver=constraint_solver,
            transform_fn=transform_fn,
            seed=seed,
        )
        result: list[dict[str, Any]] = []
        for batch in stream.generate(count, batch_size=count):
            current_batch = self._apply_batch_transforms(table_name, batch)
            result.extend(current_batch)
        return result

    def get_schema_context(self, table_name: str) -> dict[str, Any]:
        self._ensure_connected()
        column_infos = self._schema.get_column_info(table_name)
        fks = self._db.get_foreign_keys(table_name)
        all_tables = self._db.get_table_names()

        indexes: list[dict[str, Any]] = []
        try:
            idx_infos = self._schema.get_index_info(table_name)
            indexes = [
                {"name": idx.name, "columns": idx.columns, "unique": idx.unique}
                for idx in idx_infos
            ]
        except Exception:
            pass

        sample_data: list[dict[str, Any]] = []
        try:
            sample_data = self._schema.get_sample_data(table_name, limit=5)
        except Exception:
            pass

        distribution: list[dict[str, Any]] = []
        try:
            distribution = self._schema.profile_column_distribution(table_name, limit=1000)
        except Exception:
            pass

        return {
            "table_name": table_name,
            "columns": column_infos,
            "foreign_keys": fks,
            "indexes": indexes,
            "sample_data": sample_data,
            "all_table_names": all_tables,
            "distribution": distribution,
        }

    def get_column_names(self, table_name: str) -> set[str]:
        self._ensure_connected()
        return {c.name for c in self._schema.get_column_info(table_name)}

    def get_skippable_columns(self, table_name: str) -> set[str]:
        self._ensure_connected()
        return {
            c.name for c in self._schema.get_column_info(table_name)
            if (c.is_primary_key and c.is_autoincrement) or c.default is not None
        }

    def report(self) -> str:
        if not self._connected:
            return "Not connected to any database."

        tables = self._db.get_table_names()
        lines = [f"Database: {self._db_path}", "=" * 50]
        for table in tables:
            count = self._db.get_row_count(table)
            lines.append(f"  {table}: {count} rows")
        return "\n".join(lines)

    def _resolve_user_configs(
        self,
        columns: dict[str, Any] | None,
        column_configs: list[Any] | None,
    ) -> dict[str, Any]:
        from sqlseed.config.models import ColumnConfig

        configs: dict[str, Any] = {}

        if column_configs:
            for cc in column_configs:
                if isinstance(cc, ColumnConfig):
                    configs[cc.name] = cc

        if columns:
            for col_name, col_spec in columns.items():
                if isinstance(col_spec, str):
                    configs[col_name] = ColumnConfig(name=col_name, generator=col_spec)
                elif isinstance(col_spec, dict):
                    spec_copy = dict(col_spec)
                    gen_type = spec_copy.pop("type", "string")
                    configs[col_name] = ColumnConfig(
                        name=col_name,
                        generator=gen_type,
                        params=spec_copy,
                    )

        return configs

    def _resolve_foreign_keys(
        self,
        table_name: str,
        specs: dict[str, GeneratorSpec],
    ) -> dict[str, GeneratorSpec]:
        for col_name, spec in specs.items():
            if spec.generator_name == "foreign_key_or_integer":
                fk_info = self._relation.get_fk_info(table_name, col_name)
                if fk_info:
                    ref_values = self._relation.resolve_foreign_key_values(table_name, col_name)
                    new_spec = GeneratorSpec(
                        generator_name="foreign_key",
                        params={
                            "ref_table": fk_info.ref_table,
                            "ref_column": fk_info.ref_column,
                            "strategy": "random",
                            "_ref_values": ref_values,
                        },
                        null_ratio=spec.null_ratio,
                        provider=spec.provider,
                    )
                    specs[col_name] = new_spec
                else:
                    specs[col_name] = GeneratorSpec(
                        generator_name="integer",
                        params={"min_value": 1, "max_value": 999999},
                        null_ratio=spec.null_ratio,
                        provider=spec.provider,
                    )

            elif spec.generator_name == "foreign_key":
                if "ref_table" in spec.params:
                    ref_values = self._db.get_column_values(
                        spec.params["ref_table"],
                        spec.params["ref_column"],
                    )
                    spec.params["_ref_values"] = ref_values

        specs = self._resolve_implicit_associations(table_name, specs)

        return specs

    def _resolve_implicit_associations(
        self,
        table_name: str,
        specs: dict[str, GeneratorSpec],
    ) -> dict[str, GeneratorSpec]:
        """Resolve implicit cross-table associations via SharedPool.

        When a column name exists in the SharedPool (generated by a previously
        filled table), automatically use those values as a foreign_key strategy.
        This handles cases like account_id appearing in multiple tables without
        an explicit FK constraint.
        """
        if not self._shared_pool._pools:
            return specs

        for col_name, spec in list(specs.items()):
            if spec.generator_name != "foreign_key_or_integer":
                continue
            if not self._shared_pool.has(col_name):
                continue

            pool_values = self._shared_pool.get(col_name)
            if not pool_values:
                continue

            specs[col_name] = GeneratorSpec(
                generator_name="foreign_key",
                params={
                    "ref_table": "__shared_pool__",
                    "ref_column": col_name,
                    "strategy": "random",
                    "_ref_values": pool_values,
                },
                null_ratio=spec.null_ratio,
                provider=spec.provider,
            )
            logger.debug(
                "Resolved implicit association via SharedPool",
                table_name=table_name,
                column_name=col_name,
                pool_size=len(pool_values),
            )

        return specs

    AI_APPLICABLE_GENERATORS: ClassVar[frozenset[str]] = frozenset(
        {"string", "integer", "date", "datetime", "choice"}
    )

    def _apply_ai_suggestions(
        self,
        table_name: str,
        column_infos: list[Any],
        specs: dict[str, GeneratorSpec],
    ) -> dict[str, GeneratorSpec]:
        unmatched_cols = [
            col for col in column_infos
            if specs.get(col.name) is not None
            and specs[col.name].generator_name in self.AI_APPLICABLE_GENERATORS
            and not col.is_primary_key
            and not col.is_autoincrement
            and col.default is None
        ]
        if not unmatched_cols:
            return specs

        try:
            fks = self._db.get_foreign_keys(table_name)
            all_tables = self._db.get_table_names()
            indexes = self._schema.get_index_info(table_name)
            sample_data = self._schema.get_sample_data(table_name, limit=5)

            ai_result = self._plugins.hook.sqlseed_ai_analyze_table(
                table_name=table_name,
                columns=column_infos,
                indexes=[{"name": i.name, "columns": i.columns, "unique": i.unique} for i in indexes],
                sample_data=sample_data,
                foreign_keys=fks,
                all_table_names=all_tables,
            )

            if ai_result and isinstance(ai_result, dict):
                ai_columns = ai_result.get("columns", [])
                if isinstance(ai_columns, list):
                    for col_cfg in ai_columns:
                        col_name = col_cfg.get("name") if isinstance(col_cfg, dict) else None
                        if col_name and col_name in specs:
                            gen = col_cfg.get("generator")
                            if gen and gen != "skip":
                                derive_from = col_cfg.get("derive_from")
                                expression = col_cfg.get("expression")

                                if derive_from and expression:
                                    specs[col_name] = GeneratorSpec(
                                        generator_name="__derive__",
                                        params={"derive_from": derive_from, "expression": expression},
                                    )
                                else:
                                    params = col_cfg.get("params", {})
                                    if isinstance(params, dict):
                                        specs[col_name] = GeneratorSpec(
                                            generator_name=gen,
                                            params=params,
                                        )

        except Exception as e:
            logger.debug("AI suggestions not available", table_name=table_name, error=str(e))

        return specs

    def _apply_batch_transforms(
        self,
        table_name: str,
        batch: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        results = self._plugins.hook.sqlseed_transform_batch(
            table_name=table_name,
            batch=batch,
        )
        current = batch
        if results:
            for r in results:
                if r is not None:
                    current = r
        return current

    def _apply_template_pool(
        self,
        table_name: str,
        column_infos: list[Any],
        specs: dict[str, GeneratorSpec],
        count: int,
    ) -> dict[str, GeneratorSpec]:
        for col_name, spec in list(specs.items()):
            if spec.generator_name != "string":
                continue
            col_info = next((c for c in column_infos if c.name == col_name), None)
            if col_info is None or col_info.is_primary_key or col_info.is_autoincrement:
                continue
            if col_info.default is not None:
                continue

            sample_data_for_col: list[Any] = []
            try:
                sample_data_for_col = self._db.get_column_values(table_name, col_name, limit=10)
            except Exception:
                pass

            template_values = self._plugins.hook.sqlseed_pre_generate_templates(
                table_name=table_name,
                column_name=col_name,
                column_type=col_info.type,
                count=min(count, 50),
                sample_data=sample_data_for_col,
            )
            if template_values:
                specs[col_name] = GeneratorSpec(
                    generator_name="foreign_key",
                    params={
                        "ref_table": "__template_pool__",
                        "ref_column": col_name,
                        "strategy": "random",
                        "_ref_values": template_values,
                    },
                )
        return specs

    def _register_shared_pool(
        self,
        table_name: str,
        generator_specs: dict[str, GeneratorSpec],
    ) -> None:
        for col_name, spec in generator_specs.items():
            if spec.generator_name == "skip":
                continue
            try:
                values = self._db.get_column_values(table_name, col_name, limit=10000)
                if values:
                    self._shared_pool.merge(col_name, values)
            except Exception:
                pass

    def fill(
        self,
        table_name: str,
        *,
        count: int = 1000,
        columns: dict[str, Any] | None = None,
        seed: int | None = None,
        batch_size: int = 5000,
        clear_before: bool = False,
        column_configs: list[Any] | None = None,
        transform: str | None = None,
    ) -> GenerationResult:
        return self.fill_table(
            table_name=table_name,
            count=count,
            columns=columns,
            seed=seed,
            batch_size=batch_size,
            clear_before=clear_before,
            column_configs=column_configs,
            transform=transform,
        )

    def close(self) -> None:
        if self._connected:
            self._db.close()
            self._connected = False

    def __enter__(self) -> DataOrchestrator:
        self._ensure_connected()
        return self

    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any) -> None:
        if self._connected:
            self._db.close()
            self._connected = False
