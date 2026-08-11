# llama-swap Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a localhost-only bilingual management console on port 9293 for structured llama-swap configuration, model discovery and lifecycle control, live logs, and Windows WDDM GPU-process visibility.

**Architecture:** A Python 3.12 FastAPI service in WSL owns configuration, scanning, llama-swap API calls, and GPU sampling. A dependency-free static SPA consumes restricted JSON/SSE endpoints; command execution is never accepted from the browser. Core adapters are isolated behind typed service classes and tested before API or UI wiring.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, Pydantic v2, ruamel.yaml, httpx, pytest, pytest-asyncio, vanilla JavaScript/CSS, Lucide static icons, Playwright, systemd user services.

---

## File Map

```text
pyproject.toml                         Python package, runtime and test dependencies
src/llama_swap_console/app.py          FastAPI assembly and static SPA fallback
src/llama_swap_console/settings.py     Environment-backed paths, URLs and limits
src/llama_swap_console/schemas.py      Public API request/response models
src/llama_swap_console/config_store.py Comment-preserving YAML, lock, backup, atomic save
src/llama_swap_console/command_codec.py Structured llama.cpp/vLLM command round trips
src/llama_swap_console/model_scanner.py GGUF and Hugging Face candidate discovery
src/llama_swap_console/swap_client.py   Typed llama-swap HTTP and SSE adapter
src/llama_swap_console/gpu_monitor.py   NVIDIA summary and Windows WDDM process sampler
src/llama_swap_console/model_service.py Model edit/register/load orchestration
src/llama_swap_console/api.py           Restricted HTTP/SSE routes
src/llama_swap_console/web/index.html   Three-column application shell and modal
src/llama_swap_console/web/app.js       State, rendering, i18n and API interactions
src/llama_swap_console/web/styles.css   Approved light operational interface
scripts/install-wsl.sh                  Virtualenv and systemd-user installation
scripts/uninstall-wsl.sh                Service removal without deleting config/models
deploy/llama-swap-console.service       Hardened user-service unit template
tests/                                  Unit, API, integration and browser tests
```

### Task 1: Package Skeleton, Settings, and Health API

**Files:**
- Create: `pyproject.toml`
- Create: `src/llama_swap_console/__init__.py`
- Create: `src/llama_swap_console/settings.py`
- Create: `src/llama_swap_console/app.py`
- Create: `tests/test_health.py`

- [ ] **Step 1: Write the failing health test**

```python
from fastapi.testclient import TestClient
from llama_swap_console.app import create_app
from llama_swap_console.settings import Settings

def test_health_is_local_console(tmp_path):
    app = create_app(Settings(config_path=tmp_path / "config.yaml", model_roots=(tmp_path,)))
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "llama-swap-console"}
```

- [ ] **Step 2: Run the test and verify import failure**

Run: `python -m pytest tests/test_health.py -v`
Expected: FAIL because `llama_swap_console` does not exist.

- [ ] **Step 3: Add package metadata and settings**

Declare Python `>=3.12`, runtime dependencies `fastapi`, `uvicorn[standard]`, `pydantic-settings`, `ruamel.yaml`, `httpx`, `filelock`, `gguf`, and dev dependencies `pytest`, `pytest-asyncio`, `respx`, `playwright`. Define `Settings` with defaults:

```python
config_path = Path("~/.config/llama-swap/config.yaml").expanduser()
model_roots = (Path("/mnt/d/AI/models"),)
llama_swap_url = "http://127.0.0.1:9292"
listen_host = "127.0.0.1"
listen_port = 9293
backup_dir = Path("~/.local/state/llama-swap-console/backups").expanduser()
backup_limit = 20
```

- [ ] **Step 4: Implement the app factory and health route**

```python
def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="llama-swap Console", docs_url=None, redoc_url=None)
    app.state.settings = settings or Settings()

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "llama-swap-console"}
    return app
```

- [ ] **Step 5: Install and verify**

Run: `python -m pip install -e ".[dev]" && python -m pytest tests/test_health.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src tests/test_health.py
git commit -m "feat: scaffold console service"
```

### Task 2: Comment-Preserving Configuration Store

