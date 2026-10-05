"""Tests for hardware detection in sqlseed_ai._hardware.

Covers platform-specific RAM detection (Windows/Linux/macOS), GPU detection
(nvidia-smi, macOS system_profiler), the GPU dispatcher, caching behavior,
and the public detect_hardware() / evaluate_model_status() APIs. All system
calls (ctypes, subprocess, file I/O) are mocked — no real hardware probing.
"""

from __future__ import annotations

import builtins
import ctypes
import io
import json
import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from tests.assertions import assert_empty

try:
    from sqlseed_ai import _hardware
    from sqlseed_ai._hardware import (
        _detect_gpu_macos,
        _detect_gpu_nvidia,
        _detect_gpus,
        _detect_system_ram,
        _get_ram_linux,
        _get_ram_macos,
        _get_ram_windows,
        detect_hardware,
        evaluate_model_status,
    )
except ImportError:
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)


@pytest.fixture(autouse=True)
def _reset_hardware_cache() -> None:
    """Clear the hardware cache before and after each test."""
    _hardware._HardwareCache.data = None
    yield
    _hardware._HardwareCache.data = None


# ── Windows RAM ──────────────────────────────────────────────────────


class TestGetRamWindows:
    def test_returns_total_and_available_gb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_ram_windows returns (total_gb, available_gb) via Win32 API."""

        def fake_global_memory_status(stat: Any) -> None:
            stat.ullTotalPhys = 16 * 1024**3  # 16 GB
            stat.ullAvailPhys = 8 * 1024**3  # 8 GB

        mock_kernel32 = MagicMock()
        mock_kernel32.GlobalMemoryStatusEx.side_effect = fake_global_memory_status
        mock_windll = MagicMock()
        mock_windll.kernel32 = mock_kernel32
        # On non-Windows, ctypes.windll does not exist; raising=False allows the set.
        monkeypatch.setattr(ctypes, "windll", mock_windll, raising=False)
        # byref returns the stat directly so the mock can mutate its fields
        monkeypatch.setattr(ctypes, "byref", lambda obj: obj)

        result = _get_ram_windows()
        assert result == (16.0, 8.0)

    def test_returns_none_when_windll_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_ram_windows returns None when ctypes.windll is not available (non-Windows)."""
        monkeypatch.delattr(ctypes, "windll", raising=False)
        assert _get_ram_windows() is None

    def test_returns_none_on_os_error_from_global_memory_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_ram_windows returns None when GlobalMemoryStatusEx raises OSError."""
        mock_kernel32 = MagicMock()
        mock_kernel32.GlobalMemoryStatusEx.side_effect = OSError("call failed")
        mock_windll = MagicMock()
        mock_windll.kernel32 = mock_kernel32
        monkeypatch.setattr(ctypes, "windll", mock_windll, raising=False)
        monkeypatch.setattr(ctypes, "byref", lambda obj: obj)
        assert _get_ram_windows() is None


# ── Linux RAM ────────────────────────────────────────────────────────


class TestGetRamLinux:
    def test_parses_memtotal_and_memavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_ram_linux parses MemTotal and MemAvailable from /proc/meminfo."""
        meminfo_content = "MemTotal:       16384000 kB\nMemFree:         2000000 kB\nMemAvailable:    8192000 kB\n"
        real_open = builtins.open

        def fake_open(path: str, *args: Any, **kwargs: Any) -> Any:
            if path == "/proc/meminfo":
                return io.StringIO(meminfo_content)
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", fake_open)

        result = _get_ram_linux()
        # 16384000 kB / 1024^2 = 15.625 GB -> 15.6
        # 8192000 kB / 1024^2 = 7.8125 GB -> 7.8
        assert result == (15.6, 7.8)

    def test_returns_none_when_file_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_ram_linux returns None when /proc/meminfo does not exist."""

        def fake_open(path: str, *args: Any, **kwargs: Any) -> Any:
            raise FileNotFoundError(path)

        monkeypatch.setattr(builtins, "open", fake_open)
        assert _get_ram_linux() is None

    def test_returns_none_on_malformed_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_ram_linux returns None when a meminfo line is malformed (IndexError)."""
        meminfo_content = "MemTotal:\n"  # No value -> IndexError on parts[1]
        monkeypatch.setattr(builtins, "open", lambda p, *a, **k: io.StringIO(meminfo_content))
        assert _get_ram_linux() is None


