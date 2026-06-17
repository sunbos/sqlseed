"""Cross-platform hardware detection for model selection.

Detects system RAM, GPU/VRAM, and platform info using only stdlib.
Used by `sqlseed_list_gemma_models` to provide hardware-aware model recommendations.

Supported platforms: Windows, Linux, macOS (Intel + Apple Silicon).
"""

from __future__ import annotations

import ctypes
import json
import platform
import subprocess
import time
from typing import Any

from sqlseed._utils.logger import get_logger

logger = get_logger(__name__)


class _HardwareCache:
    """Cache for hardware info (detected once, reused for 5 minutes)."""

    data: tuple[float, dict[str, Any]] | None = None


_HW_CACHE_TTL = 300.0  # 5 minutes


# ── System RAM ───────────────────────────────────────────────────────


def _get_ram_windows() -> tuple[float, float] | None:
    """Get RAM via Win32 API (ctypes). Returns (total_gb, available_gb)."""
    try:

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        # ctypes.windll only exists on Windows; use getattr for cross-platform safety
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return None
        windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return (
            round(stat.ullTotalPhys / (1024**3), 1),
            round(stat.ullAvailPhys / (1024**3), 1),
        )
    except (AttributeError, OSError):
        return None


def _get_ram_linux() -> tuple[float, float] | None:
    """Get RAM from /proc/meminfo. Returns (total_gb, available_gb)."""
    try:
        with open("/proc/meminfo") as f:
            info: dict[str, int] = {}
            for line in f:
                parts = line.split()
                if parts[0] in ("MemTotal:", "MemAvailable:"):
                    info[parts[0].rstrip(":")] = int(parts[1])  # in kB
            total = info.get("MemTotal", 0) / (1024**2)
            avail = info.get("MemAvailable", 0) / (1024**2)
            return (round(total, 1), round(avail, 1))
    except (FileNotFoundError, KeyError, ValueError, IndexError):
        return None


def _get_ram_macos() -> tuple[float, float] | None:
    """Get RAM via sysctl (total) and vm_stat (available estimate)."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        total_bytes = int(result.stdout.strip())
        total_gb = round(total_bytes / (1024**3), 1)

        avail_gb = 0.0
        result = subprocess.run(
            ["vm_stat"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            # Default page size: Apple Silicon = 16384, Intel Mac = 4096
            page_size = 16384 if platform.machine() == "arm64" else 4096
            for line in result.stdout.splitlines():
                if "page size of" in line:
                    page_size = int(line.split()[-2])
                if "Pages free:" in line or "Pages speculative:" in line:
                    count = int(line.split()[-1].rstrip("."))
                    avail_gb += count * page_size / (1024**3)
            avail_gb = round(avail_gb, 1)

        return (total_gb, avail_gb)
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        return None


def _detect_system_ram() -> dict[str, Any]:
    """Detect system RAM. Cross-platform (Windows/Linux/macOS)."""
    system = platform.system()
    result: tuple[float, float] | None = None

    if system == "Windows":
        result = _get_ram_windows()
    elif system == "Linux":
        result = _get_ram_linux()
    elif system == "Darwin":
        result = _get_ram_macos()

    if result:
        return {"total_gb": result[0], "available_gb": result[1]}
    return {"total_gb": 0, "available_gb": 0}


# ── GPU / VRAM ───────────────────────────────────────────────────────


def _detect_gpu_nvidia() -> list[dict[str, Any]]:
    """Detect NVIDIA GPUs via nvidia-smi (works on all platforms)."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0 or not result.stdout:
            return []

        gpus: list[dict[str, Any]] = []
        for line in result.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                vram_total = int(parts[1])
                vram_free = int(parts[2])
                gpus.append(
                    {
                        "name": parts[0],
                        "vram_total_mb": vram_total,
                        "vram_free_mb": vram_free,
                        "vram_total_gb": round(vram_total / 1024, 1),
                        "driver_version": parts[3],
                        "vendor": "nvidia",
                    }
                )
        return gpus
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return []