**Files:**
- Create: `src/llama_swap_console/config_store.py`
- Create: `tests/test_config_store.py`

- [ ] **Step 1: Test read, comment preservation, backup, conflict, and rollback**

Create tests using a temporary YAML containing a top-level comment, `models`, and an unrelated `groups` node. Assert `save_model()` changes only one model, preserves the comment and `groups`, creates a timestamped backup, rejects a stale revision, keeps 20 newest backups, and `rollback_latest()` restores the exact previous bytes.

- [ ] **Step 2: Confirm failure**

Run: `python -m pytest tests/test_config_store.py -v`
Expected: FAIL because `ConfigStore` is undefined.

- [ ] **Step 3: Implement locked reads and revisions**

Define:

```python
@dataclass(frozen=True)
class ConfigSnapshot:
    document: CommentedMap
    revision: str
    raw: bytes

class RevisionConflict(Exception): ...
class ConfigValidationError(Exception): ...

class ConfigStore:
    def read(self) -> ConfigSnapshot: ...
    def update_model(self, model_id: str, value: CommentedMap, revision: str) -> ConfigSnapshot: ...
    def register_model(self, model_id: str, value: CommentedMap, revision: str) -> ConfigSnapshot: ...
    def rollback_latest(self) -> ConfigSnapshot: ...
```

Use SHA-256 of raw bytes as the revision and `FileLock(f"{config_path}.lock")` around each mutation.

- [ ] **Step 4: Implement atomic save and retention**

Serialize with `ruamel.yaml.YAML(typ="rt")`, write a named temporary file in the config directory, flush and `os.fsync`, copy the current file to `backup_dir/<UTC>-config.yaml`, then `os.replace`. Reparse the temporary file before replacement. Sort backups by filename and delete only entries exceeding `backup_limit`.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_config_store.py -v`
Expected: PASS.

```bash
git add src/llama_swap_console/config_store.py tests/test_config_store.py
git commit -m "feat: add atomic llama-swap config store"
```

### Task 3: Structured Command Codec

**Files:**
- Create: `src/llama_swap_console/schemas.py`
- Create: `src/llama_swap_console/command_codec.py`
- Create: `tests/test_command_codec.py`

- [ ] **Step 1: Write round-trip tests**

Test representative llama.cpp and vLLM commands containing quoted paths, `${PORT}`, boolean flags, `--speculative-config` JSON, and unknown arguments. Assert known fields decode to typed values, unknown tokens retain order, and `decode(encode(decoded)) == decoded`. Test rejection of an invalid speculative JSON object and a command without a model path.

- [ ] **Step 2: Confirm failure**

Run: `python -m pytest tests/test_command_codec.py -v`
Expected: FAIL because codecs and schemas are missing.

- [ ] **Step 3: Define public schemas**

Create `Backend = Literal["llama_cpp", "vllm"]`, `CommonModelSettings`, `LlamaCppSettings`, `VllmSettings`, `SpeculativeSettings`, and `ModelSettings`. Validate context in `512..262144`, GPU utilization in `0.1..0.99`, speculative tokens in `0..16`, and `max_num_seqs` in `1..256`.

- [ ] **Step 4: Implement token parsing and encoding**

Use `shlex.split(command, posix=True)`. Map exact flags through declarative `FlagSpec` tables; support `--flag=value` and `--flag value`. Preserve executable, `${MODEL_ID}`, `${PORT}`, unknown tokens, and JSON with `json.loads/json.dumps(separators=(",", ":"))`. Never invoke a shell.

- [ ] **Step 5: Add the round-trip guard**

```python
def assert_stable(codec: CommandCodec, command: str) -> ModelSettings:
    first = codec.decode(command)
    second = codec.decode(codec.encode(first))
    if first != second:
        raise CommandRoundTripError("command cannot be represented without loss")
    return first
