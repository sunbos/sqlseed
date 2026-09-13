#!/usr/bin/env bash
# Verify a published five-package release. Recommended: Linux with Python 3.12.
# PYTHON_BIN=/path/to/python3.12 bash scripts/verify_pypi_release.sh 0.2.4
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: PYTHON_BIN=python3.12 bash $0 <exact-public-version>" >&2
  exit 2
fi

release_version="$1"
release_python="${PYTHON_BIN:-python3}"
script_dir="$(cd "$(dirname "$0")" && pwd)"
release_root="$(mktemp -d "${TMPDIR:-/tmp}/sqlseed-pypi-acceptance.XXXXXX")"
trap 'echo "Acceptance evidence and environments retained at: $release_root"' EXIT
exec > >(tee "$release_root/verification.log") 2>&1
cd "$release_root"

# Isolate every generated database, settings document and cache. Real LLM calls
# are a separate acceptance step; never inherit their credentials in this smoke.
export SQLSEED_CACHE_DIR="$release_root/cache"
export SQLSEED_WEB_WORKSPACE_PATH="$release_root/workspace.sqlite3"
export SQLSEED_WEB_SETTINGS_PATH="$release_root/settings.json"
# --isolated still reads global pip configuration. Disable every config file so
# global target/prefix/index settings cannot escape these temporary environments.
export PIP_CONFIG_FILE=/dev/null
unset PYTHONPATH SQLSEED_AI_API_KEY SQLSEED_AI_BASE_URL SQLSEED_AI_BACKEND SQLSEED_AI_MODEL
unset GOOGLE_API_KEY OPENAI_API_KEY OPENAI_BASE_URL

package_names="sqlseed,sqlseed-cli,sqlseed-ai,mcp-server-sqlseed,sqlseed-web"
packages=(
  "sqlseed==$release_version"
  "sqlseed-cli==$release_version"
  "sqlseed-ai[mcp]==$release_version"
  "mcp-server-sqlseed==$release_version"
  "sqlseed-web==$release_version"
)

"$release_python" "$script_dir/check_pypi_metadata.py" "$release_version" "$release_root/metadata"

"$release_python" -m venv "$release_root/full"
full_python="$release_root/full/bin/python"
"$full_python" -m pip install --isolated --index-url https://pypi.org/simple --no-cache-dir \
  --only-binary="$package_names" --report "$release_root/full-install.json" "${packages[@]}"
"$full_python" "$script_dir/check_pypi_metadata.py" "$release_version" "$release_root/metadata" \
  --report "$release_root/full-install.json" --kind wheel
"$full_python" -m pip check
"$release_root/full/bin/sqlseed" --help
"$release_root/full/bin/sqlseed-web" --help
"$full_python" "$script_dir/check_wheel_install.py"
"$full_python" "$script_dir/check_public_entrypoints.py" "$release_version"

"$release_python" -m venv "$release_root/minimal"
minimal_python="$release_root/minimal/bin/python"
"$minimal_python" -m pip install --isolated --index-url https://pypi.org/simple --no-cache-dir \
  --only-binary="$package_names" --report "$release_root/minimal-install.json" \
  "sqlseed==$release_version" "sqlseed-web==$release_version"
"$minimal_python" "$script_dir/check_pypi_metadata.py" "$release_version" "$release_root/metadata" \
  --report "$release_root/minimal-install.json" --kind wheel --packages sqlseed sqlseed-web
"$minimal_python" -m pip check
"$minimal_python" "$script_dir/check_wheel_install.py" --without-optional-components

"$release_python" -m venv "$release_root/sdist"
sdist_python="$release_root/sdist/bin/python"
"$sdist_python" -m pip install --isolated --index-url https://pypi.org/simple --no-cache-dir \
  --no-binary="$package_names" --report "$release_root/sdist-install.json" "${packages[@]}"
"$sdist_python" "$script_dir/check_pypi_metadata.py" "$release_version" "$release_root/metadata" \
  --report "$release_root/sdist-install.json" --kind sdist
"$sdist_python" -m pip check
"$sdist_python" "$script_dir/check_wheel_install.py"
"$sdist_python" "$script_dir/check_public_entrypoints.py" "$release_version"

echo "Public wheel/full, wheel/minimal and sdist acceptance passed for $release_version."
echo "Not tested here: real LLM inference, PostgreSQL, browser rendering and README link contents."
