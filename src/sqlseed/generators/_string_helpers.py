from __future__ import annotations

import string
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from random import Random


def resolve_charset(charset: str | None) -> str:
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
    chars = resolve_charset(charset)
    length = rng.randint(min_length, max_length)
    return "".join(rng.choice(chars) for _ in range(length))
