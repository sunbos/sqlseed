"""Random string generation utilities."""

from __future__ import annotations

import string
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from random import Random


def resolve_charset(charset: str | None) -> str:
    """Resolve a charset name and return the corresponding character set.

    Supports predefined names (``alphanumeric``, ``alpha``, ``digits``) as well as
    custom character sets. When ``None`` is passed, the default charset is returned
    (letters, digits, space, underscore and hyphen).
    """
    if charset == "alphanumeric":
        return string.ascii_letters + string.digits
    if charset == "alpha":
        return string.ascii_letters
    if charset == "digits":
        return string.digits
    if charset is not None:
        return charset
    return string.ascii_letters + string.digits + " _-"


def generate_random_string(
    rng: Random,
    *,
    min_length: int = 1,
    max_length: int = 100,
    charset: str | None = None,
) -> str:
    """Generate a random string of a length within the given range using the provided RNG.

    The character set is resolved via ``resolve_charset``; the length is chosen randomly
    from the ``[min_length, max_length]`` interval.
    """
    chars = resolve_charset(charset)
    length = rng.randint(min_length, max_length)
    return "".join(rng.choice(chars) for _ in range(length))
