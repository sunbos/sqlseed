"""Tests for ``mcp_server_sqlseed.config`` — MCPServerConfig validation.

Covers default values, valid configurations, port boundary validation,
host non-empty validation, and Pydantic-specific coercion behavior.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from mcp_server_sqlseed.config import MCPServerConfig

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestMCPServerConfigDefaults:
    """Tests for default field values."""

    def test_default_construction(self) -> None:
        """MCPServerConfig can be constructed with no arguments."""
        config = MCPServerConfig()
        assert config.db_path is None
        assert config.host == "127.0.0.1"
        assert config.port == 8000

    def test_db_path_none_by_default(self) -> None:
        """db_path defaults to None."""
        config = MCPServerConfig()
        assert config.db_path is None

    def test_host_default_is_loopback(self) -> None:
        """host defaults to 127.0.0.1."""
        config = MCPServerConfig()
        assert config.host == "127.0.0.1"

    def test_port_default_is_8000(self) -> None:
        """port defaults to 8000."""
        config = MCPServerConfig()
        assert config.port == 8000


# ---------------------------------------------------------------------------
# Valid configurations
# ---------------------------------------------------------------------------


class TestMCPServerConfigValid:
    """Tests for valid configuration combinations."""

    def test_custom_host_and_port(self) -> None:
        """Custom host and port are accepted."""
        config = MCPServerConfig(host="0.0.0.0", port=9000)
        assert config.host == "0.0.0.0"
        assert config.port == 9000

    def test_custom_db_path(self) -> None:
        """A custom db_path is accepted."""
        config = MCPServerConfig(db_path="/path/to/db.sqlite")
        assert config.db_path == "/path/to/db.sqlite"

    def test_db_path_empty_string(self) -> None:
        """An empty string db_path is accepted (str type, not None)."""
        config = MCPServerConfig(db_path="")
        assert config.db_path == ""

    def test_db_path_windows_path(self) -> None:
        """A Windows-style db_path is accepted."""
        config = MCPServerConfig(db_path=r"C:\data\app.db")
        assert config.db_path == r"C:\data\app.db"

    def test_all_fields_combined(self) -> None:
        """All fields can be set together."""
        config = MCPServerConfig(db_path="/data/app.db", host="0.0.0.0", port=3000)
        assert config.db_path == "/data/app.db"
        assert config.host == "0.0.0.0"
        assert config.port == 3000

    def test_host_localhost(self) -> None:
        """'localhost' is a valid host."""
        config = MCPServerConfig(host="localhost")
        assert config.host == "localhost"

    def test_host_ipv6(self) -> None:
        """An IPv6 address is a valid host."""
        config = MCPServerConfig(host="::1")
        assert config.host == "::1"

    def test_host_with_internal_spaces(self) -> None:
        """A host with internal spaces is accepted (only stripped for validation)."""
        config = MCPServerConfig(host="my host")
        assert config.host == "my host"

    def test_host_with_surrounding_whitespace(self) -> None:
        """A host with surrounding whitespace is accepted (validator only checks non-empty)."""
        config = MCPServerConfig(host="  127.0.0.1  ")
        assert config.host == "  127.0.0.1  "

    def test_host_long_string(self) -> None:
        """A long host string is accepted."""
        long_host = "a" * 1000
        config = MCPServerConfig(host=long_host)
        assert config.host == long_host


# ---------------------------------------------------------------------------
# Port validation
# ---------------------------------------------------------------------------


class TestPortValidation:
    """Tests for the port field validator."""

    @pytest.mark.parametrize("port", [1, 80, 443, 3000, 8000, 8080, 65535])
    def test_valid_ports(self, port: int) -> None:
        """Ports in the range 1-65535 are accepted."""
        config = MCPServerConfig(port=port)
        assert config.port == port

    def test_port_boundary_min(self) -> None:
        """Port 1 is the minimum valid port."""
        config = MCPServerConfig(port=1)
        assert config.port == 1

    def test_port_boundary_max(self) -> None:
        """Port 65535 is the maximum valid port."""
        config = MCPServerConfig(port=65535)
        assert config.port == 65535

    @pytest.mark.parametrize("port", [0, -1, -100, -65536, 65536, 100000, 999999])
    def test_invalid_port_raises(self, port: int) -> None:
        """Ports outside 1-65535 raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            MCPServerConfig(port=port)
        assert "port must be 1-65535" in str(exc_info.value)

    def test_port_zero_raises(self) -> None:
        """Port 0 raises ValidationError."""
        with pytest.raises(ValidationError, match="port must be 1-65535"):
            MCPServerConfig(port=0)

    def test_port_negative_raises(self) -> None:
        """Negative ports raise ValidationError."""
        with pytest.raises(ValidationError, match="port must be 1-65535"):
            MCPServerConfig(port=-1)

    def test_port_above_max_raises(self) -> None:
        """Port 65536 raises ValidationError."""
        with pytest.raises(ValidationError, match="port must be 1-65535"):
            MCPServerConfig(port=65536)

    def test_port_error_message_contains_value(self) -> None:
        """The error message contains the invalid port value."""
        with pytest.raises(ValidationError) as exc_info:
            MCPServerConfig(port=70000)
        assert "70000" in str(exc_info.value)

    def test_port_just_below_min_raises(self) -> None:
        """Port 0 (just below min) raises."""
        with pytest.raises(ValidationError):
            MCPServerConfig(port=0)

    def test_port_just_above_max_raises(self) -> None:
        """Port 65536 (just above max) raises."""
        with pytest.raises(ValidationError):
            MCPServerConfig(port=65536)

    def test_port_string_coerced_to_int(self) -> None:
        """Pydantic coerces a numeric string port to int."""
        config = MCPServerConfig(port="8080")
        assert config.port == 8080
        assert isinstance(config.port, int)

    def test_port_invalid_string_raises(self) -> None:
        """A non-numeric port string raises ValidationError."""
        with pytest.raises(ValidationError):
            MCPServerConfig(port="not_a_number")

    def test_port_float_coerced_to_int(self) -> None:
        """Pydantic coerces a float port to int."""
        config = MCPServerConfig(port=8080.0)
        assert config.port == 8080

    def test_port_bool_coerced_to_int(self) -> None:
        """A boolean port is coerced to int (bool is a subclass of int in Python).

        True -> 1 (valid), False -> 0 (invalid, raises ValidationError).
        """
        config = MCPServerConfig(port=True)
        assert config.port == 1
        with pytest.raises(ValidationError, match="port must be 1-65535"):
            MCPServerConfig(port=False)


