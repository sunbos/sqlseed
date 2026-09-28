"""Stable SQLite filename semantics across SQLAlchemy URL parser versions."""

from __future__ import annotations

from sqlalchemy.engine import URL, make_url


def connection_url(target: str) -> URL:
    """Build a DBAPI target without prematurely decoding a SQLite filename.

    Bare paths are literal filesystem paths. SQLite URLs retain the historical
    unescaped database component, which may itself be a percent-encoded file:
    URI. SQLAlchemy 2.1 decodes URL.database, unlike 2.0; bypass that step so
    only SQLite decodes its own URI, while SQLAlchemy still parses URL options.
    Other dialects keep SQLAlchemy's normal URL interpretation.
    """
    driver, separator, location = target.partition("://")
    if not separator:
        return URL.create("sqlite", database=target)
    if driver.partition("+")[0] == "sqlite" and location.startswith("/"):
        filename, query_separator, query = location[1:].partition("?")
        options_url = f"{driver}:///{'?' + query if query_separator else ''}"
        return make_url(options_url).set(database=filename)
    return make_url(target)