```

- [ ] **Step 6: Verify and commit**

Run: `python -m pytest tests/test_command_codec.py -v`
Expected: PASS.

```bash
git add src/llama_swap_console/schemas.py src/llama_swap_console/command_codec.py tests/test_command_codec.py
git commit -m "feat: add structured backend command codec"
```

### Task 4: GGUF and Hugging Face Model Discovery

**Files:**
- Create: `src/llama_swap_console/model_scanner.py`
- Create: `tests/test_model_scanner.py`

- [ ] **Step 1: Build fixture-based scanner tests**

Create temporary fixtures for a minimal readable GGUF, corrupt GGUF, complete HF directory (`config.json`, tokenizer, safetensors), indexed shards, missing shard, `.part`, MTP weight, and already-registered normalized path. Assert architecture/quantization metadata, “元数据不可读” degradation, backend suggestions, completeness state, MTP availability, stable candidate ID, and deduplication.

- [ ] **Step 2: Confirm failure**

Run: `python -m pytest tests/test_model_scanner.py -v`
Expected: FAIL because `ModelScanner` is missing.

- [ ] **Step 3: Implement bounded recursive discovery**

Define `DiscoveredModel` with `candidate_id`, `path`, `kind`, `size_bytes`, `complete`, `reason`, `quantization`, and `has_mtp`. Skip symlink traversal and hidden download files. Candidate IDs are the first 16 hex characters of SHA-256 over normalized WSL path.

- [ ] **Step 4: Implement completeness and deduplication**

For GGUF files, use `gguf.GGUFReader` to read `general.architecture`, `general.file_type`, `general.quantization_version`, and size without loading tensors; catch parser errors and retain the candidate with `metadata_readable=false`. For HF directories require `config.json`, a tokenizer file, and either one safetensors file or every shard named in `model.safetensors.index.json`. Read `quantization_config.quant_method`. Compare `Path.resolve(strict=False)` values against paths decoded from registered commands.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_model_scanner.py -v`
Expected: PASS.

```bash
git add src/llama_swap_console/model_scanner.py tests/test_model_scanner.py
git commit -m "feat: discover local GGUF and vLLM models"
```

### Task 5: llama-swap Client and Event Adapter

**Files:**
- Create: `src/llama_swap_console/swap_client.py`
- Create: `tests/test_swap_client.py`

- [ ] **Step 1: Test every upstream operation with respx**

Cover `GET /v1/models`, `GET /running`, `GET /upstream/{quoted_id}/`, `POST /api/models/unload/{quoted_id}`, `POST /api/models/unload`, health timeouts, non-2xx errors, and SSE line forwarding from `/api/events`.

- [ ] **Step 2: Confirm failure**

Run: `python -m pytest tests/test_swap_client.py -v`
Expected: FAIL because `LlamaSwapClient` is missing.

- [ ] **Step 3: Implement the typed async client**

Use one injected `httpx.AsyncClient`, `urllib.parse.quote(model_id, safe="")`, 3-second status timeout, and no read timeout for SSE. Raise `SwapUnavailable` for connection errors and `SwapResponseError(status, body[:1000])` for HTTP errors.

- [ ] **Step 4: Implement SSE parsing without reinterpretation**

Yield complete upstream SSE frames separated by blank lines. Do not parse or alter log text; stop cleanly when the downstream request disconnects.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_swap_client.py -v`
Expected: PASS.

```bash
git add src/llama_swap_console/swap_client.py tests/test_swap_client.py
git commit -m "feat: add llama-swap control client"
```

### Task 6: NVIDIA and Windows WDDM GPU Monitor

**Files:**
- Create: `src/llama_swap_console/gpu_monitor.py`
- Create: `tests/fixtures/gpu-counter.json`
- Create: `tests/test_gpu_monitor.py`

- [ ] **Step 1: Test counter parsing and process enrichment**

Fixture entries must include duplicate instances for one PID, zero-byte entries, a missing process, and a Windows service. Assert byte aggregation by PID, removal of zero entries, service-name mapping, MiB conversion, descending sort, and exact `taskkill /PID 2296 /F` output.

- [ ] **Step 2: Confirm failure**

Run: `python -m pytest tests/test_gpu_monitor.py -v`
Expected: FAIL because `GpuMonitor` is missing.

- [ ] **Step 3: Implement command runner and parsers**

Call subprocesses with argument arrays and five-second timeouts. Query total GPU state via `nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits`. Invoke `powershell.exe -NoProfile -NonInteractive -Command <fixed script>`; the fixed script emits compressed JSON from `Get-Counter`, `Get-Process`, and `Get-CimInstance Win32_Service`.

- [ ] **Step 4: Validate PIDs and cache samples**

Accept only integer PID `1..4294967295`. Generate the copy command server-side from that integer. Cache successful data for two seconds, retain the last GPU summary when WDDM enrichment fails, and return a `degraded_reason` instead of fabricated process data.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_gpu_monitor.py -v`
Expected: PASS.