# ---------------------------------------------------------------------------
# Host validation
# ---------------------------------------------------------------------------


class TestHostValidation:
    """Tests for the host field validator."""

    def test_empty_host_raises(self) -> None:
        """An empty host string raises ValidationError."""
        with pytest.raises(ValidationError, match="host must be non-empty"):
            MCPServerConfig(host="")

    def test_whitespace_only_host_raises(self) -> None:
        """A whitespace-only host string raises ValidationError."""
        with pytest.raises(ValidationError, match="host must be non-empty"):
            MCPServerConfig(host="   ")

    def test_tab_only_host_raises(self) -> None:
        """A tab-only host string raises ValidationError."""
        with pytest.raises(ValidationError, match="host must be non-empty"):
            MCPServerConfig(host="\t\t")

    def test_newline_only_host_raises(self) -> None:
        """A newline-only host string raises ValidationError."""
        with pytest.raises(ValidationError, match="host must be non-empty"):
            MCPServerConfig(host="\n")

    def test_mixed_whitespace_host_raises(self) -> None:
        """A mixed-whitespace host string raises ValidationError."""
        with pytest.raises(ValidationError, match="host must be non-empty"):
            MCPServerConfig(host=" \t\n ")

    def test_single_space_host_raises(self) -> None:
        """A single-space host string raises ValidationError."""
        with pytest.raises(ValidationError, match="host must be non-empty"):
            MCPServerConfig(host=" ")

    def test_host_error_message(self) -> None:
        """The host error message is 'host must be non-empty'."""
        with pytest.raises(ValidationError) as exc_info:
            MCPServerConfig(host="")
        assert "host must be non-empty" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Pydantic model behavior
# ---------------------------------------------------------------------------


