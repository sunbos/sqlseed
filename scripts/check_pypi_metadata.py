"""Capture public release metadata and verify pip reports against PyPI file hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import urlopen

PACKAGES = ("sqlseed", "sqlseed-cli", "sqlseed-ai", "mcp-server-sqlseed", "sqlseed-web")


def require(condition: bool, message: str) -> None:
    """Reject incomplete releases or installation evidence with a useful error."""
    if not condition:
        raise RuntimeError(message)


def normalize_name(name: str) -> str:
    """Use the package index normalization for distribution names."""
    return re.sub(r"[-_.]+", "-", name).lower()


def snapshot_release(version: str, destination: Path) -> None:
    """Save the five official JSON documents, descriptions and validated hashes."""
    destination.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "version": version,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "packages": {},
    }
    for package in PACKAGES:
        endpoint = f"https://pypi.org/pypi/{package}/{quote(version, safe='')}/json"
        try:
            with urlopen(endpoint, timeout=30) as response:
                raw = response.read()
        except HTTPError as exc:
            raise RuntimeError(f"PyPI release unavailable: {package}=={version} (HTTP {exc.code}, {endpoint})") from exc
        (destination / f"{package}.json").write_bytes(raw)
        document = json.loads(raw)
        info = document["info"]
        require(info["version"] == version, f"PyPI returned a different version for {package}")
        require(normalize_name(info["name"]) == package, f"PyPI returned another package for {package}")
        description = info.get("description", "")
        require(bool(description.strip()), f"{package} has no public description")
        (destination / f"{package}-description.md").write_text(description, encoding="utf-8")
        files = document["urls"]
        require(bool(files), f"No public files for {package}=={version}")
        require(not any(item["yanked"] for item in files), f"{package}=={version} contains yanked files")
        require(
            {"bdist_wheel", "sdist"}.issubset({item["packagetype"] for item in files}),
            f"{package}=={version} requires both a public wheel and sdist",
        )
        for item in files:
            parsed = urlparse(item["url"])
            require(
                parsed.scheme == "https" and parsed.hostname == "files.pythonhosted.org",
                f"Unexpected public artifact origin: {package}",
            )
            require(
                bool(re.fullmatch(r"[0-9a-f]{64}", item["digests"]["sha256"])),
                f"Missing or invalid SHA256 for {item['filename']}",
            )
        summary["packages"][package] = {
            "json_url": endpoint,
            "project_url": f"https://pypi.org/project/{package}/{quote(version, safe='')}/",
            "description_sha256": hashlib.sha256(description.encode("utf-8")).hexdigest(),
            "project_urls": info.get("project_urls"),
            "requires_python": info.get("requires_python"),
            "requires_dist": info.get("requires_dist"),
            "provides_extra": info.get("provides_extra"),
            "license_expression": info.get("license_expression"),
            "license_files": info.get("license_files"),
            "files": files,
        }
        print(f"Captured public wheel, sdist and description: {package}=={version}")
    (destination / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def verify_install_report(version: str, destination: Path, report_path: Path, kind: str, packages: list[str]) -> None:
    """Require exact public versions and artifact SHA256 matches in a pip report."""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    records = {
        normalize_name(item["metadata"]["name"]): item
        for item in report["install"]
        if normalize_name(item["metadata"]["name"]) in PACKAGES
    }
    require(set(records) == set(packages), f"Unexpected sqlseed packages in {report_path}: {set(records)}")
    expected_type = "bdist_wheel" if kind == "wheel" else "sdist"
    for package in packages:
        record = records[package]
        require(record["metadata"]["version"] == version, f"Wrong installed version for {package}")
        document = json.loads((destination / f"{package}.json").read_text(encoding="utf-8"))
        require(document["info"]["version"] == version, f"Stale metadata snapshot for {package}")
        artifact = record["download_info"]
        matching = [item for item in document["urls"] if item["url"] == artifact["url"]]
        require(len(matching) == 1, f"{package} was not installed from the captured public PyPI release")
        expected = matching[0]
        require(expected["packagetype"] == expected_type, f"{package} did not use the requested {kind}")
        actual_hash = artifact.get("archive_info", {}).get("hashes", {}).get("sha256")
        require(actual_hash == expected["digests"]["sha256"], f"Artifact SHA256 mismatch for {package}")
        require(
            not record.get("is_direct", False), f"Direct/local installation is not public index evidence: {package}"
        )
    print(f"Verified {len(packages)} exact public {kind} origins and hashes: {report_path}")


def main() -> None:
    """Capture metadata by default, or validate a saved pip install report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Exact public version, for example 0.2.4")
    parser.add_argument("destination", type=Path, help="Directory for public release evidence")
    parser.add_argument("--report", type=Path, help="Validate this pip --report JSON instead of fetching metadata")
    parser.add_argument("--kind", choices=("wheel", "sdist"))
    parser.add_argument("--packages", nargs="+", choices=PACKAGES, default=list(PACKAGES))
    arguments = parser.parse_args()
    require(
        bool(re.fullmatch(r"[0-9][0-9A-Za-z.!-]*", arguments.version)),
        "Pass one exact public version without local suffixes, wildcards or requirement operators",
    )
    if arguments.report:
        if not arguments.kind:
            parser.error("--report requires --kind")
        verify_install_report(
            arguments.version, arguments.destination, arguments.report, arguments.kind, arguments.packages
        )
    else:
        if arguments.kind:
            parser.error("--kind requires --report")
        snapshot_release(arguments.version, arguments.destination)


if __name__ == "__main__":
    main()