```bash
git add src/llama_swap_console/gpu_monitor.py tests
git commit -m "feat: report Windows GPU process memory"
```

### Task 7: Model Service and Restricted Management API

**Files:**
- Create: `src/llama_swap_console/model_service.py`
- Create: `src/llama_swap_console/api.py`
- Modify: `src/llama_swap_console/app.py`
- Create: `tests/test_api_models.py`

- [ ] **Step 1: Write API contract tests**

Test list/detail, structured update, stale revision 409, scan/register, path outside roots 422, unknown candidate 404, load/unload white-listing, unload-all, GPU response, latest rollback, and llama-swap unavailable 503. Assert no endpoint accepts `cmd`, `shell`, or raw YAML fields. Send a write request with `Origin: https://example.invalid` and assert 403; allow missing Origin for local non-browser clients and localhost origins for the UI.

- [ ] **Step 2: Confirm failure**

Run: `python -m pytest tests/test_api_models.py -v`
Expected: FAIL because the router is absent.

- [ ] **Step 3: Implement model orchestration**

`ModelService` composes `ConfigStore`, codecs, scanner, client, and monitor. It converts YAML entries to `ModelSettings`, stores scanner results by candidate ID with a five-minute TTL, verifies paths are inside configured roots, and permits lifecycle calls only for model IDs in the latest config snapshot.

- [ ] **Step 4: Add exact restricted routes**

Implement the API list from the design: `/api/settings`, `/api/models`, `/api/models/{id}`, update/load/unload, `/api/models/unload-all`, `/api/events`, `/api/scan`, `/api/discovered-models`, registration, `/api/gpu`, and `/api/config/rollback-latest`. Use Pydantic request models with `extra="forbid"`. Add middleware that permits write methods only when `Origin` is absent or its parsed hostname is `localhost`, `127.0.0.1`, or `[::1]`; do not enable permissive CORS.

- [ ] **Step 5: Implement save and reload semantics**

For `reload=true`, save, wait up to five seconds until `/v1/models` includes the ID, unload it if running, request load, then poll `/running` for up to 120 seconds. A load failure keeps the saved config and returns stage plus upstream message. A hot-reload rejection restores the just-created backup and returns 502.

- [ ] **Step 6: Verify and commit**

Run: `python -m pytest tests/test_api_models.py -v`
Expected: PASS.

```bash
git add src/llama_swap_console tests/test_api_models.py
git commit -m "feat: expose restricted model management API"
```

### Task 8: Bilingual Application Shell

**Files:**
- Create: `src/llama_swap_console/web/index.html`
- Create: `src/llama_swap_console/web/styles.css`
- Create: `src/llama_swap_console/web/app.js`
- Create: `tests/browser/test_shell.py`

- [ ] **Step 1: Write browser shell tests**

At 1440x900 assert three visible columns, Chinese labels by default, English switch persistence in `localStorage`, no horizontal overflow, and accessible names for icon buttons. At 390x844 assert the GPU/log panel is reachable through tabs and no text overlaps.

- [ ] **Step 2: Confirm failure**

Run: `python -m pytest tests/browser/test_shell.py -v`
Expected: FAIL because the SPA is absent.

- [ ] **Step 3: Build semantic HTML and translations**

Create landmarks for model navigation, detail main content, and operations aside. Define complete `zh-CN` and `en` dictionaries in `app.js`; keep paths, IDs, flags, and logs untranslated. Add language, scan, edit, load, unload, reload, and copy buttons with Lucide icon sprites and tooltips.

- [ ] **Step 4: Implement the approved visual system**

Use white/gray-white surfaces, near-black text, 6-8px radius, 1px neutral borders, stable 36px controls, fixed type sizes, and responsive grid tracks `minmax(220px,280px) minmax(420px,1fr) minmax(320px,400px)`. Do not add gradients, nested cards, decorative shapes, or viewport-scaled fonts.

