"""Init discovery and config execution must resolve the same literal SQLite file."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from sqlseed.config.loader import load_config, save_config
from sqlseed.config.models import ColumnConfig, ProviderType


@pytest.mark.parametrize(
    ("kind", "suffix"),
    [
        ("absolute-question", ".yaml"),
        ("absolute-question-missing", ".yaml"),
        ("relative-question", ".JSON"),
        ("literal-percent", ".YML"),
        ("uri-question", ".json"),
        ("uri-percent", ".yaml"),
        ("plain-unicode", ".json"),
    ],
)
def test_init_config_roundtrip(tmp_path: Path, kind: str, suffix: str) -> None:
    if os.name == "nt" and "question" in kind:
        pytest.skip("Question marks in literal filenames require a supporting filesystem")
    if "question" in kind:
        filename, other_filename = "项目.sqlite?备份", "项目.sqlite"
    elif "percent" in kind:
        filename, other_filename = "项目%41.sqlite", "项目A.sqlite"
    else:
        filename, other_filename = "项目 数据.sqlite", "其他 数据.sqlite"
    database, other_database = tmp_path / filename, tmp_path / other_filename
    with closing(sqlite3.connect(database)) as connection:
        connection.execute('CREATE TABLE "真实 表" (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)')
        connection.execute('INSERT INTO "真实 表" VALUES (700, ?)', ("原始值",))
        connection.commit()
    has_other = not kind.endswith("-missing")
    if has_other:
        with closing(sqlite3.connect(other_database)) as connection:
            connection.execute('CREATE TABLE "其他 表" (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            connection.execute('INSERT INTO "其他 表" VALUES (900, ?)', ("旁边的文件",))
            connection.commit()
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (database, other_database)
        if path.is_file()
    }
    observations = {
        "before_sha256": {str(path): digest for path, digest in before.items()},
        "before_rows": {str(database): [[700, "原始值"]]},
    }
    if has_other:
        observations["before_rows"][str(other_database)] = [[900, "旁边的文件"]]

    def observe(stage: str) -> None:
        observations[f"{stage}_sha256"] = {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (database, other_database)
            if path.is_file()
        }
        (tmp_path / "observations.json").write_text(
            json.dumps(observations, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if kind.startswith("uri-"):
        target = f"sqlite:///{database.as_uri()}?mode=rw&uri=true&timeout=0.2"
        option = "--url"
    else:
        target = filename if kind.startswith("relative-") else str(database)
        option = "--db"
    launcher = shutil.which("sqlseed")
    if launcher is None:
        local = Path(sys.executable).with_name("sqlseed.exe" if os.name == "nt" else "sqlseed")
        if not local.is_file():
            pytest.skip("An installed SQLSeed console entry point is required")
        launcher = str(local)
    env = dict(
        os.environ,
        SQLSEED_CACHE_DIR=str(tmp_path / "cache"),
        SQLSEED_LOG_LEVEL="ERROR",
        PYTHONIOENCODING="utf-8",
    )

    def invoke(label: str, arguments: list[str]) -> None:
        args = [launcher, *arguments]
        result = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, timeout=30)
        (tmp_path / f"{label}.stdout").write_bytes(result.stdout)
        (tmp_path / f"{label}.stderr").write_bytes(result.stderr)
        (tmp_path / f"{label}.json").write_text(
            json.dumps({"args": args, "cwd": str(tmp_path), "returncode": result.returncode}, ensure_ascii=False),
            encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr.decode("utf-8")
        assert "Traceback" not in result.stderr.decode("utf-8")

    config_path = tmp_path / f"配置 文件{suffix}"
    invoke("init", ["init", str(config_path), option, target])
    observe("after_init")
    # Preserve the exact generated document before ordinary user customization.
    (tmp_path / f"generated-template{suffix}").write_bytes(config_path.read_bytes())
    for path, digest in before.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    assert other_database.exists() is has_other
    config = load_config(str(config_path))
    assert config.connection_target == target
    assert config.db_path == (target if option == "--db" else None)
    assert config.url == (target if option == "--url" else None)
    assert [table.name for table in config.tables] == ["真实 表"]
    assert config.tables[0].count == 1000

    # The template's ordinary edits retain its discovered table and connection.
    generated_value = "你好 # ? %41"
    config.provider = ProviderType.BASE
    config.tables[0].count = 2
    config.tables[0].seed = 42
    config.tables[0].columns = [
        ColumnConfig(name="payload", generator="choice", params={"choices": [generated_value]})
    ]
    save_config(config, str(config_path))
    invoke("fill", ["fill", "--config", str(config_path), "--no-ai"])
    observe("after_fill")
    assert other_database.exists() is has_other
    if has_other:
        assert hashlib.sha256(other_database.read_bytes()).hexdigest() == before[other_database]
    with closing(sqlite3.connect(database)) as connection:
        rows = connection.execute('SELECT * FROM "真实 表" ORDER BY id').fetchall()
        assert rows == [(700, "原始值"), (701, generated_value), (702, generated_value)]
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    if has_other:
        with closing(sqlite3.connect(other_database)) as connection:
            assert connection.execute('SELECT * FROM "其他 表"').fetchall() == [(900, "旁边的文件")]
            assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    (tmp_path / "verified-rows.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    assert sorted(path.name for path in tmp_path.iterdir() if path.is_file()) == sorted(
        [
            filename,
            *([other_filename] if has_other else []),
            config_path.name,
            f"generated-template{suffix}",
            "init.stdout",
            "init.stderr",
            "init.json",
            "fill.stdout",
            "fill.stderr",
            "fill.json",
            "verified-rows.json",
            "observations.json",
        ]
    )
