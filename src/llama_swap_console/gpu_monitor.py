from __future__ import annotations

import asyncio
import json
import re
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


WINDOWS_GPU_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$gpuSamples = @((Get-Counter @(
  '\GPU Process Memory(*)\Dedicated Usage',
  '\GPU Adapter Memory(*)\Dedicated Usage',
  '\GPU Adapter Memory(*)\Shared Usage'
)).CounterSamples)
$counters = @($gpuSamples | Where-Object {
  $_.Path -like '*\gpu process memory(*\dedicated usage'
} | ForEach-Object {
  [pscustomobject]@{ instance = $_.InstanceName; value = [int64]$_.CookedValue }
})
$adapterDedicated = @{}
$gpuSamples | Where-Object {
  $_.Path -like '*\gpu adapter memory(*\dedicated usage'
} | ForEach-Object {
  $adapterDedicated[$_.InstanceName] = [int64]$_.CookedValue
}
$adapterShared = @{}
$gpuSamples | Where-Object {
  $_.Path -like '*\gpu adapter memory(*\shared usage'
} | ForEach-Object {
  $adapterShared[$_.InstanceName] = [int64]$_.CookedValue
}
$adapters = @($adapterDedicated.Keys | Sort-Object | ForEach-Object {
  [pscustomobject]@{
    instance = $_
    dedicated = $adapterDedicated[$_]
    shared = if ($adapterShared.ContainsKey($_)) { $adapterShared[$_] } else { 0 }
  }
})
$processes = @(Get-Process | ForEach-Object {
  $path = $null
  try { $path = $_.Path } catch {}
  [pscustomobject]@{ pid = [int64]$_.Id; name = $_.ProcessName; path = $path }
})
$services = @(Get-CimInstance Win32_Service | Where-Object { $_.ProcessId -gt 0 } | ForEach-Object {
  [pscustomobject]@{ pid = [int64]$_.ProcessId; name = $_.Name }
})
[pscustomobject]@{ counters = $counters; adapters = $adapters; processes = $processes; services = $services } |
  ConvertTo-Json -Compress -Depth 4
