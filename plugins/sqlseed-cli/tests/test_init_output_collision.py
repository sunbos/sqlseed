"""A configuration destination must not truncate its referenced SQLite data."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

import pytest

from sqlseed.config.loader import generate_template, load_config, save_config
from sqlseed.config.models import GeneratorConfig


def fixture_db(path: Path) -> bytes:
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE sentinel(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO sentinel VALUES(1, 'synthetic retained value')")
        conn.commit()
    return path.read_bytes()


def unchanged(path: Path, before: bytes) -> None:
    assert path.read_bytes() == before
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT * FROM sentinel").fetchall() == [(1, "synthetic retained value")]
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def target_args(kind: str, db: Path) -> list[str]:
    if kind == "uri":
        return ["--url", f'sqlite:///file:{quote(str(db))}?mode=ro&uri=true']
    if kind == "url":
        return ["--url", f'sqlite:///{db}']
    return ["--db", str(db)]


def run_console(
    tmp_path: Path, label: str, output: Path, args: list[str]
) -> subprocess.CompletedProcess[str]:
    argv = [str(Path(sys.executable).parent / "sqlseed"), "init", str(output), *args]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30, env=os.environ.copy())
    record = {"argv": argv, "exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    (tmp_path / f'{label}.json').write_text(json.dumps(record, indent=2))
    return result


@pytest.mark.parametrize(
    "kind",
    [
        "literal", "url", "uri", "normalized", "symlink", "hardlink",
        "literal-question", "literal-percent", "url-percent",
    ],
)
def test_console_rejects_collision_then_accepts_distinct_retry(tmp_path: Path, kind: str) -> None:
    if kind == "literal-question" and os.name == "nt":
        pytest.skip("Windows filenames cannot contain a question mark")
    name = {
        "literal-question": "data?backup.json",
        "literal-percent": "data%20backup.json",
        "url-percent": "data%20backup.json",
    }.get(kind, "数据库 file.json")
    db = tmp_path / name
    before = fixture_db(db)
    (tmp_path / "original.sqlite").write_bytes(before)
    output = db
    if kind in {"symlink", "hardlink"}:
        output = tmp_path / "alias.yaml"
        try:
            if kind == "symlink":
                output.symlink_to(db)
            else:
                os.link(db, output)
        except OSError as exc:
            pytest.skip(f'Filesystem link unavailable: {exc}')
        assert output.samefile(db)
    if kind == "normalized":
        (tmp_path / "sub").mkdir()
        output = tmp_path / "sub" / ".." / db.name
    args = target_args("url" if kind == "url-percent" else kind, db)
    result = run_console(tmp_path, "reject", output, args)
    unchanged(db, before)
    assert result.returncode == 2
    assert "choose a different output path" in result.stderr
    assert "saved to" not in result.stdout
    distinct = tmp_path / "config.json"
    distinct.write_text("old config")
    retry = run_console(tmp_path, "retry", distinct, args)
    assert retry.returncode == 0, retry.stderr
    assert [table.name for table in load_config(str(distinct)).tables] == ["sentinel"]
    unchanged(db, before)


@pytest.mark.parametrize("kind", ["literal", "url", "uri"])
def test_save_api_preserves_database(tmp_path: Path, kind: str) -> None:
    db = tmp_path / "source.json"
    before = fixture_db(db)
    args = target_args(kind, db)
    config = generate_template(**({"url": args[1]} if args[0] == "--url" else {"db_path": args[1]}))
    with pytest.raises(ValueError, match="choose a different output path"):
        save_config(config, str(db))
    unchanged(db, before)


@pytest.mark.parametrize(
    "target",
    [
        ":memory:",
        "sqlite:///:memory:",
        "sqlite:///file:memory.json?mode=memory&cache=shared&uri=true",
        "postgresql://localhost/example",
    ],
)
def test_save_nonfile_targets_still_replaces_config(
    tmp_path: Path, target: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    destination = tmp_path / "memory.json"
    destination.write_text("old configuration")
    config = GeneratorConfig(url=target) if "://" in target else GeneratorConfig(db_path=target)
    save_config(config, str(destination))
    assert load_config(str(destination)) == config


def test_non_uri_percent_filename_does_not_alias_decoded_file(tmp_path: Path) -> None:
    database = tmp_path / "data%20file.json"
    before = fixture_db(database)
    destination = tmp_path / "data file.json"
    destination.write_text("old config")
    config = generate_template(url=f'sqlite:///{database}?uri=false')
    save_config(config, str(destination))
    assert [table.name for table in load_config(str(destination)).tables] == ["sentinel"]
    unchanged(database, before)


@pytest.mark.parametrize("query", ["mode=memory", "mode=memory&mode=memory", "mode=memory%00ignored", "vfs=memdb"])
def test_memory_or_ambiguous_uri_does_not_claim_existing_file(tmp_path: Path, query: str) -> None:
    destination = tmp_path / "existing.json"
    destination.write_text("old config")
    config = GeneratorConfig(url=f'sqlite:///file:{quote(str(destination))}?{query}&uri=true')
    save_config(config, str(destination))
    assert load_config(str(destination)) == config


def test_missing_source_does_not_create_database(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    output = tmp_path / "config.json"
    output.write_text("old config")
    config = GeneratorConfig(db_path=str(missing))
    save_config(config, str(output))
    assert load_config(str(output)) == config
    assert not missing.exists()


@pytest.mark.parametrize("target", ["sqlite:///unready.db?timeout=not-a-number", "sqlite://invalid-host/file.db"])
def test_unresolvable_connection_remains_serializable(tmp_path: Path, target: str) -> None:
    destination = tmp_path / "config.json"
    destination.write_text("old config")
    config = GeneratorConfig(url=target)
    save_config(config, str(destination))
    assert load_config(str(destination)) == config
