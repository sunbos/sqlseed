"""Tests for random string generation utilities.

Covers ``resolve_charset`` and ``generate_random_string`` with both
deterministic (seeded) assertions and edge-case validation.
"""

from __future__ import annotations

import random
import string

import pytest

from sqlseed.generators._string_helpers import generate_random_string, resolve_charset
from sqlseed.generators.base_provider import BaseProvider

# ---------------------------------------------------------------------------
# resolve_charset
# ---------------------------------------------------------------------------


class TestResolveCharset:
    """Tests for ``resolve_charset``."""

    def test_alphanumeric(self) -> None:
        result = resolve_charset("alphanumeric")
        assert result == string.ascii_letters + string.digits

    def test_alpha(self) -> None:
        result = resolve_charset("alpha")
        assert result == string.ascii_letters

    def test_digits(self) -> None:
        result = resolve_charset("digits")
        assert result == string.digits

    def test_none_returns_default(self) -> None:
        result = resolve_charset(None)
        assert result == string.ascii_letters + string.digits + " _-"

    def test_default_contains_space(self) -> None:
        result = resolve_charset(None)
        assert " " in result

    def test_default_contains_underscore(self) -> None:
        result = resolve_charset(None)
        assert "_" in result

    def test_default_contains_hyphen(self) -> None:
        result = resolve_charset(None)
        assert "-" in result

    def test_custom_charset_returned_as_is(self) -> None:
        custom = "abcXYZ123"
        result = resolve_charset(custom)
        assert result == custom

    def test_custom_single_char(self) -> None:
        result = resolve_charset("a")
        assert result == "a"

    def test_empty_string_returned_as_is(self) -> None:
        # Empty string is not None, so it is returned directly
        result = resolve_charset("")
        assert result == ""

    def test_alphanumeric_contains_letters_and_digits(self) -> None:
        result = resolve_charset("alphanumeric")
        for c in string.ascii_letters:
            assert c in result
        for c in string.digits:
            assert c in result

    def test_alpha_does_not_contain_digits(self) -> None:
        result = resolve_charset("alpha")
        for c in string.digits:
            assert c not in result

    def test_digits_does_not_contain_letters(self) -> None:
        result = resolve_charset("digits")
        for c in string.ascii_letters:
            assert c not in result

    # --- alias support (LLMs sometimes emit non-canonical names) ---

    def test_alias_alphanum_resolves_to_alphanumeric(self) -> None:
        result = resolve_charset("alphanum")
        assert result == string.ascii_letters + string.digits

    def test_alias_letters_digits_resolves_to_alphanumeric(self) -> None:
        result = resolve_charset("letters_digits")
        assert result == string.ascii_letters + string.digits

    def test_alias_ascii_letters_digits_resolves_to_alphanumeric(self) -> None:
        result = resolve_charset("ascii_letters_digits")
        assert result == string.ascii_letters + string.digits

    def test_alias_letters_resolves_to_alpha(self) -> None:
        result = resolve_charset("letters")
        assert result == string.ascii_letters

    def test_alias_ascii_letters_resolves_to_alpha(self) -> None:
        result = resolve_charset("ascii_letters")
        assert result == string.ascii_letters

    def test_alias_numeric_resolves_to_digits(self) -> None:
        result = resolve_charset("numeric")
        assert result == string.digits

    def test_alias_numbers_resolves_to_digits(self) -> None:
        result = resolve_charset("numbers")
        assert result == string.digits

    def test_aliases_are_case_sensitive(self) -> None:
        """Aliases must be lowercase (custom charsets can be anything)."""
        # "ALPHANUMERIC" is not a recognised alias → returned as-is literal
        result = resolve_charset("ALPHANUMERIC")
        assert result == "ALPHANUMERIC"


# ---------------------------------------------------------------------------
# generate_random_string
# ---------------------------------------------------------------------------


