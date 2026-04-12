from __future__ import annotations

import sqlseed
from sqlseed.core.orchestrator import DataOrchestrator
from sqlseed.core.result import GenerationResult


class TestPublicAPI:
    def test_fill(self, tmp_db) -> None:
        result = sqlseed.fill(tmp_db, table="users", count=50, provider="base")
        assert isinstance(result, GenerationResult)
        assert result.count == 50

    def test_fill_with_clear(self, tmp_db) -> None:
        sqlseed.fill(tmp_db, table="users", count=10, provider="base")
        result = sqlseed.fill(tmp_db, table="users", count=20, provider="base", clear_before=True)
        assert result.count == 20

    def test_fill_with_columns(self, tmp_db) -> None:
        result = sqlseed.fill(
            tmp_db,
            table="users",
            count=10,
            columns={"name": "name", "email": "email"},
            provider="base",
        )
        assert result.count == 10

    def test_fill_with_seed(self, tmp_db) -> None:
        result = sqlseed.fill(tmp_db, table="users", count=5, provider="base", seed=42)
        assert result.count == 5

    def test_connect(self, tmp_db) -> None:
        db = sqlseed.connect(tmp_db, provider="base")
        assert isinstance(db, DataOrchestrator)
        db._ensure_connected()
        db.close()

    def test_fill_from_config(self, tmp_db, tmp_path) -> None:
        import yaml

        config_path = tmp_path / "gen.yaml"
        config_data = {
            "db_path": tmp_db,
            "provider": "base",
            "locale": "en_US",
            "tables": [
                {
                    "name": "users",
                    "count": 15,
                    "columns": [
                        {"name": "name", "generator": "name"},
                    ],
                }
            ],
        }
        config_path.write_text(yaml.dump(config_data))
        results = sqlseed.fill_from_config(str(config_path))
        assert len(results) == 1
        assert results[0].count == 15

    def test_preview(self, tmp_db) -> None:
        rows = sqlseed.preview(tmp_db, table="users", count=3, provider="base")
        assert len(rows) == 3
        assert "name" in rows[0]

    def test_preview_with_seed(self, tmp_db) -> None:
        rows1 = sqlseed.preview(tmp_db, table="users", count=5, provider="base", seed=42)
        rows2 = sqlseed.preview(tmp_db, table="users", count=5, provider="base", seed=42)
        assert rows1 == rows2
