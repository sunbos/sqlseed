"""Layer 4a/4b: LLM Healer — regenerate a failing subgraph via LLM.

Spec reference: Section 6.3 (LLM regeneration), 6.4 (subgraph splitting).

The healer is **stateless**: it takes a subgraph + violations + parent
context, builds a focused prompt, calls the LLM, parses the JSON response,
and returns a config patch. Oscillation detection and progressive degrade
live in :class:`Layer4Coordinator` (Task 3.6).

Token budget (Section 6.4): the prompt must stay under ``max_prompt_tokens``
(default 2000) to fit small local models (Gemma 4 E2B/E4B). If the parent
schema is too large, the caller must split it via :class:`SubgraphSplitter`
(Task 4.x) before invoking the healer.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.healer.models import SubgraphTask
    from sqlseed_ai.validator.models import ViolationReport

logger = get_logger(__name__)


class LLMClient(Protocol):
    """Minimal protocol for chat-completion clients (openai-compatible)."""

    def chat_completions_create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int | None = None,
    ) -> Any:
        """Create a chat completion (openai-compatible)."""
        ...


class _OpenAICompatAdapter:
    """Adapter wrapping ``openai.OpenAI`` to satisfy the ``LLMClient`` protocol.

    The real OpenAI Python SDK exposes ``client.chat.completions.create(...)``
    (attribute chain), but :class:`LLMHealer` calls
    ``client.chat_completions_create(...)`` (flat method). Without this
    adapter, every heal() call raises
    ``AttributeError: 'OpenAI' object has no attribute 'chat_completions_create'``.

    The adapter is intentionally minimal: it forwards the call verbatim
    and preserves the response object (``resp.choices[0].message.content``
    is read by the healer).
    """

    def __init__(self, openai_client: Any) -> None:
        self._client = openai_client

    def chat_completions_create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int | None = None,
    ) -> Any:
        """Forward to ``client.chat.completions.create``."""
        return self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )


@dataclass
class HealPrompt:
    """Built prompt for inspection/logging."""

    system_prompt: str
    user_prompt: str
    estimated_tokens: int


@dataclass
class HealAttemptResult:
    """Result of a single heal attempt."""

    success: bool
    config_patch: dict[str, Any]
    error: str | None = None
    elapsed_seconds: float = 0.0
    prompt_tokens: int = 0


_SYSTEM_PROMPT = """You are a SQL test-data generator repair agent.

You will receive:
1. A list of tables that failed validation.
2. The violation reports (constraint type + columns + message).
3. The current column configurations (generator, params, derive_from).

Your task: output a JSON object with the corrected column configurations
for the failed tables only. Do NOT include tables that were not in the
failure list.

Output format:
{"tables": [{"name": "<table>", "columns": [{"name": "<col>",
  "generator": "<gen>", "params": {...}}]}]}

Rules:
- Never use a generator that crashes on the column type (e.g. integer on TIMESTAMP).
- Respect UNIQUE constraints by upgrading choice -> template_pool when needed.
- Respect CHECK constraints by adjusting min/max params.
- Keep the response under 1500 tokens.
"""


class LLMHealer:
    """Stateless LLM healer for a single subgraph."""

    def __init__(
        self,
        *,
        client: LLMClient,
        model: str,
        max_prompt_tokens: int = 2000,
        temperature: float = 0.3,
        max_response_tokens: int = 1500,
    ) -> None:
        self._client = client
        self._model = model
        self._max_prompt_tokens = max_prompt_tokens
        self._temperature = temperature
        self._max_response_tokens = max_response_tokens

    def build_prompt(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        parent_config: dict[str, Any],
    ) -> HealPrompt:
        """Build the healer prompt (Section 6.3)."""
        # Filter violations to only those in the subgraph tables
        relevant = [v for v in violations if v.table in task.tables]

        lines: list[str] = []
        lines.append("Failed tables and violations:")
        for v in relevant:
            cols = ", ".join(v.columns) if v.columns else "(unknown)"
            lines.append(
                f"- Table {v.table}, columns [{cols}], constraint={v.constraint_type.value}, severity={v.severity}"
            )
            if v.message:
                lines.append(f"  Message: {v.message}")

        # Include current configs for the failed tables
        lines.append("\nCurrent column configurations:")
        for table_cfg in parent_config.get("tables", []):
            if table_cfg["name"] not in task.tables:
                continue
            lines.append(f"Table {table_cfg['name']}:")
            for col in table_cfg.get("columns", []):
                gen = col.get("generator", "<none>")
                params = col.get("params", {})
                derive = col.get("derive_from")
                if derive:
                    lines.append(f"  - {col['name']}: derive_from={derive}, expr={col.get('expression')}")
                else:
                    lines.append(f"  - {col['name']}: generator={gen}, params={params}")

        user_prompt = "\n".join(lines)
        # Rough token estimate: 4 chars per token
        estimated = len(_SYSTEM_PROMPT) // 4 + len(user_prompt) // 4
        return HealPrompt(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            estimated_tokens=estimated,
        )

    def heal(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        parent_config: dict[str, Any],
    ) -> HealAttemptResult:
        """Call the LLM and return a config patch (or failure)."""
        prompt = self.build_prompt(task, violations, parent_config)

        # Truncate user prompt if it exceeds budget (last-resort safety)
        max_user_chars = (self._max_prompt_tokens - len(_SYSTEM_PROMPT) // 4) * 4
        if len(prompt.user_prompt) > max_user_chars:
            prompt = HealPrompt(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=prompt.user_prompt[:max_user_chars] + "\n[truncated]",
                estimated_tokens=self._max_prompt_tokens,
            )

        start = time.monotonic()
        try:
            resp = self._client.chat_completions_create(
                model=self._model,
                messages=[
                    {"role": "system", "content": prompt.system_prompt},
                    {"role": "user", "content": prompt.user_prompt},
                ],
                temperature=self._temperature,
                max_tokens=self._max_response_tokens,
            )
        except (OSError, RuntimeError, AttributeError) as exc:
            # AttributeError catches a misconfigured client (e.g. raw OpenAI
            # instance without the _OpenAICompatAdapter wrapper) so the
            # reconcile loop can degrade gracefully instead of crashing.
            logger.warning("LLM healer call failed", error=str(exc))
            return HealAttemptResult(
                success=False,
                config_patch={},
                error=f"llm_api_error: {exc}",
                elapsed_seconds=time.monotonic() - start,
            )

        elapsed = time.monotonic() - start
        content = resp.choices[0].message.content or ""

        try:
            patch = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("LLM healer returned malformed JSON", error=str(exc))
            return HealAttemptResult(
                success=False,
                config_patch={},
                error=f"json_syntax: {exc}",
                elapsed_seconds=elapsed,
                prompt_tokens=prompt.estimated_tokens,
            )

        if not isinstance(patch, dict) or "tables" not in patch:
            return HealAttemptResult(
                success=False,
                config_patch={},
                error="json_schema: missing 'tables' key",
                elapsed_seconds=elapsed,
                prompt_tokens=prompt.estimated_tokens,
            )

        return HealAttemptResult(
            success=True,
            config_patch=patch,
            elapsed_seconds=elapsed,
            prompt_tokens=prompt.estimated_tokens,
        )
