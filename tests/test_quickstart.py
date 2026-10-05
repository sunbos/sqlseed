"""Regressions for the repository demo's local installation and environment selection."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType


@pytest.fixture(name="quickstart")
def fixture_quickstart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    script = Path(__file__).resolve().parents[1] / "scripts" / "quickstart.py"
    spec = importlib.util.spec_from_file_location("quickstart", script)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "demo with spaces.db")
    monkeypatch.setattr(sys, "argv", [str(script), "--backend", "google"])
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    return module


def test_install_resolves_all_local_packages_together(
    quickstart: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venv.EnvBuilder(with_pip=False).create(tmp_path / ".venv")
    commands: list[list[str]] = []

    def record_command(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(quickstart, "run", record_command)
    quickstart.main()

    installations = [command for command in commands if command[1:4] == ["-m", "pip", "install"]]
    assert len(installations) == 1
    installation = installations[0]
    local_sources = [installation[index + 1] for index, value in enumerate(installation) if value == "-e"]
    assert set(local_sources) == {
        f"{tmp_path}[mimesis,postgres]",
        str(tmp_path / "plugins" / "sqlseed-cli"),
        f"{tmp_path / 'plugins' / 'sqlseed-ai'}[mcp]",
        str(tmp_path / "plugins" / "mcp-server-sqlseed"),
        str(tmp_path / "plugins" / "sqlseed-web"),
    }
    assert any(command[1:] == ["-m", "pip", "check"] for command in commands)


def test_foreign_environment_is_preserved_and_reports_recreation(
    quickstart: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    environment = tmp_path / ".venv"
    environment.mkdir()
    foreign_python = environment / ("Scripts/python.exe" if os.name != "nt" else "bin/python")
    foreign_python.parent.mkdir()
    foreign_python.write_text("foreign environment", encoding="utf-8")
    monkeypatch.setattr(quickstart, "run", lambda command: subprocess.CompletedProcess(command, 0))

    with pytest.raises(SystemExit) as error:
        quickstart.main()

    assert error.value.code == 1
    assert foreign_python.read_text(encoding="utf-8") == "foreign environment"
    output = capsys.readouterr().out.lower()
    assert "recreate" in output
    assert "virtual environment" in output


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell command round trip")
def test_printed_commands_use_selected_python_and_quote_paths(
    quickstart: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    selected_python = str(tmp_path / "Python with spaces" / "bin" / "python")
    monkeypatch.setattr(sys, "executable", selected_python)
    monkeypatch.setattr(sys, "argv", ["quickstart.py", "--skip-install", "--backend", "google"])
    monkeypatch.setattr(quickstart, "run", lambda command: subprocess.CompletedProcess(command, 0))

    quickstart.main()

    output = capsys.readouterr().out
    preview = next(line.split(":", 1)[1].strip() for line in output.splitlines() if "Preview:" in line)
    assert shlex.split(preview) == [
        selected_python,
        "-c",
        "from sqlseed_cli.main import cli; cli()",
        "--",
        "preview",
        str(quickstart.DB_PATH),
        "-t",
        "users",
        "-n",
        "5",
    ]
    mcp = next(line.split(":", 1)[1].strip() for line in output.splitlines() if "MCP Server:" in line)
    assert shlex.split(mcp) == [selected_python, "-m", "mcp_server_sqlseed"]


@pytest.mark.parametrize(
    ("argument", "literal"),
    [
        (r"C:\a&b\demo.db", r"'C:\a&b\demo.db'"),
        (r"C:\with spaces\demo.db", r"'C:\with spaces\demo.db'"),
        (r"C:\user's\demo.db", r"'C:\user''s\demo.db'"),
        (r"C:\$env:USERPROFILE\demo.db", r"'C:\$env:USERPROFILE\demo.db'"),
        (r"C:\%USERPROFILE%\demo.db", r"'C:\%USERPROFILE%\demo.db'"),
        (r"C:\!USERNAME!\demo.db", r"'C:\!USERNAME!\demo.db'"),
        (
            "C:\\quote\u2018\u2019\u201a\u201b\\demo.db",
            "'C:\\quote\u2018\u2018\u2019\u2019\u201a\u201a\u201b\u201b\\demo.db'",
        ),
    ],
    ids=["ampersand", "space", "apostrophe", "dollar", "percent", "exclamation", "smart-quotes"],
)
def test_windows_command_uses_powershell_literals(
    quickstart: ModuleType, monkeypatch: pytest.MonkeyPatch, argument: str, literal: str
) -> None:
    monkeypatch.setattr(quickstart, "os", SimpleNamespace(name="nt"))
    assert quickstart.shell_command([r"C:\a&b\python.exe", argument]) == f"& 'C:\\a&b\\python.exe' {literal}"


def test_windows_output_identifies_powershell(
    quickstart: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(quickstart, "os", SimpleNamespace(name="nt", environ=os.environ))
    monkeypatch.setattr(sys, "argv", ["quickstart.py", "--skip-install", "--backend", "google"])
    monkeypatch.setattr(quickstart, "run", lambda command: subprocess.CompletedProcess(command, 0))

    quickstart.main()

    assert "Commands below use PowerShell syntax." in capsys.readouterr().out


@pytest.mark.parametrize("shell_name", ["powershell", "pwsh"])
def test_windows_displayed_command_preserves_real_native_arguments(
    quickstart: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell_name: str
) -> None:
    shell = shutil.which(shell_name)
    if shell is None:
        if os.name == "nt" and shell_name == "powershell":
            pytest.fail(f"Windows compatibility tests require {shell_name} on PATH")
        pytest.skip(f"{shell_name} is not installed on this platform")
    monkeypatch.setattr(quickstart, "os", SimpleNamespace(name="nt"))
    echo = tmp_path / "echo & ' $ % ! \u2018\u2019\u201a\u201b argv.py"
    echo.write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
    arguments = [
        r"C:\a&b\demo.db",
        r"C:\with spaces\demo.db",
        r"C:\user's\demo.db",
        r"C:\$env:USERPROFILE\demo.db",
        r"C:\%USERPROFILE%\demo.db",
        r"C:\!USERNAME!\demo.db",
        "C:\\quote\u2018\u2019\u201a\u201b\\demo.db",
    ]
    command = quickstart.shell_command([sys.executable, str(echo), *arguments])
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert json.loads(result.stdout) == arguments
