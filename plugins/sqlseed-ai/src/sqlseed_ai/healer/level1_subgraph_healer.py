"""Level 1: Subgraph-level LLM healer.

Spec reference: Section 3.4.

Refactored from ``LLMHealer`` (deleted in Task 13). Sends the entire
subgraph (all violations + current column configs) to the LLM and
returns a config patch. No compact/ultra-compact logic — that lives in
``Level3CompactHealer``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlseed_ai.healer.models import Level1Result

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.healer._client import LLMClient
    from sqlseed_ai.healer.models import SubgraphTask
    from sqlseed_ai.validator.models import ViolationReport

logger = get_logger(__name__)


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


@dataclass
class SubgraphPrompt:
    """Built prompt for inspection/logging."""

    system_prompt: str
    user_prompt: str
    estimated_tokens: int


class Level1SubgraphHealer:
    """Subgraph-level LLM healer (Level 1).

    Sends the full subgraph context to the LLM. Use when the subgraph
    fits comfortably within the model's context window (pre-judged by
    ``ContextWindowDetector``).
    """

    def __init__(
        self,
        *,
        client: LLMClient,
        model: str,
        temperature: float = 0.3,
        max_response_tokens: int = 1500,
    ) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature
        self._max_response_tokens = max_response_tokens

    def build_prompt(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        parent_config: dict[str, Any],
    ) -> SubgraphPrompt:
        """Build the subgraph-level healer prompt."""
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
        estimated = len(_SYSTEM_PROMPT) // 4 + len(user_prompt) // 4
        return SubgraphPrompt(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            estimated_tokens=estimated,
        )

    def heal(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        parent_config: dict[str, Any],
    ) -> Level1Result:
        """Call the LLM with full subgraph context.

        Returns Level1Result. Does NOT raise on LLM errors — the caller
        (HealOrchestrator) classifies the failure via FailureClassifier.
        Network errors are re-raised so the orchestrator can propagate
        them (per Section 5.3).
        """
        prompt = self.build_prompt(task, violations, parent_config)
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
        except (TimeoutError, ConnectionError, OSError):
            # Network errors propagate (Section 5.3) — do not degrade.
            raise
        except (RuntimeError, AttributeError, ValueError) as exc:
            logger.warning("Level 1 LLM call failed", error=str(exc))
            return Level1Result(
                success=False,
                config_patch=None,
                error=exc,
                elapsed_seconds=time.monotonic() - start,
                prompt_tokens=prompt.estimated_tokens,
            )

        elapsed = time.monotonic() - start
        content = resp.choices[0].message.content or ""

        if not content.strip():
            return Level1Result(
                success=False,
                config_patch=None,
                raw_response=content,
                error=None,
                elapsed_seconds=elapsed,
                prompt_tokens=prompt.estimated_tokens,
            )

        try:
            patch = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("Level 1 LLM returned malformed JSON", error=str(exc))
            return Level1Result(
                success=False,
                config_patch=None,
                raw_response=content,
                error=exc,
                elapsed_seconds=elapsed,
                prompt_tokens=prompt.estimated_tokens,
            )

        if not isinstance(patch, dict) or "tables" not in patch:
            return Level1Result(
                success=False,
                config_patch=None,
                raw_response=content,
                error=RuntimeError("json_schema: missing 'tables' key"),
                elapsed_seconds=elapsed,
                prompt_tokens=prompt.estimated_tokens,
            )

        return Level1Result(
            success=True,
            config_patch=patch,
            raw_response=content,
            elapsed_seconds=elapsed,
            prompt_tokens=prompt.estimated_tokens,
        )