- [ ] **Step 5: Mount static assets and verify**

Serve packaged assets from `/assets` and return `index.html` only for non-API routes. Run browser tests at both viewports and use a screenshot plus pixel histogram to verify the page is nonblank.

- [ ] **Step 6: Commit**

```bash
git add src/llama_swap_console/web src/llama_swap_console/app.py tests/browser
git commit -m "feat: add bilingual console shell"
```

### Task 9: Model Navigation, Detail, and Edit Modal

**Files:**
- Modify: `src/llama_swap_console/web/index.html`
- Modify: `src/llama_swap_console/web/app.js`
- Modify: `src/llama_swap_console/web/styles.css`
- Create: `tests/browser/test_model_workflow.py`

- [ ] **Step 1: Write mocked model workflow tests**

Assert configured models are sorted by display name, running/discovered groups are distinct, search matches ID/name/path, scan results do not auto-register, detail is read-only, edit opens a modal, llama.cpp and vLLM fields switch by backend, validation stays open and focuses the bad field, unknown flags are visible read-only, and “保存并重新加载” sends `reload: true`.

- [ ] **Step 2: Confirm failure**

Run: `python -m pytest tests/browser/test_model_workflow.py -v`
Expected: FAIL on missing workflow controls.

- [ ] **Step 3: Implement state and rendering**

Use a single state object `{models, discovered, selectedId, running, query, locale, modal}` and small render functions per panel. Fetch with a wrapper that parses structured errors and preserves the last successful view during refresh failures.

- [ ] **Step 4: Implement structured modal groups**

Render “基础设置、显存与上下文、加速与缓存、工具与能力”. Use checkbox/toggle controls for booleans, number inputs for numeric limits, selects for enumerations, and text inputs only for IDs/paths. Keep modal footer visible with `position: sticky`; trap focus, close on Escape, and restore focus to “编辑设置”.

- [ ] **Step 5: Implement registration and lifecycle feedback**

Registration opens the same modal prefilled from candidate metadata. Loading/reloading displays stage and logs without deleting configuration on failure. Disable conflicting operations while one request is active.

- [ ] **Step 6: Verify and commit**

Run: `python -m pytest tests/browser/test_model_workflow.py -v`
Expected: PASS.

```bash
git add src/llama_swap_console/web tests/browser/test_model_workflow.py
git commit -m "feat: add structured model workflows"
```

### Task 10: GPU Process Table and Live Logs

**Files:**
- Modify: `src/llama_swap_console/web/index.html`
- Modify: `src/llama_swap_console/web/app.js`
- Modify: `src/llama_swap_console/web/styles.css`
- Create: `tests/browser/test_operations_panel.py`

- [ ] **Step 1: Write operations-panel tests**

Mock unsorted GPU processes and assert rows sort by `dedicated_bytes` descending; show process name, service name, PID, memory and path; search by name/service/PID; copy exactly `taskkill /PID 2296 /F`; warn for protected processes; never expose a kill API. Mock SSE disconnect and assert visible reconnect state followed by resumed logs.

- [ ] **Step 2: Confirm failure**

Run: `python -m pytest tests/browser/test_operations_panel.py -v`
Expected: FAIL on absent rows and log states.

- [ ] **Step 3: Implement GPU polling and copy behavior**

Poll `/api/gpu` every two seconds only while the page is visible. Always sort numerically client-side. Use `navigator.clipboard.writeText(row.kill_command)` and announce “已复制/Copy complete” through an `aria-live` region. Do not create a server mutation request.

- [ ] **Step 4: Implement bounded logs and reconnect**

