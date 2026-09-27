"""URL diagnostic redaction keeps useful targets and handles malformed input."""

from __future__ import annotations

import subprocess
import sys

import pytest

from sqlseed._utils import redaction
from sqlseed._utils.redaction import redact_url_credentials


@pytest.mark.parametrize(
    "message,expected",
    [
        ("postgresql://name:fake-pass@host:5432/db", "postgresql://***:***@host:5432/db"),
        ("postgresql+psycopg://name:p%40ss%2Fword@host/db", "postgresql+psycopg://***:***@host/db"),
        ("postgresql://name:p@ss@host/db", "postgresql://***:***@ss@host/db"),
        ("postgresql://name@host/db", "postgresql://***:***@host/db"),
        ("postgresql://host/db?password=fake&sslmode=require", "postgresql://host/db?password=***&sslmode=require"),
        ("sqlite:///safe.db?%70assword=fake&timeout=3", "sqlite:///safe.db?%70assword=***&timeout=3"),
        ("sqlite:///safe.db?token=fake&password=other", "sqlite:///safe.db?token=***&password=***"),
        ("postgresql://host/db?password='fake'&timeout=3", "postgresql://host/db?password=***&timeout=3"),
        (
            "First postgresql://host/a?sslmode=require then sqlite://host/b?password=second-secret",
            "First postgresql://host/a?sslmode=require then sqlite://host/b?password=***",
        ),
        ("?redirect=http://api.test?token=nested-secret", "?redirect=http://api.test?token=***"),
        (
            "first postgresql://host:5432/db failed; then postgresql://name:fake@other/db",
            "first postgresql://***:***@other/db",
        ),
        (
            "postgresql://name:fake@first/db then postgresql://user:other@second/db",
            "postgresql://***:***@first/db then postgresql://***:***@second/db",
        ),
        ("Invalid database URL: sqlite://u:p@host/db", "Invalid database URL: sqlite://***:***@host/db"),
        ("sqlite:///C:/data/users@work.db?mode=ro", "sqlite:///C:/data/users@work.db?mode=ro"),
        ("file not found: C:/data/sample.db", "file not found: C:/data/sample.db"),
    ],
)
def test_redaction_preserves_nonsecret_diagnostics(message: str, expected: str) -> None:
    assert redact_url_credentials(message) == expected


@pytest.mark.parametrize("password", ["synthetic?value", "synthetic/value", "synthetic#value", "synthetic value"])
def test_sqlalchemy_accepted_raw_password_characters_are_redacted(password: str) -> None:
    from sqlalchemy.engine import make_url

    target = f"postgresql://audit-user:{password}@host:5432/db"
    assert make_url(target).password == password
    assert redact_url_credentials(target) == "postgresql://***:***@host:5432/db"


def test_known_connection_target_allows_raw_scheme_inside_password() -> None:
    from sqlalchemy.engine import make_url

    target = "postgresql://audit-user:synthetic:http://nested@host:5432/db"
    assert make_url(target).password == "synthetic:http://nested"
    assert redact_url_credentials(target, whole_url=True) == "postgresql://***:***@host:5432/db"
    assert redact_url_credentials(f"Failure {target}") == "Failure postgresql://***:***@host:5432/db"


@pytest.mark.parametrize("separator", [" ", "\t", "#", "'", '"', ")"])
@pytest.mark.parametrize("whole_url", [False, True])
def test_query_credentials_keep_raw_value_delimiters_private(separator: str, whole_url: bool) -> None:
    from sqlalchemy.engine import make_url

    password = f"first-secret{separator}second-secret"
    target = f"postgresql://host/db?password={password}&sslmode=require"
    assert make_url(target).query["password"] == password
    assert redact_url_credentials(target, whole_url=whole_url) == "postgresql://host/db?password=***&sslmode=require"


def test_redaction_handles_long_malformed_urls_without_excessive_backtracking() -> None:
    # Import this leaf file alone so the timeout measures malformed text rather
    # than optional plugin discovery during package import on slower hosts.
    script = """
import runpy, sys
redact = runpy.run_path(sys.argv[1])['redact_url_credentials']
for message in ['?' * 100000, '?a' * 50000, 'a-' * 50000, 'x://u:p' * 20000,
                'x:///p' * 20000 + '@host', 'postgresql://' + '@' * 100000 + 'host/db']:
    result = redact(message)
    assert isinstance(result, str)
assert result.startswith('postgresql://***:***@')
"""
    subprocess.run([sys.executable, "-c", script, redaction.__file__], check=True, timeout=5, capture_output=True)