# ── macOS RAM ────────────────────────────────────────────────────────


class TestGetRamMacos:
    def test_returns_total_and_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_ram_macos returns (total_gb, available_gb) via sysctl and vm_stat."""
        sysctl_result = MagicMock()
        sysctl_result.returncode = 0
        sysctl_result.stdout = f"{16 * 1024**3}\n"  # 16 GB in bytes

        vm_stat_result = MagicMock()
        vm_stat_result.returncode = 0
        vm_stat_result.stdout = (
            "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
            "Pages free:                          100000.\n"
            "Pages speculative:                   50000.\n"
        )

        def fake_run(cmd: list[str], **_kwargs: Any) -> Any:
            if "sysctl" in cmd:
                return sysctl_result
            if "vm_stat" in cmd:
                return vm_stat_result
            return MagicMock(returncode=1, stdout="")

        monkeypatch.setattr(_hardware.subprocess, "run", fake_run)
        monkeypatch.setattr(_hardware.platform, "machine", lambda: "arm64")

        result = _get_ram_macos()
        assert result is not None
        assert result[0] == 16.0  # total
        # (100000 + 50000) * 16384 / 1024^3 = 2.2888... -> 2.3
        assert result[1] == pytest.approx(2.3, abs=0.1)

    def test_returns_zero_available_when_vm_stat_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_ram_macos returns avail=0.0 when vm_stat fails but sysctl succeeds."""
        sysctl_result = MagicMock()
        sysctl_result.returncode = 0
        sysctl_result.stdout = f"{16 * 1024**3}\n"

        vm_stat_result = MagicMock()
        vm_stat_result.returncode = 1  # failure
        vm_stat_result.stdout = ""

        def fake_run(cmd: list[str], **_kwargs: Any) -> Any:
            if "sysctl" in cmd:
                return sysctl_result
            return vm_stat_result

        monkeypatch.setattr(_hardware.subprocess, "run", fake_run)

        result = _get_ram_macos()
        assert result is not None
        assert result[0] == 16.0
        assert result[1] == 0.0

    def test_returns_none_when_sysctl_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_ram_macos returns None when sysctl returns non-zero exit code."""
        sysctl_result = MagicMock()
        sysctl_result.returncode = 1
        sysctl_result.stdout = ""

        monkeypatch.setattr(_hardware.subprocess, "run", lambda cmd, **kw: sysctl_result)
        assert _get_ram_macos() is None

    def test_returns_none_when_sysctl_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get_ram_macos returns None when sysctl binary is not installed."""

        def raise_fnf(cmd: list[str], **kwargs: Any) -> Any:
            raise FileNotFoundError("sysctl")

        monkeypatch.setattr(_hardware.subprocess, "run", raise_fnf)
        assert _get_ram_macos() is None


# ── System RAM dispatcher ────────────────────────────────────────────


class TestDetectSystemRam:
    def test_dispatches_to_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_hardware.platform, "system", lambda: "Windows")
        monkeypatch.setattr(_hardware, "_get_ram_windows", lambda: (16.0, 8.0))
        assert _detect_system_ram() == {"total_gb": 16.0, "available_gb": 8.0}

    def test_dispatches_to_linux(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_hardware.platform, "system", lambda: "Linux")
        monkeypatch.setattr(_hardware, "_get_ram_linux", lambda: (16.0, 8.0))
        assert _detect_system_ram() == {"total_gb": 16.0, "available_gb": 8.0}

    def test_dispatches_to_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_hardware.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(_hardware, "_get_ram_macos", lambda: (16.0, 8.0))
        assert _detect_system_ram() == {"total_gb": 16.0, "available_gb": 8.0}

    def test_returns_zeros_for_unknown_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_hardware.platform, "system", lambda: "UnknownOS")
        assert _detect_system_ram() == {"total_gb": 0, "available_gb": 0}

    def test_returns_zeros_when_detection_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_hardware.platform, "system", lambda: "Linux")
        monkeypatch.setattr(_hardware, "_get_ram_linux", lambda: None)
        assert _detect_system_ram() == {"total_gb": 0, "available_gb": 0}