class TestGenerateRandomString:
    """Tests for ``generate_random_string``."""

    def test_default_params_returns_string(self) -> None:
        rng = random.Random(42)
        result = generate_random_string(rng)
        assert isinstance(result, str)
        assert len(result) >= 1
        assert len(result) <= 100

    def test_length_within_range(self) -> None:
        rng = random.Random(42)
        result = generate_random_string(rng, min_length=5, max_length=10)
        assert 5 <= len(result) <= 10

    def test_min_equals_max(self) -> None:
        rng = random.Random(42)
        result = generate_random_string(rng, min_length=8, max_length=8)
        assert len(result) == 8

    def test_min_length_one(self) -> None:
        rng = random.Random(42)
        result = generate_random_string(rng, min_length=1, max_length=1)
        assert len(result) == 1

    def test_charset_alphanumeric(self) -> None:
        rng = random.Random(42)
        valid = string.ascii_letters + string.digits
        result = generate_random_string(rng, min_length=20, max_length=20, charset="alphanumeric")
        assert all(c in valid for c in result)

    def test_charset_alpha(self) -> None:
        rng = random.Random(42)
        result = generate_random_string(rng, min_length=20, max_length=20, charset="alpha")
        assert all(c in string.ascii_letters for c in result)

    def test_charset_digits(self) -> None:
        rng = random.Random(42)
        result = generate_random_string(rng, min_length=20, max_length=20, charset="digits")
        assert all(c in string.digits for c in result)

    def test_custom_charset(self) -> None:
        rng = random.Random(42)
        result = generate_random_string(rng, min_length=20, max_length=20, charset="abc")
        assert all(c in "abc" for c in result)

    def test_custom_single_char_charset(self) -> None:
        rng = random.Random(42)
        result = generate_random_string(rng, min_length=5, max_length=5, charset="x")
        assert result == "xxxxx"

    def test_default_charset(self) -> None:
        rng = random.Random(42)
        valid = string.ascii_letters + string.digits + " _-"
        result = generate_random_string(rng, min_length=50, max_length=50, charset=None)
        assert all(c in valid for c in result)

    def test_seed_reproducibility(self) -> None:
        rng1 = random.Random(123)
        rng2 = random.Random(123)
        r1 = generate_random_string(rng1, min_length=10, max_length=10)
        r2 = generate_random_string(rng2, min_length=10, max_length=10)
        assert r1 == r2

    def test_different_seeds_differ(self) -> None:
        rng1 = random.Random(1)
        rng2 = random.Random(2)
        r1 = generate_random_string(rng1, min_length=20, max_length=20)
        r2 = generate_random_string(rng2, min_length=20, max_length=20)
        assert r1 != r2

    def test_min_length_zero(self) -> None:
        rng = random.Random(42)
        result = generate_random_string(rng, min_length=0, max_length=0)
        assert len(result) == 0

    def test_min_length_zero_max_positive(self) -> None:
        rng = random.Random(42)
        result = generate_random_string(rng, min_length=0, max_length=10)
        assert 0 <= len(result) <= 10

    def test_min_greater_than_max_raises(self) -> None:
        rng = random.Random(42)
        with pytest.raises(ValueError):
            generate_random_string(rng, min_length=10, max_length=5)

    def test_empty_charset_raises_index_error(self) -> None:
        rng = random.Random(42)
        with pytest.raises(IndexError):
            generate_random_string(rng, min_length=1, max_length=1, charset="")

    def test_large_max_length(self) -> None:
        rng = random.Random(42)
        result = generate_random_string(rng, min_length=200, max_length=200)
        assert len(result) == 200

    def test_uses_provided_rng(self) -> None:
        """The function should use the provided RNG, not a global one."""
        rng = random.Random(999)
        result = generate_random_string(rng, min_length=10, max_length=10)
        # Reproduce with the same seed to verify the RNG was used
        rng2 = random.Random(999)
        expected = generate_random_string(rng2, min_length=10, max_length=10)
        assert result == expected

    def test_integration_with_base_provider_rng(self) -> None:
        """Verify the helper works with BaseProvider's internal RNG."""
        provider = BaseProvider()
        provider.set_seed(42)
        result = provider.generate("string", min_length=10, max_length=20, charset="digits")
        assert 10 <= len(result) <= 20
        assert all(c in string.digits for c in result)
