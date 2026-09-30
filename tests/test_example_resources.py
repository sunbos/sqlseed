"""Tutorial databases and complete offline notebooks release their resources."""

from __future__ import annotations

import gc
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from examples import build_demo_db
from tests.sqlite_helpers import sqlite_connection

_NOTEBOOKS = Path(__file__).resolve().parents[1] / "examples" / "notebooks"
_OFFLINE_RUNNER = r"""
import gc
import json
import os
import sys
from pathlib import Path

unraisable = []
network_attempts = []
sys.unraisablehook = lambda event: unraisable.append(
    f"{event.exc_type.__name__}: {event.exc_value}"
)

def reject_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        network_attempts.append(event)
        raise RuntimeError("Offline notebook attempted network access")

sys.addaudithook(reject_network)
notebook = Path(sys.argv[1])
document = json.loads(notebook.read_text(encoding="utf-8"))
original_cache = os.environ.get("SQLSEED_CACHE_DIR")
namespace = {"__name__": "__main__"}
executed = 0
for index, cell in enumerate(document["cells"]):
    if cell["cell_type"] == "code":
        source = "".join(cell["source"])
        exec(compile(source, f"{notebook.name}:cell-{index}", "exec"), namespace)
        executed += 1
        gc.collect()

temporary_root = namespace.get("work_dir", namespace.get("demo_root"))
if temporary_root is None or temporary_root.exists():
    raise RuntimeError("Notebook did not remove its temporary directory")
if os.environ.get("SQLSEED_CACHE_DIR") != original_cache:
    raise RuntimeError("Notebook did not restore the previous cache setting")
if namespace.get("RUN_LIVE_AI", False):
    raise RuntimeError("Live AI must stay disabled during offline validation")
namespace.clear()
gc.collect()
if unraisable:
    raise RuntimeError(f"Unraisable exceptions: {unraisable}")
if network_attempts:
    raise RuntimeError(f"Network attempts: {network_attempts}")
print(f"RESOURCE CHECK: {executed} code cells; directory removed; unraisable=0; network=0")
"""


def test_demo_schema_create_repair_and_existing_database_close(tmp_path: Path) -> None:
    """Both creation paths and the early return leave a usable, unlocked database."""
    database = tmp_path / "demo.db"
    assert build_demo_db.ensure_db(database) == database
    with sqlite_connection(database) as connection:
        connection.execute("INSERT INTO tags(name) VALUES ('preserved')")
        connection.execute("DROP TABLE attachments")
    assert build_demo_db.ensure_db(database) == database
    assert build_demo_db.ensure_db(database) == database
    gc.collect()
    moved = database.with_name("repaired.db")
    database.rename(moved)
    with sqlite_connection(moved) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "attachments" in tables
        assert connection.execute("SELECT name FROM tags").fetchall() == [("preserved",)]
    moved.unlink()
    assert not moved.exists()


def test_demo_build_closes_before_replacing_database(tmp_path: Path) -> None:
    database = tmp_path / "demo.db"
    build_demo_db.build(database)
    with sqlite_connection(database) as connection:
        connection.execute("INSERT INTO tags(name) VALUES ('discarded')")
    build_demo_db.build(database)
    gc.collect()
    with sqlite_connection(database) as connection:
        assert connection.execute("SELECT name FROM tags").fetchall() == []
    database.unlink()
    assert not database.exists()


@pytest.mark.parametrize("operation", [build_demo_db.build, build_demo_db.ensure_db])
def test_demo_schema_error_closes_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation) -> None:
    database = tmp_path / "invalid-schema.db"
    monkeypatch.setattr(
        build_demo_db,
        "SCHEMA_SQL",
        "BEGIN; CREATE TABLE partial (value TEXT); INSERT INTO partial VALUES ('uncommitted'); CREATE TABLE broken (",
    )
    with pytest.raises(sqlite3.OperationalError, match="incomplete input"):
        operation(database)
    gc.collect()
    with sqlite_connection(database) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    database.unlink()
    assert not database.exists()


@pytest.mark.parametrize(
    "name",
    ["06-config-deep-dive", "07-ai-plugin", "09-plugin-hooks", "12-testing-patterns"],
)
def test_offline_notebook_releases_all_resources(name: str, tmp_path: Path) -> None:
    """Execute the real cells, including result checks, cleanup, and forced GC."""
    pytest.importorskip("sqlseed_cli")
    pytest.importorskip("sqlseed_ai")
    pytest.importorskip("mimesis")
    environment = os.environ.copy()
    environment.update(
        PYTHONUTF8="1",
        PYTHONWARNINGS="error::ResourceWarning",
        SQLSEED_NOTEBOOK_LIVE_AI="0",
        SQLSEED_CACHE_DIR=str(tmp_path / "original-cache"),
        TEMP=str(tmp_path),
        TMP=str(tmp_path),
    )
    completed = subprocess.run(
        [sys.executable, "-c", _OFFLINE_RUNNER, str(_NOTEBOOKS / f"{name}.ipynb")],
        cwd=_NOTEBOOKS,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )
    print(completed.stdout)
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert "directory removed; unraisable=0; network=0" in completed.stdout
    assert not list(tmp_path.glob("sqlseed-notebook-*"))
