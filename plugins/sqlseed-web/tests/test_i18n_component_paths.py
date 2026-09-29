"""Localizable component failures preserve admission, isolation and task state."""

from __future__ import annotations

import hashlib
import io
import sys
import threading
import zipfile
from collections.abc import Iterator
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from tests.assertions import assert_empty
from tests.sqlite_helpers import sqlite_connection

from sqlseed_web import plugin_environment as environment
from sqlseed_web import plugin_management as management
from sqlseed_web import plugin_updates as updates
from sqlseed_web.messages import Message, materialize_messages
from sqlseed_web.plugin_process import InstallerCleanupPending
from sqlseed_web.settings_environment import _Installer
from sqlseed_web.state import ConnectionBusyError, UIState, UnknownConnectionError
from sqlseed_web.supervisor import Supervisor
from sqlseed_web.workbench_ai_relations import RelationSuggestion, compile_relation, validate_dags
from sqlseed_web.workbench_schema import inspect_connection


def assert_message(value: object, key: str) -> None:
    assert isinstance(value, Message)
    assert value.key == key
    assert materialize_messages({"message": value})["message_key"] == key


@pytest.fixture(name="isolated_manager")
def fixture_isolated_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    prefix = tmp_path / "venv"
    site = prefix / "site-packages"
    site.mkdir(parents=True)
    (prefix / "pyvenv.cfg").write_text("include-system-site-packages = false\n", encoding="utf-8")

    def install(name: str) -> Path:
        directory = site / f"{name.replace('-', '_')}-1.0.dist-info"
        directory.mkdir()
        path = directory / "METADATA"
        path.write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n", encoding="utf-8")
        return path

    for name in ("sqlseed", "sqlseed-web", "faker"):
        install(name)
    target = environment.Environment(prefix, sys.executable, "pip", None, None)
    monkeypatch.setattr(environment, "_distribution_paths", lambda: [str(site)])
    monkeypatch.setattr(environment, "_environment", lambda: target)

    def unexpected_installer(*args: Any, **kwargs: Any) -> int:
        pytest.fail("A rejected component operation must not reach the installer")

    monkeypatch.setattr(management, "run_installer", unexpected_installer)
    manager = management.PluginManager(enabled=True)
    manager.start()
    try:
        yield manager, install, site
    finally:
        manager.stop()


@pytest.mark.parametrize(
    "action,present,key",
    [
        ("install", True, "this_component_is_already_installed_use_the"),
        ("uninstall", False, "this_component_is_not_installed"),
        ("update", False, "this_component_is_not_installed_install_it"),
    ],
)
def test_invalid_component_transition_cannot_create_a_plan(
    isolated_manager: Any, action: str, present: bool, key: str
) -> None:
    manager, install, _ = isolated_manager
    if present:
        install("mimesis")
    before = environment.installed_packages(manager.environment.prefix)
    request = management.PlanRequest(component_id="mimesis", action=action)
    with pytest.raises(HTTPException) as error:
        manager.plan(request)
    assert error.value.status_code == 409
    assert_message(error.value.detail["message"], "backend.plugin_management." + key)
    assert manager._plan is None
    assert manager._task is None
    assert environment.installed_packages(manager.environment.prefix) == before


def test_cross_site_read_is_rejected_even_with_loopback_and_a_valid_token(isolated_manager: Any) -> None:
    manager = isolated_manager[0]
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "query_string": b"",
            "client": ("127.0.0.1", 40000),
            "server": ("127.0.0.1", 8630),
            "headers": [
                (b"host", b"127.0.0.1:8630"),
                (b"sec-fetch-site", b"cross-site"),
                (b"x-sqlseed-management-token", manager.token.encode()),
            ],
        }
    )
    with pytest.raises(HTTPException) as error:
        management.guard_request(request, manager)
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "plugin_management_forbidden"
    assert manager._plan is None


@pytest.mark.parametrize("enabled", [False, True])
def test_contending_environment_lock_keeps_the_second_service_unavailable(isolated_manager: Any, enabled: bool) -> None:
    owner = isolated_manager[0]
    contender = management.PluginManager(enabled=enabled)
    try:
        if enabled:
            contender.start()
            status = contender.status()
            assert status["available"] is False
            assert_message(
                status["reason"], "backend.plugin_management.cannot_acquire_the_maintenance_lock_check_permissions"
            )
        else:
            with pytest.raises(RuntimeError) as error:
                contender.start()
            assert_message(
                error.value.args[0], "backend.plugin_management.cannot_acquire_the_web_environment_lock_check"
            )
        assert contender._environment_lock is None
        assert owner.status()["available"] is True
    finally:
        contender.stop()