def _detect_gpu_macos() -> list[dict[str, Any]]:
    """Detect Apple Silicon GPU via system_profiler. macOS only."""
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType", "-json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0 or not result.stdout:
            return []

        data = json.loads(result.stdout)
        displays = data.get("SPDisplaysDataType", [])
        gpus: list[dict[str, Any]] = []
        for gpu_info in displays:
            name = gpu_info.get("sppci_model", "Unknown GPU")
            vram_str = gpu_info.get("spdisplays_vram", "")
            vram_mb = 0
            if vram_str:
                parts = vram_str.split()
                if len(parts) >= 2:
                    val = int(parts[0])
                    unit = parts[1].upper()
                    vram_mb = val * 1024 if "GB" in unit else val

            gpus.append(
                {
                    "name": name,
                    "vram_total_mb": vram_mb,
                    "vram_free_mb": 0,  # Apple Silicon uses unified memory; discrete VRAM is always 0
                    "vram_total_gb": round(vram_mb / 1024, 1),
                    "vendor": "apple",
                }
            )
        return gpus
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired, ValueError):
        return []


def _detect_gpus() -> list[dict[str, Any]]:
    """Detect GPUs. Tries nvidia-smi first, then platform-specific fallbacks."""
    gpus = _detect_gpu_nvidia()
    if gpus:
        return gpus

    if platform.system() == "Darwin":
        return _detect_gpu_macos()

    return []


# ── Public API ───────────────────────────────────────────────────────


def detect_hardware() -> dict[str, Any]:
    """Detect hardware environment. Results are cached for 5 minutes.

    Returns a dict with keys:
        platform: {system, release, machine}
        ram: {total_gb, available_gb}
        gpus: [{name, vram_total_mb, vram_free_mb, vram_total_gb, vendor, ...}]
        max_vram_gb: float  (max VRAM across all GPUs, 0 if no GPU)
    """
    if _HardwareCache.data is not None:
        cached_time, cached_result = _HardwareCache.data
        if time.monotonic() - cached_time < _HW_CACHE_TTL:
            return cached_result

    ram = _detect_system_ram()
    gpus = _detect_gpus()
    max_vram = max((g.get("vram_total_gb", 0) for g in gpus), default=0)

    result = {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "ram": ram,
        "gpus": gpus,
        "max_vram_gb": max_vram,
    }

    _HardwareCache.data = (time.monotonic(), result)
    logger.info(
        "Hardware detected",
        ram_total=ram["total_gb"],
        gpu_count=len(gpus),
        max_vram_gb=max_vram,
    )
    return result


# ── Model requirements ───────────────────────────────────────────────

# Approximate requirements for Gemma 4 (Q4_K_M quantized for local inference)
MODEL_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "gemma-4-e2b-it": {
        "min_ram_gb": 4,
        "min_vram_gb": 2,
        "recommended_vram_gb": 4,
    },
    "gemma-4-e4b-it": {
        "min_ram_gb": 6,
        "min_vram_gb": 3,
        "recommended_vram_gb": 6,
    },
    "gemma-4-12b-it": {
        "min_ram_gb": 12,
        "min_vram_gb": 8,
        "recommended_vram_gb": 10,
    },
    "gemma-4-26b-a4b-it": {
        "min_ram_gb": 16,
        "min_vram_gb": 14,
        "recommended_vram_gb": 16,
    },
    "gemma-4-31b-it": {
        "min_ram_gb": 24,
        "min_vram_gb": 18,
        "recommended_vram_gb": 24,
    },
}


def evaluate_model_status(
    model_id: str,
    hw: dict[str, Any],
) -> str:
    """Evaluate hardware compatibility status for a model.

    Returns one of:
        "recommended"  — hardware meets recommended specs
        "capable"      — hardware meets minimum specs
        "capable_slow" — RAM sufficient but VRAM below minimum (will use RAM offloading)
        "cpu_only"     — RAM sufficient but no GPU detected
        "insufficient" — hardware does not meet minimum specs
        "cloud_only"   — not applicable for local inference
    """
    req = MODEL_REQUIREMENTS.get(model_id)
    if not req:
        return "cloud_only"

    max_vram = hw.get("max_vram_gb", 0)
    total_ram = hw.get("ram", {}).get("total_gb", 0)

    if max_vram >= req["recommended_vram_gb"]:
        return "recommended"
    if max_vram >= req["min_vram_gb"]:
        return "capable"
    if total_ram >= req["min_ram_gb"] and max_vram == 0:
        return "cpu_only"
    if total_ram >= req["min_ram_gb"]:
        return "capable_slow"
    return "insufficient"
