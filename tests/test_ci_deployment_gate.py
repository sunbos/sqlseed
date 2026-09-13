"""Keep public documentation deployments behind the complete CI result."""

from __future__ import annotations

from pathlib import Path

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
