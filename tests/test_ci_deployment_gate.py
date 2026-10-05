"""Keep protected checks and documentation behind the complete CI result."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def test_pages_deployment_waits_for_every_ci_job_on_main() -> None:
    workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    ci = yaml.safe_load((workflows / "ci.yml").read_text(encoding="utf-8"))
    jobs = ci["jobs"]
    assert "docs" in jobs
    deployment = jobs["docs"]
    assert set(deployment["needs"]) == set(jobs) - {"docs"}
    assert deployment["if"] == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    assert deployment["uses"] == "./.github/workflows/mkdocs-deploy.yml"

    pages = yaml.safe_load((workflows / "mkdocs-deploy.yml").read_text(encoding="utf-8"))
    # PyYAML's YAML 1.1 loader treats the Actions key `on` as boolean true.
    triggers = pages.get("on", pages.get(True))
    assert set(triggers) == {"workflow_call"}
    assert pages["jobs"]["deploy"]["needs"] == "build"


def test_platform_matrix_retains_unique_names_and_protected_windows_check() -> None:
    """Branch protection consumes check names as a stable external contract."""
    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    jobs = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]
    compat = jobs["test-compat"]
    names = {
        row["os"] + ":" + row["python-version"]: compat["name"].replace(
            "${{ matrix.display-name }}", row["display-name"]
        )
        for row in compat["strategy"]["matrix"]["include"]
    }
    assert len(set(names.values())) == len(names)
    assert names["windows-latest:3.12"] == "test-compat (windows-latest)"


@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "skipped"])
def test_protected_macos_check_requires_the_complete_matrix(result: str) -> None:
    """Run the gate's actual script for every upstream terminal result."""
    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    jobs = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]
    gate = next(job for job in jobs.values() if job.get("name") == "test-compat (macos-latest)")
    assert gate["needs"] == "test-compat"
    assert gate["if"] == "always()"
    assert gate["steps"][0]["shell"] == "python"
    command = gate["steps"][0]["run"].replace("${{ needs.test-compat.result }}", result)
    completed = subprocess.run([sys.executable, "-c", command], capture_output=True, text=True, check=False)
    assert (completed.returncode == 0) == (result == "success")