# ── NVIDIA GPU detection ─────────────────────────────────────────────


class TestDetectGpuNvidia:
    def test_parses_nvidia_smi_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpu_nvidia parses nvidia-smi CSV output into GPU dicts."""
        nvidia_output = "NVIDIA GeForce RTX 4090, 24576, 20000, 535.98\n"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = nvidia_output
        monkeypatch.setattr(_hardware.subprocess, "run", lambda cmd, **kw: mock_result)

        gpus = _detect_gpu_nvidia()
        assert len(gpus) == 1
        gpu = gpus[0]
        assert gpu["name"] == "NVIDIA GeForce RTX 4090"
        assert gpu["vram_total_mb"] == 24576
        assert gpu["vram_free_mb"] == 20000
        assert gpu["vram_total_gb"] == 24.0
        assert gpu["driver_version"] == "535.98"
        assert gpu["vendor"] == "nvidia"

    def test_parses_multiple_gpus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpu_nvidia parses multiple GPU lines."""
        nvidia_output = "NVIDIA GeForce RTX 4090, 24576, 20000, 535.98\nNVIDIA GeForce RTX 3090, 24576, 18000, 535.98\n"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = nvidia_output
        monkeypatch.setattr(_hardware.subprocess, "run", lambda cmd, **kw: mock_result)

        gpus = _detect_gpu_nvidia()
        assert len(gpus) == 2
        assert gpus[0]["name"] == "NVIDIA GeForce RTX 4090"
        assert gpus[1]["name"] == "NVIDIA GeForce RTX 3090"

    def test_returns_empty_on_nonzero_returncode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpu_nvidia returns [] when nvidia-smi exits non-zero."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        monkeypatch.setattr(_hardware.subprocess, "run", lambda cmd, **kw: mock_result)
        assert not _detect_gpu_nvidia()

    def test_returns_empty_on_empty_stdout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpu_nvidia returns [] when nvidia-smi produces no output."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        monkeypatch.setattr(_hardware.subprocess, "run", lambda cmd, **kw: mock_result)
        assert not _detect_gpu_nvidia()

    def test_returns_empty_when_nvidia_smi_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpu_nvidia returns [] when nvidia-smi binary is not installed."""

        def raise_fnf(cmd: list[str], **kwargs: Any) -> Any:
            raise FileNotFoundError("nvidia-smi")

        monkeypatch.setattr(_hardware.subprocess, "run", raise_fnf)
        assert not _detect_gpu_nvidia()

    def test_returns_empty_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpu_nvidia returns [] when nvidia-smi times out."""

        def raise_timeout(cmd: list[str], **kwargs: Any) -> Any:
            raise subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=5)

        monkeypatch.setattr(_hardware.subprocess, "run", raise_timeout)
        assert not _detect_gpu_nvidia()

    def test_skips_malformed_lines(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpu_nvidia skips CSV lines with fewer than 4 fields."""
        nvidia_output = "GPU0, 1024, 512\nGPU1, 8192, 4096, 535.0\n"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = nvidia_output
        monkeypatch.setattr(_hardware.subprocess, "run", lambda cmd, **kw: mock_result)

        gpus = _detect_gpu_nvidia()
        assert len(gpus) == 1
        assert gpus[0]["name"] == "GPU1"


# ── macOS GPU detection ──────────────────────────────────────────────


class TestDetectGpuMacos:
    def _stub_macos_profile(self, monkeypatch: pytest.MonkeyPatch, profiler_data: dict[str, Any]) -> MagicMock:
        """Stub subprocess.run to return the given macOS profiler_data JSON."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(profiler_data)
        monkeypatch.setattr(_hardware.subprocess, "run", lambda cmd, **kw: mock_result)
        return mock_result

    def test_parses_system_profiler_json_gb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpu_macos parses SPDisplaysDataType JSON with GB vram."""
        profiler_data = {
            "SPDisplaysDataType": [
                {
                    "sppci_model": "AMD Radeon Pro W6800X",
                    "spdisplays_vendor": "sppci_vendor_amd",
                    "spdisplays_vram": "16 GB",
                }
            ]
        }
        self._stub_macos_profile(monkeypatch, profiler_data)

        gpus = _detect_gpu_macos()
        assert len(gpus) == 1
        gpu = gpus[0]
        assert gpu["name"] == "AMD Radeon Pro W6800X"
        assert gpu["vram_total_mb"] == 16384  # 16 GB -> 16 * 1024
        assert gpu["vram_total_gb"] == 16.0
        assert gpu["vendor"] == "amd"
        assert gpu["vram_free_mb"] == 0  # system_profiler does not report free VRAM

    def test_parses_vram_in_mb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpu_macos treats MB units as megabytes without multiplication."""
        profiler_data = {
            "SPDisplaysDataType": [
                {
                    "sppci_model": "Intel Iris",
                    "spdisplays_vram": "1536 MB",
                }
            ]
        }
        self._stub_macos_profile(monkeypatch, profiler_data)

        gpus = _detect_gpu_macos()
        assert len(gpus) == 1
        assert gpus[0]["vram_total_mb"] == 1536
        assert gpus[0]["vram_total_gb"] == 1.5

    def test_intel_shared_memory_from_real_profiler_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Intel Macs report shared memory and identify Intel as the GPU vendor."""
        self._stub_macos_profile(
            monkeypatch,
            {
                "SPDisplaysDataType": [
                    {
                        "sppci_model": "Intel UHD Graphics 630",
                        "spdisplays_vendor": "Intel",
                        "spdisplays_vram_shared": "1536 MB",
                        "_spdisplays_vram": "1536 MB",
                    }
                ]
            },
        )

        gpu = _detect_gpu_macos()[0]
        assert gpu["vendor"] == "intel"
        assert gpu["memory_type"] == "shared"
        assert gpu["vram_total_gb"] == 1.5

    def test_amd_dedicated_memory_preserves_vendor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An Intel Mac's AMD GPU is not an Apple unified-memory GPU."""
        self._stub_macos_profile(
            monkeypatch,
            {
                "SPDisplaysDataType": [
                    {
                        "sppci_model": "AMD Radeon Pro 5500M",
                        "spdisplays_vendor": "sppci_vendor_amd",
                        "spdisplays_vram": "4 GB",
                    }
                ]
            },
        )

        gpu = _detect_gpu_macos()[0]
        assert gpu["vendor"] == "amd"
        assert gpu["memory_type"] == "dedicated"
        assert gpu["vram_total_gb"] == 4.0

    def test_apple_gpu_marks_unified_memory_without_inventing_vram(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Apple GPUs are identifiable under both native Python and Rosetta."""
        self._stub_macos_profile(
            monkeypatch,
            {"SPDisplaysDataType": [{"sppci_model": "Apple M2", "spdisplays_vendor": "sppci_vendor_Apple"}]},
        )
        monkeypatch.setattr(_hardware.platform, "machine", lambda: "x86_64")

        gpu = _detect_gpu_macos()[0]
        assert gpu["vendor"] == "apple"
        assert gpu["memory_type"] == "unified"
        assert gpu["vram_total_gb"] == 0.0

    @pytest.mark.parametrize("profiler_data", [[], None, {"SPDisplaysDataType": None}, {"SPDisplaysDataType": {}}])
    def test_malformed_profiler_containers_do_not_crash(
        self, profiler_data: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps(profiler_data))
        monkeypatch.setattr(_hardware.subprocess, "run", lambda *args, **kwargs: result)
        assert_empty(_detect_gpu_macos(), list)

    @pytest.mark.parametrize("bad_memory", ["invalid GB", None, ["4", "GB"], "9" * 400 + " GB"])
    def test_bad_gpu_entry_preserves_remaining_cards(self, monkeypatch: pytest.MonkeyPatch, bad_memory: object) -> None:
        self._stub_macos_profile(
            monkeypatch,
            {
                "SPDisplaysDataType": [
                    None,
                    {"sppci_model": "Intel Iris", "spdisplays_vram_shared": bad_memory},
                    {
                        "sppci_model": "AMD Radeon Pro",
                        "spdisplays_vendor": "sppci_vendor_amd",
                        "spdisplays_vram": "4 GB",
                    },
                ]
            },
        )

        gpus = _detect_gpu_macos()
        assert [(gpu["name"], gpu["vram_total_gb"]) for gpu in gpus] == [
            ("Intel Iris", 0.0),
            ("AMD Radeon Pro", 4.0),
        ]

    def test_defaults_vram_to_zero_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpu_macos defaults vram_total_mb to 0 when spdisplays_vram absent."""
        profiler_data = {
            "SPDisplaysDataType": [
                {
                    "sppci_model": "Apple M1",
                }
            ]
        }
        self._stub_macos_profile(monkeypatch, profiler_data)

        gpus = _detect_gpu_macos()
        assert len(gpus) == 1
        assert gpus[0]["vram_total_mb"] == 0
        assert gpus[0]["vram_total_gb"] == 0.0

    def test_defaults_name_to_unknown_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpu_macos defaults name to 'Unknown GPU' when sppci_model absent."""
        profiler_data = {"SPDisplaysDataType": [{}]}
        self._stub_macos_profile(monkeypatch, profiler_data)

        gpus = _detect_gpu_macos()
        assert len(gpus) == 1
        assert gpus[0]["name"] == "Unknown GPU"

    @pytest.mark.parametrize("bad_name", [None, 123, ["Apple M2"], {"name": "Apple M2"}])
    def test_non_string_name_falls_back_without_losing_other_devices(
        self, monkeypatch: pytest.MonkeyPatch, bad_name: object
    ) -> None:
        """Malformed names cannot identify an Apple GPU or discard another valid card."""
        self._stub_macos_profile(
            monkeypatch,
            {
                "SPDisplaysDataType": [
                    {"sppci_model": bad_name, "spdisplays_vram_shared": "1536 MB"},
                    {
                        "sppci_model": "AMD Radeon Pro",
                        "spdisplays_vendor": "sppci_vendor_amd",
                        "spdisplays_vram": "4 GB",
                    },
                ]
            },
        )

        gpus = _detect_gpu_macos()
        assert [(gpu["name"], gpu["vendor"], gpu["memory_type"], gpu["vram_total_gb"]) for gpu in gpus] == [
            ("Unknown GPU", "unknown", "shared", 1.5),
            ("AMD Radeon Pro", "amd", "dedicated", 4.0),
        ]

    def test_returns_empty_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpu_macos returns [] when system_profiler exits non-zero."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        monkeypatch.setattr(_hardware.subprocess, "run", lambda cmd, **kw: mock_result)
        assert not _detect_gpu_macos()

    def test_returns_empty_when_system_profiler_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpu_macos returns [] when system_profiler is not installed."""

        def raise_fnf(cmd: list[str], **kwargs: Any) -> Any:
            raise FileNotFoundError("system_profiler")

        monkeypatch.setattr(_hardware.subprocess, "run", raise_fnf)
        assert not _detect_gpu_macos()


# ── GPU dispatcher ───────────────────────────────────────────────────


class TestDetectGpus:
    def test_returns_nvidia_gpus_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpus returns NVIDIA GPUs when nvidia-smi succeeds."""
        nvidia_gpus = [{"name": "RTX 4090", "vram_total_gb": 24.0, "vendor": "nvidia"}]
        monkeypatch.setattr(_hardware, "_detect_gpu_nvidia", lambda: nvidia_gpus)
        assert _detect_gpus() == nvidia_gpus

    def test_falls_back_to_macos_on_darwin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpus falls back to macOS GPU detection on Darwin without NVIDIA."""
        macos_gpus = [{"name": "Apple M2", "vram_total_gb": 16.0, "vendor": "apple"}]
        monkeypatch.setattr(_hardware, "_detect_gpu_nvidia", lambda: [])
        monkeypatch.setattr(_hardware.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(_hardware, "_detect_gpu_macos", lambda: macos_gpus)
        assert _detect_gpus() == macos_gpus

    def test_returns_empty_when_no_nvidia_and_not_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_detect_gpus returns [] when no NVIDIA GPU on a non-macOS platform."""
        monkeypatch.setattr(_hardware, "_detect_gpu_nvidia", lambda: [])
        monkeypatch.setattr(_hardware.platform, "system", lambda: "Linux")
        assert not _detect_gpus()


# ── Public API: detect_hardware ──────────────────────────────────────


class TestDetectHardware:
    def _stub_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_hardware.platform, "system", lambda: "Linux")
        monkeypatch.setattr(_hardware.platform, "release", lambda: "6.5.0")
        monkeypatch.setattr(_hardware.platform, "machine", lambda: "x86_64")

    def _stub_detect_with_counter(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
        """Stub platform + _detect_system_ram (with counter) + _detect_gpus.

        Returns the ``call_count`` dict-like container so callers can read/verify
        the invocation count after the fact. Use ``counter["n"]`` to read.
        """
        self._stub_platform(monkeypatch)
        counter: dict[str, int] = {"n": 0}

        def mock_detect_ram() -> dict[str, Any]:
            counter["n"] += 1
            return {"total_gb": 16.0, "available_gb": 8.0}

        monkeypatch.setattr(_hardware, "_detect_system_ram", mock_detect_ram)
        monkeypatch.setattr(_hardware, "_detect_gpus", lambda: [])
        return counter

    def test_returns_full_hardware_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """detect_hardware returns platform, ram, gpus, and max_vram_gb."""
        self._stub_platform(monkeypatch)
        monkeypatch.setattr(_hardware, "_detect_system_ram", lambda: {"total_gb": 16.0, "available_gb": 8.0})
        monkeypatch.setattr(_hardware, "_detect_gpus", lambda: [{"name": "RTX", "vram_total_gb": 24.0}])

        result = detect_hardware()
        assert result["platform"] == {
            "system": "Linux",
            "release": "6.5.0",
            "machine": "x86_64",
        }
        assert result["ram"] == {"total_gb": 16.0, "available_gb": 8.0}
        assert len(result["gpus"]) == 1
        assert result["max_vram_gb"] == 24.0

    def test_max_vram_zero_when_no_gpus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """detect_hardware sets max_vram_gb to 0 when no GPUs detected."""
        self._stub_platform(monkeypatch)
        monkeypatch.setattr(_hardware, "_detect_system_ram", lambda: {"total_gb": 16.0, "available_gb": 8.0})
        monkeypatch.setattr(_hardware, "_detect_gpus", lambda: [])

        result = detect_hardware()
        assert result["max_vram_gb"] == 0

    def test_max_vram_picks_largest_gpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """detect_hardware picks the largest vram_total_gb across all GPUs."""
        self._stub_platform(monkeypatch)
        monkeypatch.setattr(_hardware, "_detect_system_ram", lambda: {"total_gb": 32.0, "available_gb": 16.0})
        monkeypatch.setattr(
            _hardware,
            "_detect_gpus",
            lambda: [
                {"name": "GPU0", "vram_total_gb": 8.0},
                {"name": "GPU1", "vram_total_gb": 24.0},
                {"name": "GPU2", "vram_total_gb": 16.0},
            ],
        )

        result = detect_hardware()
        assert result["max_vram_gb"] == 24.0

    def test_caches_result_within_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """detect_hardware caches the result and reuses it on subsequent calls."""
        counter = self._stub_detect_with_counter(monkeypatch)

        first = detect_hardware()
        second = detect_hardware()
        assert first is second  # Same cached object
        assert counter["n"] == 1  # _detect_system_ram only called once

    def test_redetects_after_cache_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """detect_hardware re-detects after the cache TTL (300s) expires."""
        counter = self._stub_detect_with_counter(monkeypatch)

        current_time = 100.0
        monkeypatch.setattr(_hardware.time, "monotonic", lambda: current_time)

        # First call — detects and caches at t=100
        first = detect_hardware()
        assert counter["n"] == 1

        # Second call within TTL — returns cached
        current_time = 200.0
        second = detect_hardware()
        assert counter["n"] == 1
        assert second is first

        # Third call after TTL — re-detects
        current_time = 500.0  # 400s later, > 300s TTL
        detect_hardware()
        assert counter["n"] == 2


# ── Public API: evaluate_model_status ────────────────────────────────


class TestEvaluateModelStatus:
    @pytest.mark.parametrize(
        ("total_ram", "model_id", "expected", "budget"),
        [
            (8.0, "gemma-4-e2b-it", "capable", 4.0),
            (16.0, "gemma-4-26b-a4b-it", "insufficient", 12.0),
            (3.0, "gemma-4-e2b-it", "insufficient", 0.0),
            (32.0, "gemma-4-31b-it", "capable", 24.0),
        ],
    )
    def test_unified_memory_reserves_system_ram(
        self, total_ram: float, model_id: str, expected: str, budget: float, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unified memory shares RAM; total RAM cannot be counted as dedicated VRAM."""
        monkeypatch.setattr(_hardware.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(_hardware, "_detect_system_ram", lambda: {"total_gb": total_ram, "available_gb": 0.0})
        monkeypatch.setattr(
            _hardware,
            "_detect_gpus",
            lambda: [{"name": "Apple M2", "vendor": "apple", "memory_type": "unified", "vram_total_gb": 0.0}],
        )

        hardware = detect_hardware()
        assert evaluate_model_status(model_id, hardware) == expected
        assert hardware["max_vram_gb"] == 0.0
        assert hardware["unified_memory_budget_gb"] == budget

    @pytest.mark.parametrize(("system", "vendor"), [("Linux", "apple"), ("Darwin", "intel")])
    def test_unified_budget_requires_apple_gpu_on_macos(self, system: str, vendor: str) -> None:
        hardware = {
            "platform": {"system": system},
            "ram": {"total_gb": 16.0},
            "max_vram_gb": 0.0,
            "unified_memory_budget_gb": 12.0,
            "gpus": [{"vendor": vendor, "memory_type": "unified"}],
        }
        assert evaluate_model_status("gemma-4-e2b-it", hardware) == "cpu_only"

    def test_recommended_when_vram_meets_recommended(self) -> None:
        """Status is 'recommended' when VRAM meets the recommended threshold."""
        hw = {"max_vram_gb": 4.0, "ram": {"total_gb": 8.0}}
        # gemma-4-e2b-it: recommended_vram_gb=4
        assert evaluate_model_status("gemma-4-e2b-it", hw) == "recommended"

    def test_capable_when_vram_meets_minimum(self) -> None:
        """Status is 'capable' when VRAM meets the minimum but not recommended."""
        hw = {"max_vram_gb": 2.0, "ram": {"total_gb": 8.0}}
        # gemma-4-e2b-it: min_vram_gb=2, recommended_vram_gb=4
        assert evaluate_model_status("gemma-4-e2b-it", hw) == "capable"

    def test_cpu_only_when_no_gpu_but_ram_sufficient(self) -> None:
        """Status is 'cpu_only' when no GPU detected but RAM is sufficient."""
        hw = {"max_vram_gb": 0, "ram": {"total_gb": 8.0}}
        assert evaluate_model_status("gemma-4-e2b-it", hw) == "cpu_only"

    def test_capable_slow_when_ram_ok_but_vram_below_min(self) -> None:
        """Status is 'capable_slow' when RAM ok but VRAM below minimum (offloading)."""
        hw = {"max_vram_gb": 1.0, "ram": {"total_gb": 8.0}}
        assert evaluate_model_status("gemma-4-e2b-it", hw) == "capable_slow"

    def test_insufficient_when_ram_below_minimum(self) -> None:
        """Status is 'insufficient' when RAM is below the minimum requirement."""
        hw = {"max_vram_gb": 0, "ram": {"total_gb": 2.0}}
        assert evaluate_model_status("gemma-4-e2b-it", hw) == "insufficient"

    def test_cloud_only_for_unknown_model(self) -> None:
        """Status is 'cloud_only' for models not in MODEL_REQUIREMENTS."""
        hw = {"max_vram_gb": 0, "ram": {"total_gb": 0}}
        assert evaluate_model_status("unknown-model", hw) == "cloud_only"