""".strip()

_PID_PATTERN = re.compile(r"(?:^|_)pid_(-?\d+)(?:_|$)", re.IGNORECASE)
_ADAPTER_PATTERN = re.compile(
    r"(?:^|_)luid_(0x[0-9a-f]+_0x[0-9a-f]+)_phys_(\d+)(?:_|$)",
    re.IGNORECASE,
)
_PROTECTED_NAMES = {
    "system",
    "dwm",
    "csrss",
    "winlogon",
    "services",
    "lsass",
    "memory compression",
}


@dataclass(frozen=True)
class GpuDevice:
    name: str
    memory_used_mib: int
    memory_total_mib: int
    utilization_percent: int
    temperature_c: int


@dataclass(frozen=True)
class GpuProcess:
    pid: int
    adapter_id: str
    dedicated_bytes: int
    dedicated_mib: float
    process_name: str | None
    service_names: tuple[str, ...]
    path: str | None
    source: str
    kill_command: str
    protected: bool


@dataclass(frozen=True)
class GpuSnapshot:
    gpus: tuple[GpuDevice, ...]
    processes: tuple[GpuProcess, ...]
    sampled_at: float
    adapters: tuple[GpuAdapter, ...] = ()
    degraded_reason: str | None = None


@dataclass(frozen=True)
class GpuAdapter:
    adapter_id: str
    dedicated_bytes: int
    shared_bytes: int
    name: str | None = None
    is_discrete: bool = False
    memory_total_mib: int | None = None


Runner = Callable[[str, list[str]], Awaitable[str]]


def parse_nvidia_csv(output: str) -> tuple[GpuDevice, ...]:
    devices: list[GpuDevice] = []
    for raw_line in output.splitlines():
        if not raw_line.strip():
            continue
        parts = [part.strip() for part in raw_line.split(",")]
        if len(parts) != 5:
            raise ValueError(f"Unexpected nvidia-smi row: {raw_line}")
        name, used, total, utilization, temperature = parts
        devices.append(
            GpuDevice(
                name=name,
                memory_used_mib=int(float(used)),
                memory_total_mib=int(float(total)),
                utilization_percent=int(float(utilization)),
                temperature_c=int(float(temperature)),
            )
        )
    return tuple(devices)


def parse_windows_gpu_adapters_json(output: str) -> tuple[GpuAdapter, ...]:
    data = json.loads(output)
    adapters: list[GpuAdapter] = []
    for row in _as_list(data.get("adapters")):
        adapter_id = _adapter_id(str(row.get("instance", "")))
        if adapter_id is None:
            continue
        adapters.append(
            GpuAdapter(
                adapter_id=adapter_id,
                dedicated_bytes=max(0, int(float(row.get("dedicated", 0)))),
                shared_bytes=max(0, int(float(row.get("shared", 0)))),
            )
        )
    return tuple(sorted(adapters, key=lambda item: item.adapter_id))


def parse_windows_gpu_json(output: str) -> tuple[GpuProcess, ...]:
    data = json.loads(output)
    counters = _as_list(data.get("counters"))
    process_rows = _as_list(data.get("processes"))
    service_rows = _as_list(data.get("services"))

    usage: dict[tuple[int, str], int] = defaultdict(int)
    for row in counters:
        match = _PID_PATTERN.search(str(row.get("instance", "")))
        if match is None:
            continue
        pid = int(match.group(1))
        if not _valid_pid(pid):
            continue
        adapter_id = _adapter_id(str(row.get("instance", "")))
        if adapter_id is None:
            continue
        value = int(float(row.get("value", 0)))
        if value > 0:
            usage[(pid, adapter_id)] += value

    metadata: dict[int, dict[str, Any]] = {}
    for row in process_rows:
        pid = _integer(row.get("pid"))
        if pid is not None and _valid_pid(pid):
            metadata[pid] = row

    services: dict[int, set[str]] = defaultdict(set)
    for row in service_rows:
        pid = _integer(row.get("pid"))
        name = row.get("name")
        if pid is not None and _valid_pid(pid) and name:
            services[pid].add(str(name))

    processes: list[GpuProcess] = []
    for (pid, adapter_id), dedicated_bytes in usage.items():
        row = metadata.get(pid, {})
        process_name = _optional_string(row.get("name"))
        path = _optional_string(row.get("path"))
        protected = pid == 4 or (
            process_name is not None and process_name.casefold() in _PROTECTED_NAMES
        )
        processes.append(
            GpuProcess(
                pid=pid,
                adapter_id=adapter_id,
                dedicated_bytes=dedicated_bytes,
                dedicated_mib=dedicated_bytes / (1024**2),
                process_name=process_name,
                service_names=tuple(sorted(services.get(pid, set()), key=str.casefold)),
                path=path,
                source="windows-wddm",
                kill_command=f"taskkill /PID {pid} /F",
                protected=protected,
            )
        )
    return tuple(
        sorted(processes, key=lambda item: (-item.dedicated_bytes, item.pid, item.adapter_id))
    )


class GpuMonitor:
    def __init__(self, runner: Runner | None = None, cache_seconds: float = 10) -> None:
        self._runner = runner or run_command
        self._cache_seconds = cache_seconds
        self._cached: GpuSnapshot | None = None
        self._sample_lock = asyncio.Lock()

    async def sample(self) -> GpuSnapshot:
        now = time.monotonic()
        if self._cached is not None and now - self._cached.sampled_at < self._cache_seconds:
            return self._cached

        async with self._sample_lock:
            now = time.monotonic()
            if (
                self._cached is not None
                and now - self._cached.sampled_at < self._cache_seconds
            ):
                return self._cached
            return await self._collect()

    async def _collect(self) -> GpuSnapshot:

        reasons: list[str] = []
        try:
            nvidia_output = await self._runner(
                "nvidia-smi",
                [
                    "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
            )
            gpus = parse_nvidia_csv(nvidia_output)
        except Exception as error:
            gpus = ()
            reasons.append(str(error))

        try:
            windows_output = await self._runner(
                "powershell.exe",
                ["-NoProfile", "-NonInteractive", "-Command", WINDOWS_GPU_SCRIPT],
            )
            processes = parse_windows_gpu_json(windows_output)
            adapters = _label_discrete_adapters(
                parse_windows_gpu_adapters_json(windows_output), gpus
            )
        except Exception as error:
            processes = ()
            adapters = ()
            reasons.append(str(error))

        self._cached = GpuSnapshot(
            gpus=gpus,
            processes=processes,
            sampled_at=time.monotonic(),
            adapters=adapters,
            degraded_reason="; ".join(reason for reason in reasons if reason) or None,
        )
        return self._cached


async def run_command(program: str, args: list[str]) -> str:
    process = await asyncio.create_subprocess_exec(
        program,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        # 5s 在 WSL 里跨界调 powershell.exe 经常不够（冷启动 + 杀软扫描），
        # 导致 adapters/processes 频繁降级为空；放宽到 15s，采集本身有缓存不阻塞 API。
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise RuntimeError(f"{program} timed out") from None
    if process.returncode != 0:
        message = _decode_output(stderr).strip() or f"exit code {process.returncode}"
        raise RuntimeError(f"{program}: {message}")
    return _decode_output(stdout)


def _decode_output(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw[:100]:
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")


def _as_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _valid_pid(pid: int) -> bool:
    return 1 <= pid <= 4294967295


def _adapter_id(instance: str) -> str | None:
    match = _ADAPTER_PATTERN.search(instance)
    if match is None:
        return None
    return f"{match.group(1).lower()}_phys_{match.group(2)}"


def _label_discrete_adapters(
    adapters: tuple[GpuAdapter, ...], gpus: tuple[GpuDevice, ...]
) -> tuple[GpuAdapter, ...]:
    if not adapters or not gpus:
        return adapters
    remaining = list(adapters)
    labels: dict[str, GpuDevice] = {}
    for gpu in gpus:
        target = gpu.memory_used_mib * 1024**2
        closest = min(remaining, key=lambda item: abs(item.dedicated_bytes - target))
        labels[closest.adapter_id] = gpu
        remaining.remove(closest)
        if not remaining:
            break
    return tuple(
        GpuAdapter(
            adapter_id=item.adapter_id,
            dedicated_bytes=item.dedicated_bytes,
            shared_bytes=item.shared_bytes,
            name=labels[item.adapter_id].name if item.adapter_id in labels else None,
            is_discrete=item.adapter_id in labels,
            memory_total_mib=(
                labels[item.adapter_id].memory_total_mib
                if item.adapter_id in labels
                else None
            ),
        )
        for item in adapters
    )


def _optional_string(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None