def test_unstarted_and_cleanup_pending_managers_cannot_authorize_operations(isolated_manager: Any) -> None:
    manager = management.PluginManager(enabled=True)
    status = manager.status()
    assert status["available"] is False
    assert_message(status["reason"], "backend.plugin_management.the_maintenance_service_has_not_acquired_the")
    released = threading.Event()
    resources = ExitStack()
    resources.callback(released.set)
    manager._installer_cleanup = InstallerCleanupPending(lambda: None, resources)
    request = management.PlanRequest(component_id="mimesis", action="install")
    with pytest.raises(HTTPException) as error:
        manager.plan(request)
    assert_message(
        error.value.detail["message"], "backend.plugin_management.installer_cleanup_has_not_been_confirmed_the"
    )
    assert manager._plan is None
    manager.stop()
    assert released.is_set()
    assert manager._installer_cleanup is None


def test_unknown_tasks_and_unsupported_recovery_preserve_manager_state(isolated_manager: Any) -> None:
    manager = isolated_manager[0]
    with pytest.raises(HTTPException) as unknown:
        manager.task_snapshot("missing")
    assert unknown.value.status_code == 404
    assert unknown.value.detail["code"] == "plugin_task_not_found"
    with pytest.raises(HTTPException) as recovery:
        manager.recover()
    assert recovery.value.status_code == 409
    assert_message(
        recovery.value.detail["message"], "backend.plugin_management.this_deployment_does_not_support_automatic_service"
    )
    assert manager.status()["available"] is True
    assert manager._task is None


def test_changed_invalid_package_metadata_rejects_execution_before_start(isolated_manager: Any) -> None:
    manager, _, site = isolated_manager
    plan = manager.plan(management.PlanRequest(component_id="mimesis", action="install"))
    (site / "faker-1.0.dist-info" / "METADATA").write_text("Name: invalid@@\nVersion: 1.0\n", encoding="utf-8")
    request = management.ExecuteRequest(plan_id=plan["plan_id"])
    with pytest.raises(HTTPException) as error:
        manager.execute(request)
    assert error.value.status_code == 409
    assert_message(
        error.value.detail["message"], "backend.plugin_environment.installed_package_metadata_cannot_be_safely_parsed"
    )
    assert manager._task is None
    assert manager.restart_required is False


