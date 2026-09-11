from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("package", ["mimesis", "faker"])
def test_registry_reports_the_actual_dependency_import_result(package: str) -> None:
    """Exercise initial package import without uninstalling the test environment."""
    program = textwrap.dedent(
        """
        import importlib.abc
        import json
        import sys

        package = sys.argv[1]
        class MissingDependency(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == package or fullname.startswith(package + '.'):
                    raise ModuleNotFoundError('Unavailable test dependency: ' + fullname)
        sys.meta_path.insert(0, MissingDependency())

        from sqlseed.generators import registry
        providers = registry.ProviderRegistry()
        try:
            providers.ensure_provider(package)
        except ImportError as error:
            message = str(error)
        else:
            raise RuntimeError('Unavailable provider was instantiated')
        print(json.dumps({
            'available': getattr(registry, 'HAS_' + package.upper()),
            'base_value': providers.get('base').generate('integer', min_value=7, max_value=7),
            'registered': providers.available_providers,
            'message': message,
        }))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program, package],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    status = json.loads(result.stdout)
    assert status["available"] is False
    assert status["base_value"] == 7
    assert status["registered"] == ["base"]
    assert "Install" in status["message"]
    if package == "faker":
        assert "sqlseed[faker]" not in status["message"], "Faker is required; that extra does not exist"
