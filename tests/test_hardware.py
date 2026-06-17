from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

try:
    import sqlseed_ai._hardware as hw_mod
    from sqlseed_ai._hardware import (
        detect_hardware,
        evaluate_model_status,
    )

    HAS_HARDWARE = True
except ImportError:
    HAS_HARDWARE = False

if not HAS_HARDWARE:
    pytest.skip("sqlseed-ai plugin not installed", allow_module_level=True)


class TestHardwareDetection:
    @patch("platform.system")
    def test_detect_hardware_windows(self, mock_system: MagicMock) -> None:
        mock_system.return_value = "Windows"

        # Mock GlobalMemoryStatusEx using ctypes
        with (
            patch("sqlseed_ai._hardware._get_ram_windows") as mock_ram,
            patch("sqlseed_ai._hardware._detect_gpus") as mock_gpus,
        ):
            mock_ram.return_value = (16.0, 8.0)
            mock_gpus.return_value = [
                {
                    "name": "NVIDIA GeForce RTX 3080",
                    "vram_total_mb": 10240,
                    "vram_free_mb": 5120,
                    "vram_total_gb": 10.0,
                    "driver_version": "511.65",
                    "vendor": "nvidia",
                }
            ]

            # Reset cache before calling
            hw_mod._HardwareCache.data = None

            result = detect_hardware()
            assert result["platform"]["system"] == "Windows"
            assert result["ram"]["total_gb"] == pytest.approx(16.0)
            assert result["ram"]["available_gb"] == pytest.approx(8.0)
            assert len(result["gpus"]) == 1
            assert result["gpus"][0]["name"] == "NVIDIA GeForce RTX 3080"
            assert result["max_vram_gb"] == pytest.approx(10.0)

    @patch("platform.system")
    def test_detect_hardware_linux(self, mock_system: MagicMock) -> None:
        mock_system.return_value = "Linux"

        with (
            patch("sqlseed_ai._hardware._get_ram_linux") as mock_ram,
            patch("sqlseed_ai._hardware._detect_gpus") as mock_gpus,
        ):
            mock_ram.return_value = (32.0, 16.0)
            mock_gpus.return_value = []

            # Reset cache
            hw_mod._HardwareCache.data = None

            result = detect_hardware()
            assert result["platform"]["system"] == "Linux"
            assert result["ram"]["total_gb"] == pytest.approx(32.0)
            assert result["ram"]["available_gb"] == pytest.approx(16.0)
            assert len(result["gpus"]) == 0
            assert result["max_vram_gb"] == 0

    @patch("platform.system")
    def test_detect_hardware_macos(self, mock_system: MagicMock) -> None:
        mock_system.return_value = "Darwin"

        with (
            patch("sqlseed_ai._hardware._get_ram_macos") as mock_ram,
            patch("sqlseed_ai._hardware._detect_gpus") as mock_gpus,
        ):
            mock_ram.return_value = (8.0, 4.0)
            mock_gpus.return_value = [
                {
                    "name": "Apple M1",
                    "vram_total_mb": 8192,
                    "vram_free_mb": 0,
                    "vram_total_gb": 8.0,
                    "vendor": "apple",
                }
            ]

            # Reset cache
            hw_mod._HardwareCache.data = None

            result = detect_hardware()
            assert result["platform"]["system"] == "Darwin"
            assert result["ram"]["total_gb"] == pytest.approx(8.0)
            assert len(result["gpus"]) == 1
            assert result["max_vram_gb"] == pytest.approx(8.0)

    def test_evaluate_model_status(self) -> None:
        # 1. GPU VRAM meets recommended specs
        hw_rec = {
            "ram": {"total_gb": 16.0},
            "max_vram_gb": 6.0,
        }
        assert evaluate_model_status("gemma-4-e2b-it", hw_rec) == "recommended"

        # 2. GPU VRAM meets minimum but not recommended
        hw_min = {
            "ram": {"total_gb": 16.0},
            "max_vram_gb": 3.0,
        }
        assert evaluate_model_status("gemma-4-e2b-it", hw_min) == "capable"

        # 3. CPU-only inference
        hw_cpu = {
            "ram": {"total_gb": 8.0},
            "max_vram_gb": 0.0,
        }
        assert evaluate_model_status("gemma-4-e2b-it", hw_cpu) == "cpu_only"

        # 4. Capable slow
        hw_slow = {
            "ram": {"total_gb": 8.0},
            "max_vram_gb": 1.0,
        }
        assert evaluate_model_status("gemma-4-e2b-it", hw_slow) == "capable_slow"

        # 5. Insufficient RAM
        hw_insufficient = {
            "ram": {"total_gb": 2.0},
            "max_vram_gb": 0.0,
        }
        assert evaluate_model_status("gemma-4-e2b-it", hw_insufficient) == "insufficient"

        # 6. Unknown model
        assert evaluate_model_status("gemma-4-nonexistent", hw_rec) == "cloud_only"

    def test_cache_ttl_returns_cached_result(self) -> None:
        """Cached result is returned within TTL without re-detecting."""
        hw_mod._HardwareCache.data = None

        with (
            patch("sqlseed_ai._hardware._detect_system_ram") as mock_ram,
            patch("sqlseed_ai._hardware._detect_gpus") as mock_gpus,
        ):
            mock_ram.return_value = {"total_gb": 16.0, "available_gb": 8.0}
            mock_gpus.return_value = []

            result1 = detect_hardware()
            assert mock_ram.call_count == 1

            # Second call should use cache
            result2 = detect_hardware()
            assert mock_ram.call_count == 1  # Not called again
            assert result2 is result1

    def test_cache_expired_redetects(self) -> None:
        """Expired cache triggers re-detection."""
        # Set an expired cache entry
        expired_time = time.monotonic() - 600  # 10 minutes ago
        hw_mod._HardwareCache.data = (expired_time, {"old": "data"})

        with (
            patch("sqlseed_ai._hardware._detect_system_ram") as mock_ram,
            patch("sqlseed_ai._hardware._detect_gpus") as mock_gpus,
        ):
            mock_ram.return_value = {"total_gb": 32.0, "available_gb": 16.0}
            mock_gpus.return_value = []

            result = detect_hardware()
            assert mock_ram.call_count == 1
            assert result["ram"]["total_gb"] == pytest.approx(32.0)

    @patch("platform.system")
    def test_unknown_platform_returns_zeros(self, mock_system: MagicMock) -> None:
        """Unknown platform returns zero RAM/GPU without crashing."""
        mock_system.return_value = "FreeBSD"

        hw_mod._HardwareCache.data = None

        with patch("sqlseed_ai._hardware._detect_gpus") as mock_gpus:
            mock_gpus.return_value = []
            result = detect_hardware()
            assert result["platform"]["system"] == "FreeBSD"
            assert result["ram"]["total_gb"] == 0
            assert result["ram"]["available_gb"] == 0
            assert result["gpus"] == []
            assert result["max_vram_gb"] == 0

    def test_evaluate_model_status_missing_ram_key(self) -> None:
        """Missing 'ram' key in hw dict defaults to 0 (insufficient)."""
        hw_missing = {"max_vram_gb": 0}
        assert evaluate_model_status("gemma-4-e2b-it", hw_missing) == "insufficient"
