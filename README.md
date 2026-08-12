# llama-swap Console

[中文](#中文) | [English](#english)

## 中文

`llama-swap Console` 是面向 Windows 11 + WSL2 的本地 llama-swap 管理台。它在
`127.0.0.1:9293` 提供配置与运行状态界面；模型推理 API 和 llama-swap 原管理页仍由
`127.0.0.1:9292` 提供。两者是独立服务，管理台不会取代 llama-swap。

默认界面为中文，可在页面顶部和编辑窗口中切换英文。项目将模型权重和 llama-swap
主配置视为用户数据，安装、更新和卸载均不会删除它们。

### 功能

- 查看已配置模型、其结构化启动设置、运行状态和 llama-swap 连接状态。
- 扫描 `/mnt/d/AI/models` 下的 GGUF 与 Hugging Face safetensors 模型，并登记完整的候选模型。
- 自动过滤辅助模型，例如 `mmproj`、嵌入、重排序、草稿和 dflash/eagle GGUF；未完成下载的
  Hugging Face 模型会保留在列表中，但不能登记。
- 在弹出式编辑窗口中分别编辑 llama.cpp 与 vLLM 的常用设置；启动器、端口模板和原始兼容参数
  保持只读，避免丢失无法安全重写的命令参数。
- 保存前校验 YAML、模型路径和配置版本；写入前创建备份，热重载失败时自动恢复本次改动。
- 加载、卸载单个模型或全部模型，并把并发的同一模型操作合并，避免重复向上游发送请求。
- 显示 NVIDIA 实际显存总量，以及 Windows WDDM 的按进程显存分配。可在独显和全部图形适配器
  之间切换；进程行只提供可复制的 `taskkill /PID <PID> /F` 命令，不会在网页中结束任何进程。
- 转发 llama-swap 的实时事件日志，并提供中文/英文界面切换。

### 架构与端口

```text
Windows browser
  |-- http://localhost:9293  -> llama-swap Console (WSL user service)
  |                               |-- config.yaml / backups
  |                               |-- /mnt/d/AI/models scan
  |                               |-- nvidia-smi + Windows WDDM query
  |
  `-- http://localhost:9292  -> llama-swap (existing inference API and UI)
                                    `-- llama.cpp / vLLM model processes
```

| 地址 | 用途 |
| --- | --- |
| `http://localhost:9293` | 本项目的管理台 |
| `http://localhost:9292` | 现有 llama-swap 推理 API |
| `http://localhost:9292/ui` | 现有 llama-swap 原管理页 |

管理台 systemd 用户服务名为 `llama-swap-console.service`，固定监听
`127.0.0.1:9293`。不建议同时手工启动另一个 uvicorn 实例。

### 环境要求

- Windows 11 与 WSL2 Ubuntu。
- WSL 已启用 systemd。
- WSL 内 Python 3.12 或更高版本，以及 `python3-venv`。
- 已可用的 llama-swap，监听 `127.0.0.1:9292`。
- llama-swap 配置位于 `~/.config/llama-swap/config.yaml`。
- 模型默认根目录为 `/mnt/d/AI/models`。

若尚未启用 WSL systemd，在 `/etc/wsl.conf` 中加入：

```ini
[boot]
systemd=true
```

然后在 Windows PowerShell 执行：

```powershell
wsl --shutdown
```

重新打开 Ubuntu 后再安装。

### 安装

在 WSL 中进入仓库目录并执行：

```bash
cd /mnt/d/projects/just-thinking/llama-swap-console
bash scripts/install-wsl.sh
```

安装脚本会：

1. 确认当前环境是 WSL2、Python 版本满足要求且 systemd 用户服务可用。
2. 在 `~/.local/share/llama-swap-console/.venv` 创建独立虚拟环境并安装当前源码。
3. 安装并启动 `~/.config/systemd/user/llama-swap-console.service`。
4. 检查 `http://127.0.0.1:9293/api/health`。

完成后在 Windows 浏览器打开 <http://localhost:9293>。

### 更新

拉取或修改源码后，重复执行安装命令即可：

```bash
cd /mnt/d/projects/just-thinking/llama-swap-console
bash scripts/install-wsl.sh
```

脚本会升级管理台的独立环境、刷新 unit 并重启服务；不会重建模型文件、删除模型权重或覆盖
llama-swap 配置。

### 卸载

```bash
cd /mnt/d/projects/just-thinking/llama-swap-console
bash scripts/uninstall-wsl.sh
```

卸载脚本只停止并移除 `llama-swap-console.service`。它不会删除模型文件，也不会删除 llama-swap 配置
`~/.config/llama-swap/config.yaml`；备份和虚拟环境同样会保留。若需要清理虚拟环境，
请自行确认后处理 `~/.local/share/llama-swap-console`。

### 配置、扫描与默认行为

服务的默认值可由 `LLAMA_SWAP_CONSOLE_` 前缀的环境变量覆盖。随仓库提供的 systemd unit 使用
下列设置：

| 项目 | 默认值 |
| --- | --- |
| llama-swap 配置 | `~/.config/llama-swap/config.yaml` |
| 模型根目录 | `/mnt/d/AI/models` |
| llama-swap 地址 | `http://127.0.0.1:9292` |
| 管理台地址 | `127.0.0.1:9293` |
| 备份目录 | `~/.local/state/llama-swap-console/backups` |
| 保留备份数 | 20 |

模型扫描结果会缓存 5 分钟。登记候选模型时，路径必须位于允许的模型根目录中，模型必须完整，且
该后端需要已有一个可解析的已配置模型作为受信任启动器模板。管理台不会猜测或下载启动器。

候选模型的初始上下文按权重文件总大小保守设置：小于 12 GiB 为 64K，12--20 GiB 为 32K，
20--24 GiB 为 16K，24 GiB 及以上为 8K。vLLM 候选默认使用单序列、FP8 KV cache、最多
4096 个批处理 token、启用 chunked prefill，并关闭 MTP。它们是可编辑的起点，不代表某个
模型或显卡一定能稳定支持该上下文长度。

编辑已有模型时，后端类型、启动器、端口模板和无法结构化表达的兼容参数不可改；模型路径与可见的
推理参数可以通过校验后保存。每次写入使用配置 revision 防止覆盖外部修改，并在写入前生成备份。

更多实测部署参数和运行记录见 [docs/operations.md](docs/operations.md)。

### 模型生命周期与 HTTP 202

加载或卸载在 llama-swap 上需要时间时，管理台可能返回 HTTP `202 Accepted`：

| `status` | 含义 |
| --- | --- |
| `starting` | 上游已经报告模型正在启动，或相同操作正在进行。 |
| `loading` | 上游运行状态明确显示正在加载。 |
| `pending` | 加载请求已被上游接受，但暂时还未能从运行状态确认。 |

前端会禁用相关操作并每秒刷新模型状态，最多刷新 30 次。`202` 不是失败，也不需要反复点击“加载”。
真正无法连上 llama-swap 时，管理台返回 `503`；llama-swap 返回非成功响应时，管理台返回 `502`。

### 日常运维

```bash
# 查看服务状态
systemctl --user status llama-swap-console

# 跟随服务日志
journalctl --user -u llama-swap-console -f

# 重启管理台
systemctl --user restart llama-swap-console

# 健康检查
curl http://127.0.0.1:9293/api/health
```

### 故障排查

#### 端口占用、9293 无法启动或页面打不开

先检查端口与服务日志：

```bash
ss -ltnp | grep ':9293'
systemctl --user status llama-swap-console
journalctl --user -u llama-swap-console -n 80 --no-pager
```

服务固定绑定 `127.0.0.1:9293`。若 WSL 内健康检查成功而 Windows 浏览器打不开：

#### Windows localhost 转发

1. 在 Windows PowerShell 执行 `wsl --shutdown` 后重新启动 WSL。
2. 检查 `%UserProfile%\.wslconfig` 没有禁用 `localhostForwarding`。
3. 确认 Windows 没有其他程序占用 9293，且 unit 没被改为其他监听地址或端口。

#### 出现 503、模型状态 unavailable 或实时日志无法连接

9293 依赖已经运行的 llama-swap。先在 WSL 中验证：

```bash
curl http://127.0.0.1:9292/v1/models
```

若该请求失败，请先恢复 llama-swap 服务。模型加载过程中的 `202 starting`、`loading` 或
`pending` 属于正常过渡状态；等待状态刷新，不要并发反复点击。

#### 模型没有出现在“未登记模型”列表

- 确认模型实际位于 `/mnt/d/AI/models` 或已通过服务环境变量配置的允许根目录内。
- GGUF 辅助文件、视觉投影、嵌入、重排序、草稿与 dflash/eagle 文件会被过滤，不会作为对话模型登记。
- Hugging Face 目录需有 `config.json`、一个 tokenizer 文件和 safetensors 权重；`.part`、
  `.crdownload`、`.tmp` 或缺失分片会显示为未完成。
- 已登记模型不会重复显示为候选项。

#### 保存失败、409 或热重载失败

- `409` 表示 `config.yaml` 在打开编辑窗口后被外部程序修改。刷新页面后重新编辑。
- `422` 表示结构化设置、模型路径或启动器模板校验未通过。
- 热重载无法确认时，管理台会自动恢复此次写入前的配置。模型权重不会被修改。

手动回滚最近备份：

```bash
systemctl --user stop llama-swap-console
ls -lt ~/.local/state/llama-swap-console/backups/
cp --preserve=mode <选定的备份文件> ~/.config/llama-swap/config.yaml
systemctl --user restart llama-swap-console
```

恢复前建议再复制一份当前 `config.yaml`。

#### 顶部 NVIDIA 显存和 WDDM 进程列表不能相加

顶部 NVIDIA 数字来自 `nvidia-smi`，表示独显的物理显存总占用。进程列表来自 Windows WDDM，
表示进程的图形资源分配；共享表面可能会在多个进程中重复出现。因此 WDDM 行不应相加，也不能要求
与 NVIDIA 总量一一相等。通常选择检测到的 NVIDIA 独显最适合排查本地模型占用；“全部图形适配器”
用于同时查看集显和独显。

### 安全边界

- 管理台和服务默认只绑定 loopback 地址；写操作拒绝非 `localhost`、`127.0.0.1` 和 `::1` 的
  浏览器 Origin。
- 模型路径必须落在明确配置的模型根目录内。
- 网页不提供任意 YAML、Shell 命令或直接结束 Windows 进程的入口。
- 进程区域只复制命令，由操作者在 CMD 中自行确认执行。
- 所有配置写入先备份；热重载失败会尝试恢复写入前配置。

这不是多用户网络服务。若要暴露到局域网或互联网，应另行设计认证、TLS、访问控制和进程管理策略。

### 开发与测试

安装开发依赖后运行：

```bash
uv run --isolated --extra dev pytest -q
node --check src/llama_swap_console/web/app.js
git diff --check
```

`tests/browser/verify_console.py` 使用模拟 API 验证界面，不修改真实配置。需要对已启动的本地
服务做浏览器验收时，可运行：

```bash
python tests/browser/verify_live_console.py
```

该脚本需要 Playwright 浏览器和可访问的 `http://localhost:9293`，并会把截图写入已忽略的
`test-results/live-screenshots/`。

---

## English

`llama-swap Console` is a local management console for llama-swap on Windows 11
and WSL2. It serves configuration and runtime controls on `127.0.0.1:9293`; the
inference API and original llama-swap UI remain on `127.0.0.1:9292`. The two are
separate services. This console does not replace llama-swap.

The UI defaults to Chinese and can switch to English from the page header or the
editor dialog. Model weights and the primary llama-swap configuration are treated
as user data: install, update, and uninstall operations do not delete them.

### Features

- Inspect configured models, structured launch settings, runtime state, and
  llama-swap availability.
- Scan GGUF and Hugging Face safetensors models under `/mnt/d/AI/models`, then
  register complete candidates.
- Filter auxiliary models such as `mmproj`, embedding, reranker, draft, and
  dflash/eagle GGUF files. Incomplete Hugging Face downloads remain visible but
  cannot be registered.
- Edit common llama.cpp and vLLM settings in a modal dialog. The launcher, port
  template, and raw compatibility arguments stay read-only so unsupported command
  arguments cannot be silently lost.
- Validate YAML, model paths, and configuration revisions before saving. Create a
  backup before each write and restore the attempted change if hot reload fails.
- Load or unload one model or all models. Concurrent requests for the same model
  are coalesced to prevent duplicate upstream operations.
- Show physical NVIDIA memory usage and per-process Windows WDDM allocations.
  Select the discrete GPU or all adapters. Process rows only copy a
  `taskkill /PID <PID> /F` command; the browser never terminates a process.
- Forward llama-swap live event logs and provide Chinese/English UI switching.

### Architecture and ports

```text
Windows browser
  |-- http://localhost:9293  -> llama-swap Console (WSL user service)
  |                               |-- config.yaml / backups
  |                               |-- /mnt/d/AI/models scan
  |                               |-- nvidia-smi + Windows WDDM query
  |
  `-- http://localhost:9292  -> llama-swap (existing inference API and UI)
                                    `-- llama.cpp / vLLM model processes
```

| Address | Purpose |
| --- | --- |
| `http://localhost:9293` | This project's management console |
| `http://localhost:9292` | Existing llama-swap inference API |
| `http://localhost:9292/ui` | Existing llama-swap UI |

The systemd user service is named `llama-swap-console.service` and binds to
`127.0.0.1:9293`. Do not run a second manual uvicorn instance at the same time.

### Prerequisites

- Windows 11 and WSL2 Ubuntu.
- systemd enabled in WSL.
- Python 3.12 or newer and `python3-venv` inside WSL.
- A working llama-swap instance listening on `127.0.0.1:9292`.
- llama-swap configuration at `~/.config/llama-swap/config.yaml`.
- Models in the default root `/mnt/d/AI/models`.

To enable systemd in WSL, add this to `/etc/wsl.conf`:

```ini
[boot]
systemd=true
```

Then run this in Windows PowerShell and reopen Ubuntu:

```powershell
wsl --shutdown
```

### Install

Run this inside WSL from the repository directory:

```bash
cd /mnt/d/projects/just-thinking/llama-swap-console
bash scripts/install-wsl.sh
```

The installer verifies WSL2, Python, and user systemd; creates an isolated virtual
environment at `~/.local/share/llama-swap-console/.venv`; installs the current
source; enables and restarts the user service; then checks
`http://127.0.0.1:9293/api/health`.

Open <http://localhost:9293> in a Windows browser when it completes.

### Update

After pulling or changing source code, rerun the installer:

```bash
cd /mnt/d/projects/just-thinking/llama-swap-console
bash scripts/install-wsl.sh
```

It upgrades the console environment, refreshes the unit, and restarts the service.
It does not rebuild model files, remove weights, or overwrite the llama-swap
configuration.

### Uninstall

```bash
cd /mnt/d/projects/just-thinking/llama-swap-console
bash scripts/uninstall-wsl.sh
```

The uninstaller only stops and removes `llama-swap-console.service`. It keeps model
files, `~/.config/llama-swap/config.yaml`, backups, and the virtual environment.
Remove `~/.local/share/llama-swap-console` manually only after confirming that path.

### Configuration, scanning, and defaults

Defaults can be overridden with environment variables prefixed by
`LLAMA_SWAP_CONSOLE_`. The included systemd unit uses these values:

| Item | Default |
| --- | --- |
| llama-swap configuration | `~/.config/llama-swap/config.yaml` |
| Model root | `/mnt/d/AI/models` |
| llama-swap URL | `http://127.0.0.1:9292` |
| Console listener | `127.0.0.1:9293` |
| Backup directory | `~/.local/state/llama-swap-console/backups` |
| Retained backups | 20 |

Scan results are cached for five minutes. To register a candidate, its path must be
inside an allowed model root, its download must be complete, and an existing,
parseable configured model for the same backend must be available as a trusted
launcher template. The console does not guess or download launchers.

Candidate context defaults are intentionally conservative and are based on total
weight size: under 12 GiB uses 64K; 12--20 GiB uses 32K; 20--24 GiB uses 16K; and
24 GiB or more uses 8K. vLLM candidates start with one sequence, FP8 KV cache, at
most 4096 batched tokens, chunked prefill enabled, and MTP disabled. These values
are editable starting points, not guarantees that a particular GPU or model can
reliably sustain that context length.

For existing models, the backend, launcher, port template, and unstructured
compatibility arguments are immutable. The model path and visible inference
settings can be saved after validation. Each write is revision-checked to avoid
overwriting external changes and creates a backup first.

See [docs/operations.md](docs/operations.md) for observed deployment settings and
operational notes.

### Model lifecycle and HTTP 202

When a load or unload needs time in llama-swap, the console can return HTTP
`202 Accepted`:

| `status` | Meaning |
| --- | --- |
| `starting` | Upstream reports that the model is starting, or the same operation is already in progress. |
| `loading` | The upstream running state explicitly reports loading. |
| `pending` | The upstream accepted the load request but the running state cannot yet confirm it. |

The browser disables related controls and refreshes model status once per second,
up to 30 times. A `202` is not a failure, so do not repeatedly click Load. A
connection failure to llama-swap produces `503`; a non-success upstream response
produces `502`.

### Operations

```bash
# Service status
systemctl --user status llama-swap-console

# Follow logs
journalctl --user -u llama-swap-console -f

# Restart the console
systemctl --user restart llama-swap-console

# Health check
curl http://127.0.0.1:9293/api/health
```

### Troubleshooting

#### 9293 does not start or the page is unavailable

Check the port and service logs:

```bash
ss -ltnp | grep ':9293'
systemctl --user status llama-swap-console
journalctl --user -u llama-swap-console -n 80 --no-pager
```

The service always binds to `127.0.0.1:9293`. If the health check works in WSL but
the Windows browser cannot connect:

1. Run `wsl --shutdown` in Windows PowerShell and restart WSL.
2. Check that `%UserProfile%\.wslconfig` does not disable `localhostForwarding`.
3. Confirm that no Windows application occupies 9293 and that the unit was not
   changed to a different address or port.

#### 503, unavailable model state, or disconnected live logs

Port 9293 depends on an already-running llama-swap. Verify it from WSL:

```bash
curl http://127.0.0.1:9292/v1/models
```

If this fails, restore llama-swap first. `202 starting`, `loading`, and `pending`
are normal transition states during model startup; wait for status refresh instead
of sending repeated concurrent requests.

#### A model is missing from Unregistered models

- Confirm that it is in `/mnt/d/AI/models`, or in a model root explicitly allowed
  through service environment variables.
- GGUF auxiliary files, vision projectors, embedding, reranker, draft, and
  dflash/eagle files are intentionally filtered from chat-model registration.
- A Hugging Face directory needs `config.json`, a tokenizer file, and safetensors
  weights. `.part`, `.crdownload`, `.tmp`, or missing shards mark it incomplete.
- Already configured models are not duplicated as candidates.

#### Save failure, 409, or failed hot reload

- `409` means another process changed `config.yaml` after the editor opened. Refresh
  the page and edit again.
- `422` means validation rejected the structured settings, path, or launcher template.
- If hot reload cannot be confirmed, the console automatically restores the
  configuration from before that write. It never alters model weights.

To restore a backup manually:

```bash
systemctl --user stop llama-swap-console
ls -lt ~/.local/state/llama-swap-console/backups/
cp --preserve=mode <chosen-backup-file> ~/.config/llama-swap/config.yaml
systemctl --user restart llama-swap-console
```

Copy the current `config.yaml` first if you need to preserve its current state.

#### NVIDIA total memory and WDDM process rows do not add up

The NVIDIA total comes from `nvidia-smi` and represents physical discrete-GPU
memory. The process table comes from Windows WDDM and represents graphics resource
allocations. Shared surfaces can be counted for more than one process, so WDDM rows
must not be summed and need not equal the NVIDIA total. Selecting the detected
NVIDIA discrete GPU is usually best for local-model diagnosis; All adapters is for
viewing both integrated and discrete GPUs.

### Security boundaries

- The console and included service bind to loopback by default. Write operations
  reject browser Origins other than `localhost`, `127.0.0.1`, and `::1`.
- Model paths must remain under explicitly configured model roots.
- The browser exposes no arbitrary YAML editor, shell-command runner, or direct
  Windows process termination endpoint.
- The process panel only copies a command for the operator to review and run in CMD.
- Every configuration write is backed up, and a failed hot reload attempts to
  restore the pre-write configuration.

This is not a multi-user network service. Exposing it to a LAN or the internet
requires a separate authentication, TLS, access-control, and process-management
design.

### Development and testing

After installing development dependencies, run:

```bash
uv run --isolated --extra dev pytest -q
node --check src/llama_swap_console/web/app.js
git diff --check
```

`tests/browser/verify_console.py` uses mocked APIs and does not modify a real
configuration. To run browser acceptance against an already-running local service:

```bash
python tests/browser/verify_live_console.py
```

That script requires Playwright browsers and an accessible
`http://localhost:9293`; screenshots are written to the ignored
`test-results/live-screenshots/` directory.
