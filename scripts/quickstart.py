#!/usr/bin/env python
"""sqlseed + Gemma 4 one-click setup script (cross-platform).

Usage:
    python scripts/quickstart.py [--backend lm_studio|ollama|google] [--model MODEL_NAME]
    python scripts/quickstart.py --skip-install   # Skip pip install, use current env
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "quickstart_demo.db"


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a command and print it."""
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, check=check, text=True)


def check_lm_studio() -> bool:
    """Check if LM Studio is running."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:1234/v1/models", timeout=3) as r:
            return r.status == 200
    except OSError:
        return False


def check_ollama() -> bool:
    """Check if Ollama is running."""
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            return r.status == 200
    except OSError:
        return False


def sqlseed_cmd(python: str) -> list[str]:
    """Build a sqlseed CLI invocation."""
    return [python, "-c", "from sqlseed.cli.main import cli; cli()", "--"]


def _fill_data(python: str) -> None:
    """Fill the demo database with sample data using sqlseed CLI."""
    cmd = sqlseed_cmd(python)
    for table, count in (("users", 500), ("projects", 200), ("orders", 1000)):
        run([*cmd, "fill", str(DB_PATH), "-t", table, "-n", str(count)])

    print()
    print("  Data fill complete!")


def _run_ai_analysis_step(args: argparse.Namespace, python: str) -> None:
    """Run the Gemma 4 AI schema analysis step."""
    print("[5/5] Gemma 4 AI Schema Analysis...")
    print(f"  Backend: {args.backend}")
    print(f"  Model:   {args.model}")
    print()

    os.environ["SQLSEED_AI_BACKEND"] = args.backend
    os.environ["SQLSEED_AI_MODEL"] = args.model

    ai_ok = False
    if args.backend == "lm_studio":
        if check_lm_studio():
            ai_ok = True
        else:
            print("  Skipped: LM Studio is not running")
            print("  Please start LM Studio and load a Gemma 4 model")
            print("  Download: https://lmstudio.ai/")
    elif args.backend == "ollama":
        if check_ollama():
            ai_ok = True
        else:
            print("  Skipped: Ollama is not running")
            print("  Example: ollama pull gemma4:4b")
    elif args.backend == "google":
        if os.environ.get("GOOGLE_API_KEY"):
            ai_ok = True
        else:
            print("  Skipped: GOOGLE_API_KEY not set")
            print("  Example: export GOOGLE_API_KEY=your-key")

    if ai_ok:
        output_yaml = str(PROJECT_ROOT / "projects_config.yaml")
        cmd = sqlseed_cmd(python)
        run([*cmd, "ai-suggest", str(DB_PATH), "-t", "projects", "-o", output_yaml, "--timeout", "300"])


def main() -> None:
    parser = argparse.ArgumentParser(description="GemmaSQLSeed one-click setup")
    parser.add_argument(
        "--backend",
        choices=["lm_studio", "ollama", "google"],
        default=os.environ.get("SQLSEED_AI_BACKEND", "lm_studio"),
        help="AI backend (default: lm_studio)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("SQLSEED_AI_MODEL", "google/gemma-4-e4b"),
        help="Model name (default: google/gemma-4-e4b)",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip dependency installation, use current Python environment",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("  GemmaSQLSeed Quick Start")
    print("=" * 50)
    print()

    # Determine which python to use
    if args.skip_install:
        # Use current Python (already has sqlseed installed)
        python = sys.executable
        print("[1/5] Using current Python environment (skip-install)")
        print("[2/5] Skipping installation (--skip-install)")
    else:
        # Create venv and install
        venv_path = PROJECT_ROOT / ".venv"
        if not venv_path.exists():
            print("[1/5] Creating virtual environment...")
            run([sys.executable, "-m", "venv", str(venv_path)])
        else:
            print("[1/5] Virtual environment exists, skipping")

        if sys.platform == "win32":
            python = str(venv_path / "Scripts" / "python.exe")
        else:
            python = str(venv_path / "bin" / "python")

        print("[2/5] Installing dependencies (may take a few minutes on first run)...")
        run([python, "-m", "pip", "install", "-q", "-e", f"{PROJECT_ROOT}[dev,all]"])
        run([python, "-m", "pip", "install", "-q", "-e", str(PROJECT_ROOT / "plugins" / "sqlseed-ai")])
        run([python, "-m", "pip", "install", "-q", "-e", str(PROJECT_ROOT / "plugins" / "mcp-server-sqlseed")])

    # ── Step 3: Create test database ─────────────────────────────────
    print("[3/5] Creating test database...")
    if DB_PATH.exists():
        DB_PATH.unlink()

    create_db_script = Path(__file__).parent / "_create_demo_db.py"
    run([python, str(create_db_script), str(DB_PATH)])

    # ── Step 4: Fill data ────────────────────────────────────────────
    print("[4/5] Filling data (zero-config)...")
    _fill_data(python)

    # ── Step 5: Gemma 4 AI analysis ──────────────────────────────────
    _run_ai_analysis_step(args, python)

    # ── Done ─────────────────────────────────────────────────────────
    print()
    print("=" * 50)
    print("  Setup Complete!")
    print("=" * 50)
    print()
    print(f"  Database:    {DB_PATH}")
    cli_call = 'python -c "from sqlseed.cli.main import cli; cli()" --'
    print(f"  Preview:     {cli_call} preview {DB_PATH} -t users -n 5")
    print(f"  Inspect:     {cli_call} inspect {DB_PATH} --show-mapping")
    print(f"  AI Suggest:  {cli_call} ai-suggest {DB_PATH} -t users -o config.yaml")
    print("  MCP Server:  mcp-server-sqlseed")
    print()


if __name__ == "__main__":
    main()
