"""Credential-free AI preferences and service-scoped in-memory authentication."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import SplitResult, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sqlseed_web.settings_environment import require_ai_available
from sqlseed_web.workbench_store import _default_path

if TYPE_CHECKING:
    from sqlseed_ai.config import AIConfig

    from sqlseed_web.state import UIState

_FIELDS = ("backend", "model", "base_url")
_SETTINGS_LOCK = RLock()


def _validate_endpoint_components(parsed: SplitResult) -> None:
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError
    if parsed.query or parsed.fragment:
        raise ValueError


def http_endpoint(value: str) -> str:
    """Accept plain HTTP endpoints, never URL-embedded credentials or tokens."""
    if not (value := value.strip()):
        return value
    try:
        parsed = urlsplit(value)
        _validate_endpoint_components(parsed)
        if (
            any(char.isspace() or ord(char) < 32 for char in value)
            or "\\" in value
            or (parsed.port is not None and parsed.port < 1)
        ):
            raise ValueError
    except ValueError:
        raise ValueError("Base URL 必须是 HTTP(S) 地址；认证请使用 API Key 字段") from None
    return value.rstrip("/")


class SettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    backend: Literal["openai_compat", "google_ai_studio", "ollama", "lm_studio"]
    model: str = Field(default="", max_length=200)
    base_url: str = Field(default="", max_length=2000)
    api_key: str = Field(default="", max_length=4000, repr=False)
    clear_api_key: bool = False

    @field_validator("base_url")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        return http_endpoint(value)

    @field_validator("model", "api_key")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


def settings_path() -> Path:
    """Follow the workspace data directory, with an independent path override."""
    if configured := os.environ.get("SQLSEED_WEB_SETTINGS_PATH"):
        return Path(configured).expanduser().resolve()
    workspace = os.environ.get("SQLSEED_WEB_WORKSPACE_PATH")
    return (Path(workspace).expanduser().resolve() if workspace else _default_path()).with_name("settings.json")


def read_preferences() -> dict[str, str]:
    """Ignore unavailable or malformed preferences; never load credentials."""
    try:
        value = json.loads(settings_path().read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != set(_FIELDS):
            return {}
        parsed = SettingsRequest.model_validate(value)
        return {key: str(getattr(parsed, key)) for key in _FIELDS}
    except (OSError, ValueError, ValidationError):
        return {}


def storage_info() -> dict[str, Any]:
    return {
        "kind": "user_file",
        "path": str(settings_path()),
        "fields": list(_FIELDS),
        "api_key": "session_or_environment",
    }


def unavailable_preferences(registry: UIState) -> dict[str, Any]:
    """Show saved ordinary fields without loading an absent/broken AI plugin."""
    values = {
        "backend": os.environ.get("SQLSEED_AI_BACKEND", "openai_compat"),
        "model": os.environ.get("SQLSEED_AI_MODEL", ""),
        "base_url": os.environ.get("SQLSEED_AI_BASE_URL", os.environ.get("OPENAI_BASE_URL", "")),
    }
    with _SETTINGS_LOCK:
        values.update(read_preferences())
        override = registry.get_ai_override()
        values.update({key: override[key] for key in _FIELDS if key in override})
    try:
        values["base_url"] = http_endpoint(values["base_url"])
    except ValueError:
        values["base_url"] = ""
    return {**values, "api_key_present": False}


def _service(config: AIConfig) -> str:
    try:
        endpoint = http_endpoint(config.resolve_base_url())
        parsed = urlsplit(endpoint)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return json.dumps([config.backend.value, parsed.scheme, parsed.hostname, port, parsed.path])
    except ValueError:
        return ""


def _apply(config: AIConfig, values: dict[str, str]) -> None:
    from sqlseed_ai.config import AIBackend

    if "backend" in values:
        config.backend = AIBackend(values["backend"])
    if "model" in values:
        config.model = values["model"] or None
    if "base_url" in values:
        config.base_url = http_endpoint(values["base_url"]) or None


def credential_snapshot(config: AIConfig) -> AIConfig:
    """Prevent downstream SDK setup from re-reading an unscoped environment key."""
    from sqlseed_ai.config import AIConfig

    class ServiceAIConfig(AIConfig):
        def resolve_api_key(self) -> str | None:
            if self.api_key:
                return self.api_key
            return {"ollama": "ollama", "lm_studio": "lm-studio"}.get(self.backend.value)

        @property
        def has_real_api_key(self) -> bool:
            return bool(self.api_key) and self.backend.value not in {"ollama", "lm_studio"}

    return ServiceAIConfig.model_validate(config.model_dump())


def resolve_settings(
    registry: UIState,
    draft: SettingsRequest | None = None,
    *,
    session_override: dict[str, str] | None = None,
) -> tuple[AIConfig, dict[str, str]]:
    """Resolve fields without network I/O; a secret is usable only at its source service."""
    require_ai_available()
    from sqlseed_ai.config import AIConfig

    with _SETTINGS_LOCK:
        override = registry.get_ai_override() if session_override is None else dict(session_override)
        saved = read_preferences()
    env = AIConfig.from_env()
    config = env.model_copy(deep=True)
    config.api_key = None
    sources = {
        "backend": "environment" if os.environ.get("SQLSEED_AI_BACKEND") or env.base_url else "default",
        "model": "environment" if env.model else "none",
        "base_url": "environment" if env.base_url else "default",
        "api_key": "none",
    }
    for values, source in ((saved, "saved"), (override, "saved" if override.get("_settings_saved") else "session")):
        _apply(config, values)
        sources.update({key: source for key in _FIELDS if key in values})
    # Remember the original binding of legacy unbound session credentials,
    # then select a credential against the final draft endpoint exactly once.
    key_service = override.get("_api_key_service", _service(config))
    if draft is not None:
        _apply(config, {key: str(getattr(draft, key)) for key in _FIELDS})
        sources.update({key: "draft" for key in _FIELDS})
    final_service = _service(config)
    if draft is not None and draft.clear_api_key:
        pass
    elif draft is not None and draft.api_key:
        config.api_key = draft.api_key
        sources["api_key"] = "draft"
    elif override.get("api_key") and final_service and key_service == final_service:
        config.api_key = override["api_key"]
        sources["api_key"] = "session"
    elif not override.get("_api_key_cleared") and env.api_key and final_service and _service(env) == final_service:
        config.api_key = env.api_key
        sources["api_key"] = "environment"
    # Validate environment endpoints too, before an SDK can receive credentials.
    if config.base_url:
        config.base_url = http_endpoint(config.base_url)
    return credential_snapshot(config), sources


def _write_preferences(values: dict[str, str]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".settings-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(values, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_preferences(registry: UIState, body: SettingsRequest) -> None:
    """Publish in-memory configuration only after the atomic disk write succeeds."""
    with _SETTINGS_LOCK:
        config, sources = resolve_settings(registry, body)
        values = {key: str(getattr(body, key)) for key in _FIELDS}
        session: dict[str, str | None] = dict(values)
        session["_settings_saved"] = "1"
        if sources["api_key"] in {"session", "draft"} and config.api_key:
            session["api_key"] = config.api_key
            session["_api_key_service"] = _service(config)
        if body.clear_api_key or (registry.get_ai_override().get("_api_key_cleared") and not body.api_key):
            session["_api_key_cleared"] = "1"
        _write_preferences(values)
        registry.set_ai_override(session)


def set_session_preferences(registry: UIState, values: dict[str, str | None]) -> None:
    """Explicit nulls remove legacy overrides; omitted fields retain their value."""
    with _SETTINGS_LOCK:
        current, _ = resolve_settings(registry)
        candidate = registry.get_ai_override()
        candidate.pop("_settings_saved", None)
        if candidate.get("api_key"):
            candidate.setdefault("_api_key_service", _service(current))
        for key in _FIELDS:
            if key in values:
                value = values[key]
                if value and value.strip():
                    candidate[key] = value.strip()
                else:
                    candidate.pop(key, None)
        # Resolve removals against persisted/environment defaults without
        # publishing this candidate or re-binding the previous service's key.
        restored, _ = resolve_settings(registry, session_override=candidate)
        body = SettingsRequest.model_validate(
            {
                "backend": restored.backend.value,
                "model": restored.model or "",
                "base_url": restored.base_url or "",
                "api_key": values.get("api_key") or "",
            }
        )
        config, sources = resolve_settings(registry, body, session_override=candidate)
        candidate.pop("api_key", None)
        candidate.pop("_api_key_service", None)
        if sources["api_key"] in {"session", "draft"} and config.api_key:
            candidate["api_key"] = config.api_key
            candidate["_api_key_service"] = _service(config)
        if body.api_key:
            candidate.pop("_api_key_cleared", None)
        registry.set_ai_override(dict(candidate))