Subscribe to `/api/events`, retain the newest 2,000 lines, pause DOM appends while log scrolling is locked, and reconnect with delays `1, 2, 4, 8, 15` seconds. Show connection state separately from log content.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/browser/test_operations_panel.py -v`
Expected: PASS.

```bash
git add src/llama_swap_console/web tests/browser/test_operations_panel.py
git commit -m "feat: add GPU process and live log panels"
```

### Task 11: WSL Installation and Service Lifecycle

**Files:**
- Create: `deploy/llama-swap-console.service`
- Create: `scripts/install-wsl.sh`
- Create: `scripts/uninstall-wsl.sh`
- Create: `tests/test_install_scripts.py`
- Create: `README.md`

- [ ] **Step 1: Test scripts statically**

Assert the service binds `127.0.0.1:9293`, references `%h/.local/share/llama-swap-console/.venv`, restarts on failure, has `NoNewPrivileges=true`, and receives explicit config/model paths. Assert uninstall stops/disables only this service and does not contain recursive deletion of model/config paths.

- [ ] **Step 2: Confirm failure**

Run: `python -m pytest tests/test_install_scripts.py -v`
Expected: FAIL because deployment files are absent.

- [ ] **Step 3: Implement idempotent installer**

The installer creates `~/.local/share/llama-swap-console/.venv`, installs the local wheel/editable package, renders the unit into `~/.config/systemd/user`, runs `systemctl --user daemon-reload`, enables and starts it, then verifies `/api/health`. It must print the service status and `http://localhost:9293`.

- [ ] **Step 4: Implement conservative uninstall and documentation**

Uninstall stops/disables the service and removes only the unit file after checking its exact resolved path. README documents install, update, logs, rollback, port ownership, Windows localhost forwarding, and manual recovery from backup. It explicitly states model files and llama-swap config are retained.

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_install_scripts.py -v`
Expected: PASS.

```bash
git add deploy scripts README.md tests/test_install_scripts.py
git commit -m "feat: add WSL user-service installation"
```

### Task 12: Real Configuration and End-to-End Acceptance

**Files:**
- Create: `tests/integration/test_real_environment.py`
- Create: `docs/operations.md`
- Modify: `/home/czy098/.config/llama-swap/config.yaml` through the tested API only

- [ ] **Step 1: Back up and audit the live configuration**

Record its SHA-256, create a timestamped copy in the console backup directory, query `/v1/models`, `/running`, and current GPU state, and verify no unrelated model entry changes during a dry decode/encode pass.

- [ ] **Step 2: Start the console on 9293 and run API smoke tests**

Run health, settings, scan, configured model list, GPU process list, and SSE connection checks. Expected: all return successfully; WDDM degradation, if any, is explicit.

- [ ] **Step 3: Register the Fable NVFP4A16 profile**

Use vLLM 0.27 with `max_model_len=32768`, `gpu_memory_utilization=0.85`, `max_num_seqs=1`, chunked prefill, `reasoning_parser=qwen3`, auto tool choice, `tool_call_parser=qwen3_coder`, `safetensors_load_strategy=prefetch`, and speculative `{method: mtp, num_speculative_tokens: 5}`. Preserve all existing entries.

- [ ] **Step 4: Perform real model checks**

Load Fable, issue a short OpenAI chat completion, issue a deterministic tool-call request, unload it, and confirm logs show MTP enabled. If OOM occurs, reduce speculative tokens before context length and record the final stable values; never modify weights.

- [ ] **Step 5: Run full automated and visual verification**

Run: `python -m pytest -v`
Expected: all tests PASS.

Run Playwright at 1440x900, 1920x1080, and 390x844; capture screenshots and verify nonblank pixels, no overlap, modal scroll/footer behavior, translation stability, GPU descending sort, and exact copied CMD command.

- [ ] **Step 6: Document operational results and commit**

Write actual llama-swap version, model startup duration, VRAM after load, generation throughput, final MTP/context settings, and any WDDM limitation to `docs/operations.md`.

```bash
git add tests/integration docs/operations.md
git commit -m "test: verify console against local inference stack"
```

## Completion Gate

- [ ] All unit, API, integration, and browser tests pass.
- [ ] `git diff --check` is clean and no secrets or model files are tracked.
- [ ] Existing llama-swap model IDs and commands are byte-for-byte unchanged except the explicitly registered/edited model.
- [ ] `9292` remains the Cherry Studio inference endpoint and `9293` remains localhost-only management.
- [ ] Windows GPU rows are descending and copy valid CMD commands without executing them.
- [ ] Fable NVFP4A16 loads, produces text, and completes a tool-call check.
- [ ] Service survives restart and uninstall leaves llama-swap config and all model files intact.