class TestMCPServerConfigPydantic:
    """Tests for Pydantic-specific behavior of MCPServerConfig."""

    def test_is_basemodel_subclass(self) -> None:
        """MCPServerConfig is a subclass of pydantic.BaseModel."""
        assert issubclass(MCPServerConfig, BaseModel)

    def test_model_fields_exist(self) -> None:
        """The model has db_path, host, and port fields."""
        field_names = set(MCPServerConfig.model_fields.keys())
        assert "db_path" in field_names
        assert "host" in field_names
        assert "port" in field_names

    def test_model_fields_count(self) -> None:
        """The model has exactly three fields."""
        assert len(MCPServerConfig.model_fields) == 3

    def test_field_assignment_allowed(self) -> None:
        """Pydantic v2 allows field assignment by default (not frozen)."""
        config = MCPServerConfig()
        config.port = 9000
        assert config.port == 9000

    def test_model_dump_returns_dict(self) -> None:
        """model_dump() returns a dict with all fields."""
        config = MCPServerConfig(db_path="/x.db", host="0.0.0.0", port=443)
        dumped = config.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["db_path"] == "/x.db"
        assert dumped["host"] == "0.0.0.0"
        assert dumped["port"] == 443

    def test_model_dump_default_values(self) -> None:
        """model_dump() returns default values when no args given."""
        config = MCPServerConfig()
        dumped = config.model_dump()
        assert dumped == {"db_path": None, "host": "127.0.0.1", "port": 8000}

    def test_model_validate_from_dict(self) -> None:
        """model_validate() constructs an instance from a dict."""
        config = MCPServerConfig.model_validate(
            {"db_path": "/y.db", "host": "localhost", "port": 5000}
        )
        assert config.db_path == "/y.db"
        assert config.host == "localhost"
        assert config.port == 5000

    def test_model_validate_invalid_port_raises(self) -> None:
        """model_validate() raises for an invalid port."""
        with pytest.raises(ValidationError, match="port must be 1-65535"):
            MCPServerConfig.model_validate({"port": 0})

    def test_model_validate_invalid_host_raises(self) -> None:
        """model_validate() raises for an invalid host."""
        with pytest.raises(ValidationError, match="host must be non-empty"):
            MCPServerConfig.model_validate({"host": ""})

    def test_extra_fields_ignored_by_default(self) -> None:
        """Extra fields are ignored by default (Pydantic v2 default behavior)."""
        config = MCPServerConfig.model_validate(
            {"host": "1.2.3.4", "port": 80, "extra_field": "ignored"}
        )
        assert config.host == "1.2.3.4"
        assert config.port == 80
        assert not hasattr(config, "extra_field")

    def test_repr_contains_class_name(self) -> None:
        """repr() includes the class name."""
        config = MCPServerConfig()
        assert "MCPServerConfig" in repr(config)

    def test_equality_same_values(self) -> None:
        """Two configs with the same values are equal."""
        a = MCPServerConfig(db_path="/x.db", host="0.0.0.0", port=80)
        b = MCPServerConfig(db_path="/x.db", host="0.0.0.0", port=80)
        assert a == b

    def test_inequality_different_port(self) -> None:
        """Two configs with different ports are not equal."""
        a = MCPServerConfig(port=80)
        b = MCPServerConfig(port=81)
        assert a != b

    def test_inequality_different_host(self) -> None:
        """Two configs with different hosts are not equal."""
        a = MCPServerConfig(host="a")
        b = MCPServerConfig(host="b")
        assert a != b

    def test_inequality_different_db_path(self) -> None:
        """Two configs with different db_paths are not equal."""
        a = MCPServerConfig(db_path="/a.db")
        b = MCPServerConfig(db_path="/b.db")
        assert a != b


# ---------------------------------------------------------------------------
# Combined validation
# ---------------------------------------------------------------------------


class TestCombinedValidation:
    """Tests for combined field validation scenarios."""

    def test_both_host_and_port_invalid_reports_both(self) -> None:
        """When both host and port are invalid, both errors are in the exception."""
        with pytest.raises(ValidationError) as exc_info:
            MCPServerConfig(host="", port=0)
        error_str = str(exc_info.value)
        assert "host must be non-empty" in error_str
        assert "port must be 1-65535" in error_str

    def test_valid_db_path_with_invalid_port(self) -> None:
        """A valid db_path does not mask an invalid port."""
        with pytest.raises(ValidationError, match="port must be 1-65535"):
            MCPServerConfig(db_path="/valid.db", port=0)

    def test_invalid_host_with_valid_port(self) -> None:
        """An invalid host does not mask a valid port."""
        with pytest.raises(ValidationError, match="host must be non-empty"):
            MCPServerConfig(host="", port=8080)

    def test_db_path_does_not_affect_validation(self) -> None:
        """db_path is not validated, so any string is accepted."""
        config = MCPServerConfig(db_path="anything/here/with spaces")
        assert config.db_path == "anything/here/with spaces"
