"""Level 3: Compact/ultra-compact prompt LLM healer + JSON repair.

Spec reference: Section 3.6.

Uses progressively shorter prompts (compact → ultra_compact) to handle
context overflow and JSON format errors. Attempts JSON repair (strip
markdown fences, trailing commas) before declaring failure.
"""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Any, Literal

from sqlseed_ai.healer._client import LLMClient
from sqlseed_ai.healer.models import Level3Result

from sqlseed._utils.logger import get_logger

if TYPE_CHECKING:
    from sqlseed_ai.healer.models import SubgraphTask
    from sqlseed_ai.validator.models import ViolationReport

logger = get_logger(__name__)


_COMPACT_SYSTEM_PROMPT = """You are a SQL test-data repair agent. Output JSON only.
Format: {"tables":[{"name":"<t>","columns":[{"name":"<c>","generator":"<g>","params":{}}]}]}
Fix the violations. No explanation."""

_ULTRA_COMPACT_SYSTEM_PROMPT = """Output JSON only: {"tables":[{"name":"<t>","columns":[{"name":"<c>","generator":"<g>","params":{}}]}]}"""


def _repair_json(text: str) -> str:
    """Attempt to repair minor JSON format errors.

    Strips markdown code fences (```json ... ```), trailing commas, and
    leading/trailing whitespace. Does not use external libraries.
    """
    text = text.strip()
    # Strip markdown code fences.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    # Remove trailing commas before } or ].
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


class Level3CompactHealer:
    """Compact/ultra-compact prompt LLM healer (Level 3).

    Two modes:
    - ``compact``: Reduced system prompt, no few-shot examples.
    - ``ultra_compact``: Minimal system prompt (JSON format only).
    """

    def __init__(
        self,
        *,
        client: LLMClient,
        model: str,
        temperature: float = 0.3,
        max_response_tokens: int = 1000,
    ) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature
        self._max_response_tokens = max_response_tokens

    def _build_user_prompt(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        parent_config: dict[str, Any],
        mode: Literal["compact", "ultra_compact"],
    ) -> str:
        """Build a compact user prompt."""
        relevant = [v for v in violations if v.table in task.tables]
        lines: list[str] = []
        for v in relevant:
            cols = ",".join(v.columns) if v.columns else "?"
            lines.append(f"{v.table}.{cols}:{v.constraint_type.value}")
        lines.append("")
        for table_cfg in parent_config.get("tables", []):
            if table_cfg["name"] not in task.tables:
                continue
            for col in table_cfg.get("columns", []):
                gen = col.get("generator", "?")
                params = col.get("params", {})
                lines.append(f"{table_cfg['name']}.{col['name']}={gen}:{params}")
        return "\n".join(lines)

    def heal_compact(
        self,
        task: SubgraphTask,
        violations: list[ViolationReport],
        parent_config: dict[str, Any],
        mode: Literal["compact", "ultra_compact"],
    ) -> Level3Result:
        """Call LLM with compact or ultra_compact prompt.

        Returns Level3Result. Network errors are re-raised (Section 5.3).
        """
        system_prompt = (
            _COMPACT_SYSTEM_PROMPT if mode == "compact" else _ULTRA_COMPACT_SYSTEM_PROMPT
        )
        user_prompt = self._build_user_prompt(task, violations, parent_config, mode)
        estimated = len(system_prompt) // 4 + len(user_prompt) // 4
        start = time.monotonic()

        try:
            resp = self._client.chat_completions_create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._temperature,
                max_tokens=self._max_response_tokens,
            )
        except (TimeoutError, ConnectionError, OSError) as exc:
            raise
        except (RuntimeError, AttributeError, ValueError) as exc:
            logger.warning("Level 3 LLM call failed", mode=mode, error=str(exc))
            return Level3Result(
                success=False,
                mode=mode,
                error=exc,
                elapsed_seconds=time.monotonic() - start,
                prompt_tokens=estimated,
            )

        elapsed = time.monotonic() - start
        content = resp.choices[0].message.content or ""

        if not content.strip():
            return Level3Result(
                success=False,
                mode=mode,
                raw_response=content,
                elapsed_seconds=elapsed,
                prompt_tokens=estimated,
            )

        # Try direct JSON parse first.
        patch: dict[str, Any] | None = None
        json_repaired = False
        try:
            patch = json.loads(content)
        except json.JSONDecodeError:
            # Attempt JSON repair.
            repaired = _repair_json(content)
            try:
                patch = json.loads(repaired)
                json_repaired = True
            except json.JSONDecodeError as exc:
                logger.warning("Level 3 JSON repair failed", mode=mode, error=str(exc))
                return Level3Result(
                    success=False,
                    mode=mode,
                    raw_response=content,
                    error=exc,
                    elapsed_seconds=elapsed,
                    prompt_tokens=estimated,
                    json_repaired=False,
                )

        if not isinstance(patch, dict) or "tables" not in patch:
            return Level3Result(
                success=False,
                mode=mode,
                raw_response=content,
                error=RuntimeError("json_schema: missing 'tables' key"),
                elapsed_seconds=elapsed,
                prompt_tokens=estimated,
                json_repaired=json_repaired,
            )

        return Level3Result(
            success=True,
            mode=mode,
            config_patch=patch,
            raw_response=content,
            elapsed_seconds=elapsed,
            prompt_tokens=estimated,
            json_repaired=json_repaired,
        )
