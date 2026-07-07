"""FailureClassifier — classify LLM failures for routing decisions.

Spec reference: Section 3.3 + Section 5.1.

Classification rules (checked in order):
  1. Error message contains "context length" / "too long" → CONTEXT_OVERFLOW
  2. Response is empty/whitespace → EMPTY_RESPONSE
  3. JSONDecodeError → JSON_FORMAT
  4. Error message contains "validation" / "constraint" → SEMANTIC
  5. Timeout/Connection errors → NETWORK
  6. Other → UNKNOWN (treated as SEMANTIC by HealOrchestrator)
"""

from __future__ import annotations

import json

from sqlseed_ai.healer.models import FailureType


class FailureClassifier:
    """Classify LLM failure types based on error and response."""

    def classify(self, error: Exception | None, response: str | None) -> FailureType:
        """Classify an LLM failure.

        Args:
            error: The exception raised (if any). None if the call succeeded
                but the response was invalid.
            response: The raw LLM response string (if any).

        Returns:
            The classified FailureType.
        """
        # 1. Check error message for context overflow keywords.
        if error is not None:
            err_msg = str(error).lower()
            if "context length" in err_msg or "too long" in err_msg:
                return FailureType.CONTEXT_OVERFLOW

        # 2. Check for empty response.
        if response is not None and not response.strip():
            return FailureType.EMPTY_RESPONSE
        if error is None and response is None:
            return FailureType.EMPTY_RESPONSE

        # 3. Check for JSON format errors.
        if isinstance(error, json.JSONDecodeError):
            return FailureType.JSON_FORMAT

        # 4. Check for semantic/validation errors.
        if error is not None:
            err_msg = str(error).lower()
            if "validation" in err_msg or "constraint" in err_msg:
                return FailureType.SEMANTIC

        # 5. Check for network errors.
        if isinstance(error, TimeoutError | ConnectionError | OSError):
            return FailureType.NETWORK
        if error is not None:
            err_msg = str(error).lower()
            if "timeout" in err_msg or "timed out" in err_msg:
                return FailureType.NETWORK
            if "connection" in err_msg or "connect" in err_msg:
                return FailureType.NETWORK
            if "rate limit" in err_msg:
                return FailureType.NETWORK

        # 6. Unknown.
        return FailureType.UNKNOWN
