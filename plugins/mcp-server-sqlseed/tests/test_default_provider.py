from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def test_mcp_uses_faker_en_us_without_mimesis(tmp_path: Path) -> None:
    """Compare real SQLite values with upstream Faker, including default mapping."""
    program = textwrap.dedent(
        """
        import importlib.abc
        import json
        import sys

        class MissingMimesis(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == 'mimesis' or fullname.startswith('mimesis.'):
                    raise ModuleNotFoundError('Unavailable test dependency: ' + fullname)
        sys.meta_path.insert(0, MissingMimesis())

        from faker import Faker
        from structlog.testing import capture_logs
        import yaml

        with capture_logs() as events:
            from mcp_server_sqlseed.server import sqlseed_execute_fill, sqlseed_generate_yaml
            from sqlseed.core.orchestrator import DataOrchestrator
            from sqlseed.generators import registry
            from tests.sqlite_helpers import sqlite_connection

            database = sys.argv[1]
            seed = 31415
            count = 5
            with sqlite_connection(database) as connection:
                connection.execute('CREATE TABLE people (first_name TEXT NOT NULL)')

            template = yaml.safe_load(sqlseed_generate_yaml(database, 'people'))
            template_defaults = {key: template[key] for key in ('provider', 'locale')}
            expected_faker = Faker('en_US')
            expected_faker.seed_instance(seed)
            expected = [expected_faker.first_name() for _ in range(count)]

            def read_names():
                with sqlite_connection(database) as connection:
                    return [row[0] for row in connection.execute(
                        'SELECT first_name FROM people ORDER BY rowid'
                    )]

            # No YAML: use the upstream seed API, without replacing the provider.
            Faker.seed(seed)
            default_result = sqlseed_execute_fill(database, 'people', count=count)
            default_names = read_names()

            table = template['tables'][0]
            table['seed'] = seed
            table['clear_before'] = True
            generated_result = sqlseed_execute_fill(
                database, 'people', count=count, yaml_config=yaml.safe_dump(template)
            )
            generated_names = read_names()

            # Top-level engine/locale settings remain outside the tool's YAML scope.
            template['provider'] = 'mimesis'
            template['locale'] = 'zh_CN'
            overridden_result = sqlseed_execute_fill(
                database, 'people', count=count, yaml_config=yaml.safe_dump(template)
            )
            overridden_names = read_names()
            tool_warnings = [event for event in events if event['log_level'] == 'warning']

            # Positive control: the explicit unavailable Core provider still warns.
            events.clear()
            with DataOrchestrator(database, provider_name='mimesis') as orchestrator:
                tables = orchestrator.get_table_names()
            fallback_warnings = [event for event in events if event['log_level'] == 'warning']

        print(json.dumps({
            'mimesis_available': registry.HAS_MIMESIS,
            'template_defaults': template_defaults,
            'expected': expected,
            'names': [default_names, generated_names, overridden_names],
            'results': [default_result, generated_result, overridden_result],
            'tool_warnings': tool_warnings,
            'fallback_warnings': fallback_warnings,
            'tables': tables,
        }))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path / "faker-default.db")],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    status = json.loads(result.stdout)
    assert status["mimesis_available"] is False
    assert status["template_defaults"] == {"provider": "faker", "locale": "en_US"}
    assert status["names"] == [status["expected"]] * 3
    for fill_result in status["results"]:
        assert fill_result["count"] == 5
        assert fill_result["errors"] == []
    assert status["tool_warnings"] == []
    assert status["tables"] == ["people"]
    assert any(
        event["event"] == "Provider not available, falling back to 'base'" and event["provider_name"] == "mimesis"
        for event in status["fallback_warnings"]
    )
