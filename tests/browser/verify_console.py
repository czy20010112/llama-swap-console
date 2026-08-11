from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import Route, expect, sync_playwright


BASE_URL = os.environ.get("LLAMA_SWAP_CONSOLE_TEST_URL", "http://127.0.0.1:9393")
SCREENSHOTS = Path("test-results/screenshots")


LLAMA_SETTINGS = {
    "backend": "llama_cpp",
    "launch_tokens": ["/home/test/bin/llama server"],
    "model_path": "/mnt/d/AI/models/Muse Glimmer Q5_K_XL.gguf",
    "model_argument": "flag",
    "context_length": 112000,
    "port_token": "${PORT}",
    "llama_cpp": {
        "n_gpu_layers": 99,
        "flash_attn": "on",
        "cache_type_k": "q8_0",
        "cache_type_v": "q8_0",
        "jinja": True,
        "mmproj": None,
        "model_draft": None,
        "spec_type": "dflash",
        "spec_draft_n_max": 16,
        "temperature": 0.8,
        "top_p": 0.95,
        "top_k": 40,
        "min_p": 0.05,
        "repeat_penalty": 1.05,
    },
    "vllm": None,
    "unknown_tokens": ["--ctx-other", "1"],
}

VLLM_SETTINGS = {
    "backend": "vllm",
    "launch_tokens": ["/home/test/.venv/bin/vllm", "serve"],
    "model_path": "/mnt/d/AI/models/Qwen3.6-27B-Fable-NVFP4A16",
    "model_argument": "positional",
    "context_length": 32768,
    "port_token": "${PORT}",
    "llama_cpp": None,
    "vllm": {
        "gpu_memory_utilization": 0.85,
        "kv_cache_dtype": "auto",
        "dtype": "auto",
        "quantization": "compressed-tensors",
        "max_num_seqs": 1,
        "max_num_batched_tokens": 8192,
        "enable_chunked_prefill": True,
        "trust_remote_code": True,
        "reasoning_parser": "qwen3",
        "enable_auto_tool_choice": True,
        "tool_call_parser": "qwen3_coder",
        "safetensors_load_strategy": "prefetch",
        "speculative": {"method": "mtp", "model": None, "num_speculative_tokens": 5},
    },
    "unknown_tokens": [],
}

MODELS = [
    {
        "id": "muse-z",
        "name": "Muse Glimmer Q5_K_XL",
        "description": "Long-context writing model",
        "settings": LLAMA_SETTINGS,
        "compatibility_error": None,
        "revision": "a" * 64,
        "status": "running",
    },
    {
        "id": "fable-a",
        "name": "Fable Fusion NVFP4A16",
        "description": "NVFP4 model with MTP",
        "settings": VLLM_SETTINGS,
        "compatibility_error": None,
        "revision": "a" * 64,
        "status": "unloaded",
    },
]

DISCOVERED = [
    {
        "candidate_id": "ready-candidate",
        "path": "/mnt/d/AI/models/Gemma4-31B-NVFP4",
        "kind": "huggingface",
        "backend": "vllm",
        "size_bytes": 26_500_000_000,
        "complete": True,
        "reason": None,
        "quantization": "compressed-tensors",
        "has_mtp": False,
        "metadata_readable": True,
        "architecture": "gemma4",
        "gguf_file_type": None,
        "quantization_version": None,
    },
    {
        "candidate_id": "gguf-candidate",
        "path": "/mnt/d/AI/models/Qwen-27B-Q4_K_M.gguf",
        "kind": "gguf",
        "backend": "llama_cpp",
        "size_bytes": 17_000_000_000,
        "complete": True,
        "reason": None,
        "quantization": None,
        "has_mtp": False,
        "metadata_readable": True,
        "architecture": "qwen35",
        "gguf_file_type": 15,
        "quantization_version": 2,
    },
    {
        "candidate_id": "partial-candidate",
        "path": "/mnt/d/AI/models/Downloading-Qwen",
        "kind": "huggingface",
        "backend": "vllm",
        "size_bytes": 4_000_000_000,
        "complete": False,
        "reason": "Missing safetensors shard",
        "quantization": "compressed-tensors",
        "has_mtp": True,
        "metadata_readable": True,
        "architecture": "qwen3",
        "gguf_file_type": None,
        "quantization_version": None,
    },
]

GPU = {
    "gpus": [
        {
            "index": 0,
            "name": "NVIDIA GeForce RTX 5090",
            "memory_total_mib": 32607,
            "memory_used_mib": 25300,
            "utilization_percent": 87,
            "temperature_c": 63,
        }
    ],
    "adapters": [
        {
            "adapter_id": "0x00000000_0x0001_phys_0",
            "name": "NVIDIA GeForce RTX 5090",
            "is_discrete": True,
            "dedicated_bytes": 25_300_000_000,
            "shared_bytes": 0,
            "memory_total_mib": 32607,
        },
        {
            "adapter_id": "0x00000000_0x0002_phys_0",
            "name": "Intel(R) UHD Graphics 770",
            "is_discrete": False,
            "dedicated_bytes": 600_000_000,
            "shared_bytes": 100_000_000,
            "memory_total_mib": None,
        },
    ],
    "processes": [
        {
            "pid": 2296,
            "adapter_id": "0x00000000_0x0001_phys_0",
            "process_name": "llama-server",
            "path": "C:\\llama\\llama-server.exe",
            "service_names": ["LlamaSwap"],
            "dedicated_bytes": 24_000_000_000,
            "dedicated_mib": 22888.2,
            "protected": False,
            "kill_command": "taskkill /PID 2296 /F",
        },
        {
            "pid": 100,
            "adapter_id": "0x00000000_0x0002_phys_0",
            "process_name": "dwm",
            "path": "C:\\Windows\\System32\\dwm.exe",
            "service_names": [],
            "dedicated_bytes": 600_000_000,
            "dedicated_mib": 572.2,
            "protected": True,
            "kill_command": "taskkill /PID 100 /F",
        },
    ],
    "sampled_at": 1.0,
    "degraded_reason": None,
}


