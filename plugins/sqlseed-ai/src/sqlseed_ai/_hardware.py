"""Cross-platform hardware detection for model selection.

Detects system RAM, GPU/VRAM, and platform info using only stdlib.
Used by `sqlseed_list_gemma_models` to provide hardware-aware model recommendations.

Supported platforms: Windows, Linux, macOS (Intel + Apple Silicon).
"""

from __future__ import annotations

import ctypes
import json
import platform
import re
import subprocess
import time
from math import isfinite
from typing import Any, NamedTuple

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
            """Win32 ``MEMORYSTATUSEX`` structure for ``GlobalMemoryStatusEx`` (ctypes mirror).

            Field names (``dwLength``, ``ullTotalPhys``, etc.) MUST exactly match
            the Win32 C struct definition — ctypes requires this for binary
            compatibility. The Hungarian-notation prefixes (``dw`` = DWORD,
            ``ull`` = ULONGLONG) are dictated by the Windows API and cannot be
            renamed to snake_case. The ``good-names-rgxs`` setting in
            ``pyproject.toml`` whitelists this pattern.
            """

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

            def __init__(self) -> None:
                super().__init__()
                # Required by GlobalMemoryStatusEx: dwLength must be set to the
                # size of the struct before the call. Initializing in __init__
                # (rather than after instantiation) ensures every instance is
                # correctly populated and satisfies pylint's
                # attribute-defined-outside-init check.
                self.dwLength = ctypes.sizeof(self)

        stat = MEMORYSTATUSEX()
        # ctypes.windll only exists on Windows; use getattr for cross-platform safety
        if (windll := getattr(ctypes, "windll", None)) is None:
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
        with open("/proc/meminfo", encoding="utf-8") as f:
            info: dict[str, int] = {}
            for line in f:
                parts = line.split()
                if parts[0] in {"MemTotal:", "MemAvailable:"}:
                    info[parts[0].rstrip(":")] = int(parts[1])  # in kB
            total = info.get("MemTotal", 0) / (1024**2)
            avail = info.get("MemAvailable", 0) / (1024**2)
            return (round(total, 1), round(avail, 1))
    except (FileNotFoundError, KeyError, ValueError, IndexError):
        return None


def _available_ram_from_vm_stat(output: str, page_size: int) -> float:
    """Convert free and speculative vm_stat page counts to available GiB."""
    avail_gb = 0.0
    for line in output.splitlines():
        if "page size of" in line:
            page_size = int(line.split()[-2])
        if "Pages free:" in line or "Pages speculative:" in line:
            count = int(line.split()[-1].rstrip("."))
            avail_gb += count * page_size / (1024**3)
    return round(avail_gb, 1)


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
            avail_gb = _available_ram_from_vm_stat(result.stdout, page_size)

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


def _video_memory_mb(value: object) -> int:
    """Parse a profiler memory quantity without trusting malformed card fields."""
    if not isinstance(value, str):
        return 0
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(MB|GB)", value.strip(), re.IGNORECASE)
    if match is None:
        return 0
    size_mb = float(match[1]) * (1024 if match[2].upper() == "GB" else 1)
    return int(size_mb) if isfinite(size_mb) else 0


def _detect_gpu_macos() -> list[dict[str, Any]]:
    """Detect Apple, Intel and discrete GPUs via macOS system_profiler."""
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
        if not isinstance(data, dict):
            return []
        displays = data.get("SPDisplaysDataType", [])
        if not isinstance(displays, list):
            return []
        gpus: list[dict[str, Any]] = []
        for gpu_info in displays:
            if not isinstance(gpu_info, dict):
                continue
            name = gpu_info.get("sppci_model", "Unknown GPU")
            if not isinstance(name, str):
                name = "Unknown GPU"
            vendor_label = str(gpu_info.get("spdisplays_vendor") or name).lower()
            vendor = next((v for v in ("apple", "intel", "amd", "nvidia") if v in vendor_label), "unknown")
            if vendor == "apple":
                memory_type = "unified"
                vram_mb = 0
            else:
                memory_type = "shared" if "spdisplays_vram_shared" in gpu_info else "dedicated"
                vram_mb = next(
                    (
                        size
                        for key in ("spdisplays_vram", "spdisplays_vram_shared", "_spdisplays_vram")
                        if (size := _video_memory_mb(gpu_info.get(key))) > 0
                    ),
                    0,
                )

            gpus.append(
                {
                    "name": name,
                    "vram_total_mb": vram_mb,
                    "vram_free_mb": 0,  # system_profiler does not report free VRAM
                    "vram_total_gb": round(vram_mb / 1024, 1),
                    "vendor": vendor,
                    "memory_type": memory_type,
                }
            )
        return gpus
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        return []