def test_thread_start_failure_publishes_a_terminal_task_without_touching_packages(
    isolated_manager: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = isolated_manager[0]
    before = environment.installed_packages(manager.environment.prefix)
    plan = manager.plan(management.PlanRequest(component_id="mimesis", action="install"))

    def refuse_start(self: threading.Thread) -> None:
        raise RuntimeError("No thread resources")

    monkeypatch.setattr(threading.Thread, "start", refuse_start)
    result = manager.execute(management.ExecuteRequest(plan_id=plan["plan_id"]))
    assert result["status"] == "failed"
    assert_message(result["message"], "backend.plugin_management.cannot_start_the_component_operation")
    assert manager._worker is None
    assert manager._plan is None
    assert environment.installed_packages(manager.environment.prefix) == before


def test_zero_exit_without_installed_component_still_fails_metadata_verification(
    isolated_manager: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = isolated_manager[0]
    started, finish = threading.Event(), threading.Event()

    def installer(*args: Any, **kwargs: Any) -> int:
        started.set()
        if not finish.wait(5):
            raise RuntimeError("Test installer was not released")
        return 0

    monkeypatch.setattr(management, "run_installer", installer)
    plan = manager.plan(management.PlanRequest(component_id="mimesis", action="install"))
    task = manager.execute(management.ExecuteRequest(plan_id=plan["plan_id"]))
    try:
        assert started.wait(2)
        assert manager.task_snapshot(task["task_id"])["status"] == "running"
        assert manager.status()["available"] is False
    finally:
        finish.set()
        manager._worker.join(timeout=5)
    result = manager.task_snapshot(task["task_id"])
    assert result["status"] == "failed"
    assert result["returncode"] == 0
    assert_message(
        result["message"], "backend.plugin_management.the_installer_exited_but_component_metadata_verification"
    )
    assert "mimesis" not in environment.installed_packages(manager.environment.prefix)
    assert result["restart_required"] is True


@pytest.mark.parametrize(
    "metadata,key",
    [
        (b"Name: wrong\nVersion: 2.0\n", "package_metadata_does_not_match_the_selected"),
        (b"Name: mimesis\nVersion: 2.0\nRequires-Python: >=99\n", "the_latest_stable_version_does_not_support"),
    ],
)
def test_update_metadata_rejects_wrong_identity_and_incompatible_python(metadata: bytes, key: str) -> None:
    with pytest.raises(ValueError) as error:
        updates._package_metadata(metadata, "mimesis", "2.0")
    assert_message(error.value.args[0], "backend.plugin_updates." + key)


@pytest.mark.parametrize("failure", [OSError("unavailable"), None])
def test_update_index_failure_is_localizable_without_mutating_installed_metadata(
    monkeypatch: pytest.MonkeyPatch, failure: Exception | None
) -> None:
    def unavailable(_: str) -> None:
        if failure is not None:
            raise failure

    monkeypatch.setattr(updates.settings_updates, "_fetch_index", unavailable)
    packages = {"mimesis": environment.InstalledPackage("1.0", ())}
    before = dict(packages)
    with pytest.raises(ValueError) as error:
        updates.prepare_update("mimesis", packages)
    suffix = (
        "cannot_complete_the_official_update_compatibility_check"
        if isinstance(failure, OSError)
        else "official_package_metadata_cannot_be_safely_parsed"
    )
    assert_message(error.value.args[0], "backend.plugin_updates." + suffix)
    if failure is not None:
        assert error.value.__cause__ is failure
    else:
        assert isinstance(error.value.__cause__, TypeError)
    assert packages == before


def test_ai_update_below_supported_protocol_is_rejected_before_metadata_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = {"files": [{"filename": "sqlseed_ai-0.2.3-py3-none-any.whl"}]}
    monkeypatch.setattr(updates.settings_updates, "_fetch_index", lambda _: index)
    packages = {"sqlseed-ai": environment.InstalledPackage("0.2.2", ())}
    with pytest.raises(ValueError) as error:
        updates.prepare_update("sqlseed-ai", packages)
    assert_message(error.value.args[0], "backend.plugin_updates.the_latest_stable_version_does_not_meet")
    assert packages["sqlseed-ai"].version == "0.2.2"


def test_verified_wheel_bytes_without_metadata_are_not_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("README.txt", "not an installable wheel")
    payload = buffer.getvalue()
    update = updates.PreparedUpdate(
        "mimesis",
        "mimesis-2.0-py3-none-any.whl",
        "https://files.pythonhosted.org/packages/test.whl",
        hashlib.sha256(payload).hexdigest(),
        "0" * 64,
        environment.InstalledPackage("2.0", ()),
        (),
    )
    monkeypatch.setattr(updates, "_read_artifact", lambda *args, **kwargs: payload)
    with pytest.raises(ValueError) as error:
        updates.download_update(update, tmp_path)
    assert_message(error.value.args[0], "backend.plugin_updates.the_package_metadata_is_invalid_no_update")
    assert (tmp_path / update.filename).read_bytes() == payload


def test_missing_installer_and_unowned_lock_cannot_produce_install_commands(tmp_path: Path) -> None:
    target = environment.Environment(tmp_path, sys.executable, None, None, None)
    constraints = tmp_path / "constraints.txt"
    with pytest.raises(RuntimeError) as install:
        environment.installer_arguments(target, "install", "mimesis", constraints)
    assert_message(install.value.args[0], "backend.plugin_environment.no_installation_tool_is_available")
    with pytest.raises(RuntimeError) as update:
        updates.update_arguments(target, tmp_path / "mimesis-2.0-py3-none-any.whl", constraints)
    assert_message(update.value.args[0], "backend.plugin_updates.no_installation_tool_is_available")
    lock = environment.EnvironmentLock(tmp_path, exclusive=True)
    with pytest.raises(RuntimeError) as unowned:
        lock.fileno()
    assert_message(unowned.value.args[0], "backend.plugin_environment.the_environment_lock_is_not_held")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("problem", ["managed", "invalid_config", "missing_installer"])
def test_real_environment_restrictions_remain_localizable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    prefix = tmp_path / "venv"
    site = prefix / "site"
    site.mkdir(parents=True)
    configuration = prefix / "pyvenv.cfg"
    configuration.write_text("include-system-site-packages = false\n", encoding="utf-8")
    monkeypatch.setattr(environment.sysconfig, "get_path", lambda _: str(site))
    if problem == "managed":
        (site / "EXTERNALLY-MANAGED").touch()
        reason = environment._venv_directory_restriction(prefix)
        suffix = "this_environment_is_externally_managed_use_its"
    elif problem == "invalid_config":
        configuration.write_bytes(b"\xff")
        reason = environment._venv_directory_restriction(prefix)
        suffix = "cannot_verify_write_permissions_for_this_python"
    else:
        monkeypatch.setattr(sys, "prefix", str(prefix))
        monkeypatch.setattr(sys, "base_prefix", str(tmp_path))
        monkeypatch.setattr(environment, "_installer", lambda: _Installer(None, sys.executable, None, "posix"))
        reason = environment._environment().reason
        suffix = "no_usable_pip_or_uv_in_this"
    assert_message(reason, "backend.plugin_environment." + suffix)
    assert not (prefix / ".sqlseed-web-environment.lock").exists()


def test_connection_admission_failures_preserve_registry_and_sqlite_rows(tmp_path: Path) -> None:
    path = tmp_path / "data.db"
    with sqlite_connection(path) as database:
        database.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, value TEXT)")
        database.execute("INSERT INTO records VALUES (1, 'preserved')")
    registry = UIState()
    with pytest.raises(ValueError) as empty:
        registry.add_connection(str(path), provider="base", connection_id="")
    assert_message(empty.value.args[0], "backend.state.connection_id_must_not_be_empty")
    assert_empty(registry.list_connections(), list)
    conn = registry.add_connection(str(path), provider="base")
    try:
        with (
            pytest.raises(UnknownConnectionError) as missing,
            registry.connection_operation(conn.conn_id, job_id="missing"),
        ):
            pytest.fail("Missing job must not acquire a connection")
        assert_message(missing.value.args[0], "backend.state.unknown_running_job")
        lock = registry.connection_lock(conn.conn_id)
        with lock, pytest.raises(ConnectionBusyError) as busy:
            registry.create_job(conn.conn_id, "fill", "blocked")
        assert_message(busy.value.args[0], "backend.state.connection_busy_before_generation")
        for read in (registry.get_job, registry.job_snapshot):
            with pytest.raises(KeyError) as job:
                read("missing")
            assert_message(job.value.args[0], "backend.state.unknown_job")
        assert registry.recent_jobs() == []
        with registry.connection_operation(conn.conn_id), sqlite_connection(path) as database:
            assert database.execute("SELECT * FROM records").fetchall() == [(1, "preserved")]
    finally:
        registry.close_connection(conn.conn_id)


def test_supervisor_without_a_worker_or_listener_rejects_control_requests(isolated_manager: Any) -> None:
    supervisor = Supervisor(port=0)
    with pytest.raises(RuntimeError) as unavailable:
        supervisor._request("prepare")
    assert_message(unavailable.value.args[0], "backend.supervisor.the_application_process_is_temporarily_unavailable")
    with pytest.raises(RuntimeError) as listener:
        supervisor._spawn("business")
    assert_message(listener.value.args[0], "backend.supervisor.the_service_listening_port_is_unavailable")
    with pytest.raises(HTTPException) as pause:
        supervisor.pause()
    assert pause.value.status_code == 409
    assert pause.value.detail["code"] == "service_not_ready"
    assert supervisor.process is None
    assert supervisor.channel is None
    assert supervisor._session == {}


@pytest.mark.parametrize(
    "template,column,sources,options,key",
    [
        ("copy", "text_result", ["quantity"], {}, "copy_requires_one_compatible_source_column"),
        ("concat", "text_result", ["text_source"], {"separator": 1}, "concatenation_supports_only_text_columns_and_a"),
        ("product", "integer_result", ["quantity", "price"], {}, "an_integer_target_requires_integer_sources"),
        ("date_offset", "date_result", ["date_source"], {"days": True}, "date_offset_requires_matching_date_types_and"),
        ("date_offset", "date_result", ["text_source"], {}, "date_offset_requires_matching_date_types_and"),
        ("product", "integer_result", ["quantity", "quantity"], {}, "the_source_column_is_duplicated_or_does"),
    ],
)
def test_incompatible_relation_templates_cannot_replace_existing_rules(
    tmp_path: Path, template: str, column: str, sources: list[str], options: dict[str, Any], key: str
) -> None:
    path = tmp_path / "relations.db"
    with sqlite_connection(path) as database:
        database.execute(
            "CREATE TABLE records(quantity INTEGER, price REAL, integer_result INTEGER, "
            "text_source TEXT, text_result TEXT, date_source DATE, date_result DATE)"
        )
    registry = UIState()
    conn = registry.add_connection(str(path), provider="base")
    try:
        schema = inspect_connection(conn)
        table = schema["tables"][0]
        rules = {column: {"name": column, "generator": "string", "params": {"length": 8}}}
        original = deepcopy(rules)
        suggestion = RelationSuggestion(
            kind="relation", table="records", column=column, template=template, sources=sources, options=options
        )
        with pytest.raises(ValueError) as error:
            compile_relation(suggestion, table, rules)
        assert_message(error.value.args[0], "backend.workbench_ai_relations." + key)
        assert rules == original
        with sqlite_connection(path) as database:
            assert database.execute("SELECT count(*) FROM records").fetchone()[0] == 0
        document = {
            "tables": [
                {
                    "name": "records",
                    "columns": [{"name": "integer_result", "derive_from": "missing", "expression": "value"}],
                }
            ]
        }
        with pytest.raises(ValueError) as unavailable:
            validate_dags(document, schema)
        assert_message(unavailable.value.args[0], "backend.workbench_ai_relations.a_relation_source_is_unavailable")
    finally:
        registry.close_connection(conn.conn_id)
