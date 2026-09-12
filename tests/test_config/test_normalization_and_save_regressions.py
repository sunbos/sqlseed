from __future__ import annotations

from collections import UserDict
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from sqlseed.config.loader import load_config, save_config
from sqlseed.config.models import ColumnConfig, GeneratorConfig, TableConfig

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("params", ["min_value: 10", [10, 20], 10, False])
def test_non_mapping_params_are_rejected_instead_of_losing_the_requested_rules(params: object) -> None:
    with pytest.raises(ValidationError, match="params"):
        ColumnConfig.model_validate({"name": "amount", "generator": "integer", "params": params})


def test_source_params_null_and_mapping_normalization_keep_existing_compatibility() -> None:
    assert ColumnConfig(name="amount", generator="integer", params=None).params == {}
    column = ColumnConfig.model_validate(
        {"name": "amount", "type": "integer", "params": UserDict({"min_value": 10, "max_value": 20}), "max_value": 15}
    )
    assert column.generator == "integer"
    assert column.params == {"min_value": 10, "max_value": 15}


def test_invalid_yaml_params_fail_during_loading(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        'db_path: app.db\ntables:\n- name: users\n  columns:\n  - name: amount\n    params: "min_value: 10"\n'
    )
    with pytest.raises(ValidationError, match="params"):
        load_config(str(path))


@pytest.mark.parametrize("suffix", [".txt", ".db"])
def test_unsupported_save_formats_do_not_truncate_existing_files(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"existing{suffix}"
    original = b"existing contents must survive rejected saves"
    path.write_bytes(original)
    config = GeneratorConfig(db_path="app.db")
    path_string = str(path)
    with pytest.raises(ValueError, match="Unsupported"):
        save_config(config, path_string)
    assert path.read_bytes() == original


def test_unsupported_save_format_does_not_create_directories_or_files(tmp_path: Path) -> None:
    path = tmp_path / "new-directory" / "config.unsupported"
    config = GeneratorConfig(db_path="app.db")
    path_string = str(path)
    with pytest.raises(ValueError, match="Unsupported"):
        save_config(config, path_string)
    assert not path.parent.exists()


def test_json_encoding_failure_does_not_truncate_the_previous_configuration(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    original = GeneratorConfig(db_path="app.db")
    save_config(original, str(path))
    previous_bytes = path.read_bytes()
    invalid = GeneratorConfig(db_path="app.db", tables=[TableConfig(name="\ud800")])
    with pytest.raises(UnicodeEncodeError):
        save_config(invalid, str(path))
    assert path.read_bytes() == previous_bytes
    assert load_config(str(path)) == original
