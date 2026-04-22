from __future__ import annotations

import pytest

from sqlseed.core.column_dag import ColumnConstraints, ColumnDAG, ColumnNode
from sqlseed.core.constraints import ConstraintSolver
from sqlseed.core.expression import ExpressionEngine
from sqlseed.core.mapper import GeneratorSpec
from sqlseed.generators.base_provider import BaseProvider
from sqlseed.generators.stream import DataStream, UnknownGeneratorError


class TestDataStream:
    def _create_stream(self, specs, seed=42):
        dag = ColumnDAG()
        nodes = dag.build(specs)
        return DataStream(
            dag_nodes=nodes,
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=seed,
        )

    def test_generate_single_batch(self) -> None:
        specs = {
            "name": GeneratorSpec(generator_name="name"),
            "email": GeneratorSpec(generator_name="email"),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(10, batch_size=10))
        assert len(batches) == 1
        assert len(batches[0]) == 10
        assert "name" in batches[0][0]
        assert "email" in batches[0][0]

    def test_generate_multiple_batches(self) -> None:
        specs = {
            "name": GeneratorSpec(generator_name="name"),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(15, batch_size=5))
        assert len(batches) == 3
        assert len(batches[0]) == 5
        assert len(batches[1]) == 5
        assert len(batches[2]) == 5

    def test_skip_autoincrement(self) -> None:
        specs = {
            "id": GeneratorSpec(generator_name="skip"),
            "name": GeneratorSpec(generator_name="name"),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(5, batch_size=5))
        assert "id" not in batches[0][0]
        assert "name" in batches[0][0]

    def test_null_ratio(self) -> None:
        specs = {
            "name": GeneratorSpec(generator_name="name", null_ratio=1.0),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(10, batch_size=10))
        assert all(row["name"] is None for row in batches[0])

    def test_seed_reproducibility(self) -> None:
        specs = {
            "name": GeneratorSpec(generator_name="name"),
            "age": GeneratorSpec(generator_name="integer", params={"min_value": 18, "max_value": 65}),
        }
        stream1 = self._create_stream(specs, seed=42)
        batches1 = list(stream1.generate(5, batch_size=5))

        stream2 = self._create_stream(specs, seed=42)
        batches2 = list(stream2.generate(5, batch_size=5))

        assert batches1[0] == batches2[0]

    def test_choice_generator(self) -> None:
        specs = {
            "status": GeneratorSpec(
                generator_name="choice",
                params={"choices": [0, 1, 2]},
            ),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(10, batch_size=10))
        assert all(row["status"] in {0, 1, 2} for row in batches[0])

    def test_foreign_key_with_ref_values(self) -> None:
        specs = {
            "user_id": GeneratorSpec(
                generator_name="foreign_key",
                params={"_ref_values": [1, 2, 3, 4, 5]},
            ),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(10, batch_size=10))
        assert all(row["user_id"] in {1, 2, 3, 4, 5} for row in batches[0])

    def test_foreign_key_without_ref_values(self) -> None:
        specs = {
            "user_id": GeneratorSpec(
                generator_name="foreign_key",
                params={"max_ref": 100},
            ),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(5, batch_size=5))
        assert all(isinstance(row["user_id"], int) for row in batches[0])

    def test_generator_with_no_params(self) -> None:
        specs = {
            "active": GeneratorSpec(generator_name="boolean"),
        }
        stream = self._create_stream(specs, seed=42)
        batches = list(stream.generate(5, batch_size=5))
        assert all(isinstance(row["active"], bool) for row in batches[0])

    def test_unknown_generator_raises_error(self) -> None:
        specs = {
            "field": GeneratorSpec(
                generator_name="nonexistent_generator",
                params={"min_length": 5, "max_length": 10},
            ),
        }
        stream = self._create_stream(specs, seed=42)
        with pytest.raises(UnknownGeneratorError, match="Unknown generator 'nonexistent_generator'"):
            list(stream.generate(5, batch_size=5))

    def test_generate_with_unique_constraint(self) -> None:
        specs = {
            "code": GeneratorSpec(
                generator_name="string",
                params={"min_length": 8, "max_length": 8, "charset": "alphanumeric"},
            ),
        }
        dag = ColumnDAG()
        nodes = dag.build(specs)
        unique_nodes = []
        for n in nodes:
            if n.name == "code":
                unique_nodes.append(
                    ColumnNode(
                        name=n.name,
                        generator_spec=n.generator_spec,
                        constraints=ColumnConstraints(unique=True, max_retries=100),
                    )
                )
            else:
                unique_nodes.append(n)
        stream = DataStream(
            dag_nodes=unique_nodes,
            provider=BaseProvider(),
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        batches = list(stream.generate(10, batch_size=10))
        codes = [row["code"] for row in batches[0]]
        assert len(codes) == len(set(codes))

    def test_generate_max_retries_exceeded(self) -> None:
        nodes = [
            ColumnNode(
                name="col",
                generator_spec=GeneratorSpec(
                    generator_name="integer",
                    params={"min_value": 1, "max_value": 1},
                ),
                constraints=ColumnConstraints(unique=True, max_retries=2),
            )
        ]
        provider = BaseProvider()
        stream = DataStream(
            dag_nodes=nodes,
            provider=provider,
            expr_engine=ExpressionEngine(),
            constraint_solver=ConstraintSolver(),
            seed=42,
        )
        with pytest.raises(RuntimeError, match="maximum retries"):
            next(stream.generate(3))

    def test_unknown_generator_error_defined(self) -> None:
        err = UnknownGeneratorError("bad_gen", column_name="col_x")
        assert "bad_gen" in str(err)
        assert "col_x" in str(err)