def _detect_gpus() -> list[dict[str, Any]]:
    """Detect GPUs. Tries nvidia-smi first, then platform-specific fallbacks."""
    if gpus := _detect_gpu_nvidia():
        return gpus

    if platform.system() == "Darwin":
        return _detect_gpu_macos()

    return []


def _has_apple_unified_memory(hw: dict[str, Any]) -> bool:
    """Require an identified Apple GPU on macOS, including under Rosetta."""
    return hw.get("platform", {}).get("system") == "Darwin" and any(
        gpu.get("vendor") == "apple" and gpu.get("memory_type") == "unified" for gpu in hw.get("gpus", [])
    )


# ── Public API ───────────────────────────────────────────────────────


def detect_hardware() -> dict[str, Any]:
    """Detect hardware environment. Results are cached for 5 minutes.

    Returns a dict with keys:
        platform: {system, release, machine}
        ram: {total_gb, available_gb}
        gpus: [{name, vram_total_mb, vram_free_mb, vram_total_gb, vendor, ...}]
        max_vram_gb: float (largest reported non-unified VRAM quantity)
        unified_memory_budget_gb: float (heuristic budget, not measured free VRAM)
    """
    if _HardwareCache.data is not None:
        cached_time, cached_result = _HardwareCache.data
        if time.monotonic() - cached_time < _HW_CACHE_TTL:
            return cached_result

    ram = _detect_system_ram()
    gpus = _detect_gpus()
    max_vram = max((g.get("vram_total_gb", 0) for g in gpus if g.get("memory_type") != "unified"), default=0)

    result: dict[str, Any] = {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "ram": ram,
        "gpus": gpus,
        "max_vram_gb": max_vram,
        "unified_memory_budget_gb": 0.0,
    }
    if _has_apple_unified_memory(result):
        # A static screening heuristic, not Metal's runtime allocation limit.
        # Reserve at least 4 GiB / 25% for the OS and other applications.
        total_ram = ram["total_gb"]
        result["unified_memory_budget_gb"] = max(0.0, min(total_ram * 0.75, total_ram - 4.0))

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


class ModelRequirement(NamedTuple):
    """Hardware requirements for a local model variant."""

    min_ram_gb: int
    min_vram_gb: int
    recommended_vram_gb: int


MODEL_REQUIREMENTS: dict[str, ModelRequirement] = {
    "gemma-4-e2b-it": ModelRequirement(min_ram_gb=4, min_vram_gb=2, recommended_vram_gb=4),
    "gemma-4-e4b-it": ModelRequirement(min_ram_gb=6, min_vram_gb=3, recommended_vram_gb=6),
    "gemma-4-12b-it": ModelRequirement(min_ram_gb=12, min_vram_gb=8, recommended_vram_gb=10),
    "gemma-4-26b-a4b-it": ModelRequirement(min_ram_gb=16, min_vram_gb=14, recommended_vram_gb=16),
    "gemma-4-31b-it": ModelRequirement(min_ram_gb=24, min_vram_gb=18, recommended_vram_gb=24),
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
    if not (req := MODEL_REQUIREMENTS.get(model_id)):
        return "cloud_only"

    max_vram = hw.get("max_vram_gb", 0)
    total_ram = hw.get("ram", {}).get("total_gb", 0)

    if max_vram >= req.recommended_vram_gb:
        return "recommended"
    if max_vram >= req.min_vram_gb:
        return "capable"
    if _has_apple_unified_memory(hw):
        budget = hw.get("unified_memory_budget_gb", 0)
        # RAM and GPU allocations share this budget; never add them or grant
        # a recommendation without verifying the backend and actual model.
        return "capable" if budget >= max(req.min_ram_gb, req.min_vram_gb) else "insufficient"
    if total_ram >= req.min_ram_gb and max_vram == 0:
        return "cpu_only"
    if total_ram >= req.min_ram_gb:
        return "capable_slow"
    return "insufficient"
