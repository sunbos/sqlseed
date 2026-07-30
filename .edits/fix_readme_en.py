"""Fix README.md: remove --backend flag refs, add sqlseed-cli install/deps rows."""
from pathlib import Path

p = Path("/tmp/wt-contract/README.md")
text = p.read_text(encoding="utf-8")
orig = text

# 1. ai-suggest has no --backend option -> use SQLSEED_AI_BACKEND env var
text = text.replace(
    """# Use local LM Studio / Ollama
sqlseed ai-suggest app.db --table projects --output projects.yaml --backend lm_studio --model google/gemma-4-e4b""",
    """# Use local LM Studio / Ollama (backend selected via env var; ai-suggest has no --backend flag)
SQLSEED_AI_BACKEND=lm_studio sqlseed ai-suggest app.db --table projects --output projects.yaml --model google/gemma-4-e4b""",
)

# 2. Backend table: drop `--backend xxx or` (no such CLI flag)
text = text.replace(
    "| **Google AI Studio** | Official API, recommended for Gemma 4 26B/31B | `--backend google_ai_studio` or `SQLSEED_AI_BACKEND=google_ai_studio` |",
    "| **Google AI Studio** | Official API, recommended for Gemma 4 26B/31B | `SQLSEED_AI_BACKEND=google_ai_studio` |",
)
text = text.replace(
    "| **LM Studio** | Local inference, suitable for Gemma 4 2B/4B | `--backend lm_studio` or `SQLSEED_AI_BACKEND=lm_studio` |",
    "| **LM Studio** | Local inference, suitable for Gemma 4 2B/4B | `SQLSEED_AI_BACKEND=lm_studio` (default URL `http://127.0.0.1:1234/v1`) |",
)
text = text.replace(
    "| **Ollama** | Local inference, suitable for Gemma 4 2B/4B/26B | `--backend ollama` or `SQLSEED_AI_BACKEND=ollama` |",
    "| **Ollama** | Local inference, suitable for Gemma 4 2B/4B/26B | `SQLSEED_AI_BACKEND=ollama` |",
)
text = text.replace(
    "| **OpenAI-compatible** | Generic OpenAI-compatible endpoint (e.g., OpenRouter, DeepSeek) | `--backend openai_compat` or `SQLSEED_AI_BACKEND=openai_compat` |",
    "| **OpenAI-compatible** | Generic OpenAI-compatible endpoint (e.g., OpenRouter, DeepSeek) | `SQLSEED_AI_BACKEND=openai_compat` |",
)

# 3. Optional Plugins install section: add sqlseed-cli
text = text.replace(
    """### Optional Plugins

```bash
# AI analysis plugin (requires openai SDK)
pip install sqlseed-ai""",
    """### Optional Plugins

```bash
# CLI plugin (provides the `sqlseed` command; auto-pulls sqlseed core)
pip install sqlseed-cli

# AI analysis plugin (requires openai SDK)
pip install sqlseed-ai""",
)

# 4. Dependencies table: add sqlseed-cli row
text = text.replace(
    "| `sqlseed[docs]` | + mkdocs-material, mkdocstrings | Documentation build |\n",
    "| `sqlseed[docs]` | + mkdocs-material, mkdocstrings | Documentation build |\n"
    "| `sqlseed-cli` | sqlseed, **click**, **rich** | CLI plugin — provides the `sqlseed` command (fill/preview/inspect/init/replay), auto-pulls sqlseed core |\n",
)

if text == orig:
    raise SystemExit("NO CHANGES MADE — check patterns")
p.write_text(text, encoding="utf-8")
print("README.md updated")