def json_response(route: Route, payload: object, status: int = 200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))


def api_route(route: Route) -> None:
    request = route.request
    path = request.url.removeprefix(BASE_URL)
    if path == "/api/models":
        json_response(route, {"models": MODELS, "revision": "a" * 64, "llama_swap_available": True})
    elif path.startswith("/api/models/") and request.method == "GET":
        model_id = path.split("/")[3]
        json_response(route, next(item for item in MODELS if item["id"] == model_id))
    elif path.startswith("/api/models/") and request.method == "PUT":
        json_response(route, {"detail": "Simulated validation error"}, 422)
    elif path == "/api/discovered-models":
        json_response(route, {"models": DISCOVERED})
    elif path == "/api/gpu":
        json_response(route, GPU)
    elif path == "/api/events":
        route.fulfill(status=200, content_type="text/event-stream", body="event: log\ndata: console ready\n\n")
    elif request.method == "POST":
        json_response(route, {"ok": True})
    else:
        json_response(route, {"detail": f"Unhandled mock route: {path}"}, 404)


def assert_no_horizontal_overflow(page) -> None:
    dimensions = page.evaluate("() => ({scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth})")
    assert dimensions["scroll"] <= dimensions["client"], dimensions


def main() -> None:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE_URL)
        page = context.new_page()
        page.route(f"{BASE_URL}/api/**", api_route)
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")

        names = page.locator("#model-list .model-row strong").all_text_contents()
        assert names == ["Fable Fusion NVFP4A16", "Muse Glimmer Q5_K_XL"], names
        assert page.locator("#discovered-models .model-row").count() == 3
        assert page.locator("#discovered-models .incomplete").is_disabled()
        assert_no_horizontal_overflow(page)

        page.get_by_text("Fable Fusion NVFP4A16", exact=True).first.click()
        page.get_by_role("button", name="编辑设置").click()
        assert page.locator("#model-editor").evaluate("element => element.open")
        editor = page.locator("#model-editor")
        assert editor.get_by_text("GPU 显存使用率", exact=True).count() == 1
        assert editor.get_by_text("推测 Token 数", exact=True).count() == 1
        assert page.locator('[data-path="launch_tokens"]').count() == 0
        page.locator('[data-path="context_length"]').fill("65536")
        page.get_by_role("button", name="仅保存").click()
        assert page.locator("#model-editor").evaluate("element => element.open")
        expect(page.locator("#editor-errors")).to_have_text("Simulated validation error")

        editor.get_by_role("button", name="EN", exact=True).click()
        assert page.get_by_role("button", name="Save", exact=True).is_visible()
        assert editor.get_by_text("GPU memory utilization", exact=True).count() == 1
        page.get_by_role("button", name="Cancel", exact=True).click()

        assert page.locator("#gpu-selector").input_value() == "0x00000000_0x0001_phys_0"
        process_names = page.locator("#process-list .process-row strong").all_text_contents()
        assert process_names == ["llama-server"], process_names
        page.locator("#process-list .copy-button").first.click()
        assert page.evaluate("navigator.clipboard.readText()") == "taskkill /PID 2296 /F"
        page.locator("#gpu-selector").select_option("all")
        process_names = page.locator("#process-list .process-row strong").all_text_contents()
        assert process_names == ["llama-server", "dwm"], process_names

        page.get_by_text("Gemma4-31B-NVFP4", exact=True).click()
        assert page.locator('[data-path="context_length"]').input_value() == "8192"
        assert page.locator('[data-path="vllm.gpu_memory_utilization"]').input_value() == "0.94"
        assert page.locator('[data-path="vllm.kv_cache_dtype"]').input_value() == "fp8"
        assert page.locator('[data-path="vllm.max_num_batched_tokens"]').input_value() == "4096"
        assert page.locator('[data-path="vllm.speculative.num_speculative_tokens"]').input_value() == ""
        page.get_by_role("button", name="Cancel", exact=True).click()

        page.get_by_text("Qwen-27B-Q4_K_M.gguf", exact=True).click()
        assert page.locator('[data-path="context_length"]').input_value() == "32768"
        page.get_by_role("button", name="Cancel", exact=True).click()
        page.wait_for_timeout(2300)
        page.screenshot(path=SCREENSHOTS / "console-1440x900.png", full_page=True)

        page.set_viewport_size({"width": 1920, "height": 1080})
        assert_no_horizontal_overflow(page)
        page.screenshot(path=SCREENSHOTS / "console-1920x1080.png", full_page=True)

        page.set_viewport_size({"width": 901, "height": 900})
        assert page.locator(".mobile-tabs").is_visible()
        assert_no_horizontal_overflow(page)

        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("button", name="Models", exact=True).click()
        assert page.locator("#model-nav").is_visible()
        assert_no_horizontal_overflow(page)
        page.screenshot(path=SCREENSHOTS / "console-390x844.png", full_page=True)

        for screenshot in SCREENSHOTS.glob("console-*.png"):
            assert screenshot.stat().st_size > 10_000, screenshot
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
