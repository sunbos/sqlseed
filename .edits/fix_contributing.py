"""Fix CONTRIBUTING.md: commit example references MySQL (removed); use PostgreSQL example."""
from pathlib import Path

p = Path("/tmp/wt-contract/CONTRIBUTING.md")
text = p.read_text(encoding="utf-8")
orig = text

text = text.replace(
    """feat(database): add MySQL support via SQLAlchemyAdapter

- Add pymysql as optional dependency
- Update TypeNormalizer for MySQL types
- Add integration tests for MySQL""",
    """feat(database): add PostgreSQL support via SQLAlchemyAdapter

- Add psycopg as optional dependency
- Update TypeNormalizer for PostgreSQL types
- Add integration tests for PostgreSQL""",
)

if text == orig:
    raise SystemExit("NO CHANGES MADE — check patterns")
p.write_text(text, encoding="utf-8")
print("CONTRIBUTING.md updated")
