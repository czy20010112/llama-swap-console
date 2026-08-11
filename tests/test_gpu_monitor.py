from __future__ import annotations

import json
from pathlib import Path

import pytest

from llama_swap_console.gpu_monitor import GpuMonitor, parse_nvidia_csv, parse_windows_gpu_json


FIXTURE = Path(__file__).parent / "fixtures" / "gpu-counter.json"


def test_parses_nvidia_summary() -> None:
    snapshot = parse_nvidia_csv("NVIDIA GeForce RTX 5090, 24576, 32607, 87, 61\n")

    assert len(snapshot) == 1
    assert snapshot[0].name == "NVIDIA GeForce RTX 5090"
    assert snapshot[0].memory_used_mib == 24576
    assert snapshot[0].memory_total_mib == 32607
    assert snapshot[0].utilization_percent == 87
    assert snapshot[0].temperature_c == 61


def test_aggregates_windows_instances_and_enriches_processes() -> None:
    processes = parse_windows_gpu_json(FIXTURE.read_text(encoding="utf-8"))

    assert [process.pid for process in processes] == [2296, 9056]
    assert processes[0].dedicated_bytes == 11 * 1024**3
    assert processes[0].dedicated_mib == 11264
    assert processes[0].process_name == "python"
    assert processes[0].service_names == ("model-worker", "vllm-service")
    assert processes[0].path == r"C:\Python\python.exe"
    assert processes[0].kill_command == "taskkill /PID 2296 /F"
    assert processes[0].protected is False
    assert processes[1].process_name == "dwm"
    assert processes[1].protected is True


def test_missing_process_metadata_retains_valid_pid() -> None:
    raw = json.dumps(
        {
            "counters": [{"instance": "pid_42_luid_x", "value": 1048576}],
            "processes": [],
            "services": [],
        }
    )

    process = parse_windows_gpu_json(raw)[0]

    assert process.pid == 42
    assert process.process_name is None
    assert process.path is None
    assert process.dedicated_mib == 1


@pytest.mark.parametrize("pid", [0, -1, 4294967296])
def test_invalid_pids_are_discarded(pid: int) -> None:
    raw = json.dumps(
        {
            "counters": [{"instance": f"pid_{pid}_luid_x", "value": 1048576}],
            "processes": [],
            "services": [],
        }
    )

    assert parse_windows_gpu_json(raw) == ()


@pytest.mark.asyncio
async def test_sample_keeps_gpu_summary_when_windows_counter_fails() -> None:
    calls = 0

    async def runner(program: str, args: list[str]) -> str:
        nonlocal calls
        calls += 1
        if program == "nvidia-smi":
            return "RTX 5090, 1000, 32000, 50, 55\n"
        raise RuntimeError("Get-Counter unavailable")

    monitor = GpuMonitor(runner=runner, cache_seconds=2)

    first = await monitor.sample()
    second = await monitor.sample()

    assert first.gpus[0].name == "RTX 5090"
    assert first.processes == ()
    assert first.degraded_reason == "Get-Counter unavailable"
    assert second is first
    assert calls == 2


@pytest.mark.asyncio
async def test_sample_sorts_processes_by_dedicated_memory() -> None:
    async def runner(program: str, args: list[str]) -> str:
        if program == "nvidia-smi":
            return "RTX 5090, 1000, 32000, 50, 55\n"
        return FIXTURE.read_text(encoding="utf-8")

    snapshot = await GpuMonitor(runner=runner, cache_seconds=0).sample()

    assert [process.pid for process in snapshot.processes] == [2296, 9056]
    assert snapshot.degraded_reason is None
