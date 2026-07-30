"""Fix the 7 remaining failed edits."""
from __future__ import annotations
import sys
sys.path.insert(0, "/workspace")
from _edit_helper import edit

ROOT = "/tmp/wt-multi-db"

# 1. README.md – the extras table line doesn't exist in a table there, skip
# Actually README.md has a description section but no table row with that exact text.
# Looking at actual file, there is no table at all for extras. So we skip.

# 2. README.zh-CN.md AI quick-ref block uses -t / -o, not --table/--output
edit(f"{ROOT}/README.zh-CN.md",
     "# ═══ AI 后端选择 ═══\nsqlseed ai-suggest app.db -t users -o users.yaml --backend google_ai_studio --model gemma-4-26b-a4b-it\nsqlseed ai-suggest app.db -t users -o users.yaml --backend ollama --model gemma-4-e4b-it\nSQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db -t users -o users.yaml --model google/gemma-4-e4b\nsqlseed ai-suggest app.db -t users -o users.yaml --backend openai_compat --model your-model --base-url https://your-api-endpoint",
     """# ═══ AI 后端选择 ═══
SQLSEED_AI_BACKEND=google_ai_studio sqlseed ai-suggest app.db -t users -o users.yaml --model gemma-4-26b-a4b-it
SQLSEED_AI_BACKEND=ollama sqlseed ai-suggest app.db -t users -o users.yaml --model gemma-4-e4b-it
SQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db -t users -o users.yaml --model google/gemma-4-e4b
SQLSEED_AI_BACKEND=openai_compat SQLSEED_AI_BASE_URL=https://your-api-endpoint sqlseed ai-suggest app.db -t users -o users.yaml --model your-model""")

# 3. docs/architecture.zh-CN.md – let's see what's actually there
# We will check in a separate step.

# 4. src/sqlseed/generators/AGENTS.md
edit(f"{ROOT}/src/sqlseed/generators/AGENTS.md",
     "├── base_provider.py     # BaseProvider — 31 generators, lazy deps",
     "├── base_provider.py     # BaseProvider — 31 generators, no optional deps")

# 5. plugins/sqlseed-ai/AGENTS.md pyproject line
edit(f"{ROOT}/plugins/sqlseed-ai/AGENTS.md",
     "├── pyproject.toml        # Separate package: sqlseed>=0.1.0, openai>=1.0, httpx>=0.24.0",
     "├── pyproject.toml        # Separate package: sqlseed>=0.1.0, sqlseed-cli>=0.1.0, openai>=1.0, httpx>=0.24.0; optional mcp>=1.0,<2")

print("Remaining targeted fixes done.")
