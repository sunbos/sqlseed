"""Pure-logic tests for FailureClassifier (no LLM calls)."""

from __future__ import annotations

import json

import pytest
from sqlseed_ai.healer.failure_classifier import FailureClassifier, FailureType


@pytest.fixture
def classifier():
    return FailureClassifier()


def test_classify_context_overflow_from_message(classifier):
    """Error message containing 'context length' → CONTEXT_OVERFLOW."""
    err = RuntimeError("This model's maximum context length is 8192 tokens")
    assert classifier.classify(err, response=None) == FailureType.CONTEXT_OVERFLOW


def test_classify_context_overflow_from_too_long(classifier):
    """Error message containing 'too long' → CONTEXT_OVERFLOW."""
    err = RuntimeError("Input is too long for this model")
    assert classifier.classify(err, response=None) == FailureType.CONTEXT_OVERFLOW


def test_classify_empty_response(classifier):
    """Empty or whitespace-only response → EMPTY_RESPONSE."""
    assert classifier.classify(None, response="") == FailureType.EMPTY_RESPONSE
    assert classifier.classify(None, response="   \n  ") == FailureType.EMPTY_RESPONSE


def test_classify_json_format(classifier):
    """JSONDecodeError → JSON_FORMAT."""
    err = json.JSONDecodeError("Expecting value", "", 0)
    assert classifier.classify(err, response="{invalid json") == FailureType.JSON_FORMAT


def test_classify_semantic_from_message(classifier):
    """Error message containing 'validation' → SEMANTIC."""
    err = RuntimeError("Validation failed: CHECK constraint violated")
    assert classifier.classify(err, response='{"tables": []}') == FailureType.SEMANTIC


def test_classify_network_timeout(classifier):
    """Timeout-related error → NETWORK."""
    err = TimeoutError("Request timed out after 60s")
    assert classifier.classify(err, response=None) == FailureType.NETWORK


def test_classify_network_connection(classifier):
    """Connection-related error → NETWORK."""
    err = ConnectionError("Failed to connect to localhost:1234")
    assert classifier.classify(err, response=None) == FailureType.NETWORK


def test_classify_unknown(classifier):
    """Unclassified error → UNKNOWN."""
    err = RuntimeError("Something unexpected happened")
    assert classifier.classify(err, response=None) == FailureType.UNKNOWN
