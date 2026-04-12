from __future__ import annotations

from sqlseed.core.mapper import GeneratorSpec
from sqlseed.generators.base_provider import BaseProvider
from sqlseed.generators.stream import DataStream


class TestDataStream:
    def test_generate_single_batch(self) -> None:
        specs = {
            "name": GeneratorSpec(generator_name="name"),
            "email": GeneratorSpec(generator_name="email"),
        }
        provider = BaseProvider()
        stream = DataStream(specs, provider, seed=42)
        batches = list(stream.generate(10, batch_size=10))
        assert len(batches) == 1
        assert len(batches[0]) == 10
        assert "name" in batches[0][0]
        assert "email" in batches[0][0]

    def test_generate_multiple_batches(self) -> None:
        specs = {
            "name": GeneratorSpec(generator_name="name"),
        }
        provider = BaseProvider()
        stream = DataStream(specs, provider, seed=42)
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
        provider = BaseProvider()
        stream = DataStream(specs, provider, seed=42)
        batches = list(stream.generate(5, batch_size=5))
        assert "id" not in batches[0][0]
        assert "name" in batches[0][0]

    def test_null_ratio(self) -> None:
        specs = {
            "name": GeneratorSpec(generator_name="name", null_ratio=1.0),
        }
        provider = BaseProvider()
        stream = DataStream(specs, provider, seed=42)
        batches = list(stream.generate(10, batch_size=10))
        assert all(row["name"] is None for row in batches[0])

    def test_seed_reproducibility(self) -> None:
        specs = {
            "name": GeneratorSpec(generator_name="name"),
            "age": GeneratorSpec(generator_name="integer", params={"min_value": 18, "max_value": 65}),
        }
        provider1 = BaseProvider()
        stream1 = DataStream(specs, provider1, seed=42)
        batches1 = list(stream1.generate(5, batch_size=5))

        provider2 = BaseProvider()
        stream2 = DataStream(specs, provider2, seed=42)
        batches2 = list(stream2.generate(5, batch_size=5))

        assert batches1[0] == batches2[0]

    def test_choice_generator(self) -> None:
        specs = {
            "status": GeneratorSpec(
                generator_name="choice",
                params={"choices": [0, 1, 2]},
            ),
        }
        provider = BaseProvider()
        stream = DataStream(specs, provider, seed=42)
        batches = list(stream.generate(10, batch_size=10))
        assert all(row["status"] in [0, 1, 2] for row in batches[0])

    def test_foreign_key_with_ref_values(self) -> None:
        specs = {
            "user_id": GeneratorSpec(
                generator_name="foreign_key",
                params={"_ref_values": [1, 2, 3, 4, 5]},
            ),
        }
        provider = BaseProvider()
        stream = DataStream(specs, provider, seed=42)
        batches = list(stream.generate(10, batch_size=10))
        assert all(row["user_id"] in [1, 2, 3, 4, 5] for row in batches[0])

    def test_foreign_key_without_ref_values(self) -> None:
        specs = {
            "user_id": GeneratorSpec(
                generator_name="foreign_key",
                params={"max_ref": 100},
            ),
        }
        provider = BaseProvider()
        stream = DataStream(specs, provider, seed=42)
        batches = list(stream.generate(5, batch_size=5))
        assert all(isinstance(row["user_id"], int) for row in batches[0])

    def test_generator_with_no_params(self) -> None:
        specs = {
            "active": GeneratorSpec(generator_name="boolean"),
        }
        provider = BaseProvider()
        stream = DataStream(specs, provider, seed=42)
        batches = list(stream.generate(5, batch_size=5))
        assert all(isinstance(row["active"], bool) for row in batches[0])

    def test_fallback_to_string(self) -> None:
        specs = {
            "field": GeneratorSpec(
                generator_name="nonexistent_generator",
                params={"min_length": 5, "max_length": 10},
            ),
        }
        provider = BaseProvider()
        stream = DataStream(specs, provider, seed=42)
        batches = list(stream.generate(5, batch_size=5))
        assert all(5 <= len(row["field"]) <= 10 for row in batches[0])
