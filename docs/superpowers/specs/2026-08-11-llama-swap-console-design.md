# llama-swap Console 设计说明

日期：2026-08-11  
状态：待用户最终审阅  
目标环境：Windows 11 + WSL2 Ubuntu + RTX 5090 32GB + llama-swap v249 + Cherry Studio

## 1. 背景与目标

现有 llama-swap 运行在 WSL2，监听 `127.0.0.1:9292`，配置文件为：

```text
/home/czy098/.config/llama-swap/config.yaml
```

llama-swap 自带的 `9292/ui` 能查看模型、加载/卸载模型、查看日志与性能，但没有读取或保存原始配置的写接口。llama-swap 也不会扫描模型目录并自动登记模型，只有已经写入 YAML `models` 节点的模型才会出现在 `/v1/models`。

本项目新增一个独立的本地管理台，监听 `127.0.0.1:9293`，提供：

- 中文/英文界面，默认中文。
- 结构化模型启动配置编辑，不暴露原始 YAML 编辑器。
- 模型目录扫描，发现但不自动登记模型。
- 模型加载、卸载、健康检查和实时日志。
- Windows 与 WSL GPU 状态、进程和专用显存展示。
- 配置验证、备份、原子保存与错误提示。
- 与 llama-swap 视觉风格协调的简洁浅色界面。

`9292` 继续承担推理 API 和原生 llama-swap 管理能力；`9293` 不代理推理请求，也不替代 Cherry Studio。

## 2. 已确认的产品决策

### 2.1 独立管理台

采用独立服务，不 fork 或修改 llama-swap。原因：

- llama-swap 升级不会覆盖管理台。
- Windows GPU 计数器和配置写入逻辑可以保持独立。
- `9292/ui` 仍可用于对照和应急操作。
- 避免注入或反向代理 llama-swap 前端带来的版本耦合。

### 2.2 配置编辑边界

- 只提供结构化表单，不提供原始 YAML 编辑器。
- 已知参数翻译成中文字段，英文模式显示对应英文标签。
- 命令行中未识别的参数显示在只读“兼容参数”区，并在保存时原样保留。
- 不允许从网页输入任意 shell 命令。

### 2.3 模型发现

- 扫描 `/mnt/d/AI/models`。
- `.gguf` 文件识别为 llama.cpp 候选模型。
- 同时包含 `config.json` 和 safetensors 权重的目录识别为 Hugging Face/vLLM 候选模型。
- 扫描结果进入“待登记模型”，不自动修改配置。
- 用户确认后选择后端、上下文和加速参数，再加入 llama-swap。

### 2.4 进程操作边界

- 网页不直接结束 Windows 进程。
- GPU 进程表每行提供复制按钮，复制以下 CMD 命令：

```cmd
taskkill /PID <PID> /F
```

- 对系统或受保护进程提示“可能需要管理员 CMD”。
- 不提供删除模型文件、结束进程或执行任意命令的服务端 API。

## 3. 视觉与交互设计

### 3.1 视觉方向

- 白底黑字，页面背景使用轻微灰白区分工作区。
- 6-8px 圆角矩形；不使用大圆角、渐变、装饰光斑或营销式卡片。
- 紧凑、安静、面向重复运维操作。
- 主色为近黑色，状态色仅用于成功、警告和错误。
- 字号固定，不随视口宽度缩放。
- 默认浅色主题；保留未来加入深色主题的变量结构，但第一版不要求主题切换。

### 3.2 主布局

采用三栏布局：

1. 左栏：搜索、正在运行、全部模型、待登记模型、扫描入口。
2. 中栏：当前模型的只读配置、健康状态、加载/卸载/重新加载操作。
3. 右栏：GPU 总览、Windows 显存进程、实时日志。

窄屏时隐藏右栏，将 GPU 与日志移动到独立标签页；模型配置仍保持可读。

### 3.3 展示与编辑分离

模型详情页只读展示配置。点击“编辑设置”打开模态窗口：

- 表单按“基础设置、显存与上下文、加速与缓存、工具与能力”分组。
- 底部操作为“取消、仅保存、保存并重新加载”。
- 保存前显示“将验证并备份当前配置”。
- 校验错误定位到具体字段，不关闭弹窗。
- 保存成功后关闭弹窗并刷新只读详情。

### 3.4 国际化

- 默认中文，可切换 English。
- 字段名、帮助文本、状态、错误信息全部通过翻译字典提供。
- 模型 ID、文件路径、命令行参数和日志保持原文。
- 语言选择保存在浏览器本地存储中。

## 4. 系统架构

### 4.1 进程与端口

```text
Cherry Studio / API 客户端
        |
        v
llama-swap :9292 --------------> llama.cpp / vLLM 子进程
        ^
        | 模型操作、状态、事件流
        |
llama-swap-console :9293
        | 配置读写
        +-----------------------> config.yaml
        | Windows 性能计数器
        +-----------------------> powershell.exe / Get-Counter
```

管理台以 WSL systemd user service 运行，只监听 `127.0.0.1`。

### 4.2 技术选择

- 后端：Python 3.12 + FastAPI + Uvicorn。
- YAML：`ruamel.yaml`，保持键顺序、注释和未编辑字段。
- 前端：静态单页应用，模块化 JavaScript、CSS 和本地 SVG 图标资源；不依赖 CDN。
- 测试：pytest + HTTP 集成测试；Playwright 用于浏览器流程和截图检查。
- 服务：`~/.config/systemd/user/llama-swap-console.service`。

### 4.3 模块边界

- `config_store`：加载、解析、备份、原子保存、恢复配置。
- `command_codec`：在 llama.cpp/vLLM 命令 tokens 与结构化字段之间往返转换。
- `model_scanner`：扫描 GGUF 和 Hugging Face 目录并去重。
- `llama_swap_client`：调用 `9292` 的模型、卸载、加载、日志和状态接口。
- `gpu_monitor`：读取 GPU 总量、Windows 进程显存、进程名、路径和服务名。
- `api`：只暴露受限的管理操作，不接受原始命令。
- `web`：模型列表、只读详情、编辑模态框、GPU 表和日志。

## 5. 配置数据模型

### 5.1 公共字段

- 模型 ID / Model ID
- 显示名称 / Display name
- 描述 / Description
- 模型路径 / Model path
- 推理后端 / Backend
- 上下文长度 / Context length
- 是否在模型列表显示 / Listed
- 输入能力：文本、图片
- 输出能力：文本
- 工具调用能力

### 5.2 llama.cpp 字段

- `--n-gpu-layers`
- `--ctx-size`
- `--flash-attn`
- `--cache-type-k`
- `--cache-type-v`
- `--jinja`
- `--mmproj`
- `--model-draft`
- `--spec-type`
- `--spec-draft-n-max`
- 温度、top-p、top-k、min-p、重复惩罚

### 5.3 vLLM 字段

- `--max-model-len`
- `--gpu-memory-utilization`
- `--kv-cache-dtype`
- `--dtype`
- `--quantization`
- `--max-num-seqs`
- `--max-num-batched-tokens`
- `--enable-chunked-prefill`
- `--trust-remote-code`
- `--reasoning-parser`
- `--enable-auto-tool-choice`
- `--tool-call-parser`
- `--speculative-config` 的 method、model、num_speculative_tokens
- `--safetensors-load-strategy`

### 5.4 参数往返规则

- 使用 `shlex` 解析命令，不使用字符串切割。
- `${MODEL_ID}` 和 `${PORT}` 保持为 llama-swap 模板变量。
- 已知字段按固定顺序重新生成。
- 未识别 tokens 作为不可编辑数组附在已知字段之后。
- 解析后立即进行“解析 -> 生成 -> 再解析”一致性测试；不一致时禁止保存。

## 6. 保存、验证与备份

### 6.1 保存流程

1. 验证请求体字段类型和范围。
2. 验证模型路径、后端可执行文件和引用文件存在。
3. 将结构化字段编码为命令 tokens。
4. 把修改应用到内存中的 YAML 文档。
5. 写入同目录临时文件并重新解析验证。
6. 将当前配置复制到备份目录。
7. 通过同文件系统原子替换正式配置。
8. 等待 llama-swap 配置热重载，并刷新 `/v1/models`。

### 6.2 备份规则

- 备份目录：`~/.local/state/llama-swap-console/backups/`。
- 文件名包含 UTC 时间戳。
- 默认保留最近 20 份。
- 第一版不在 UI 提供任意文件恢复；只提供最近一次配置回滚。

### 6.3 保存模式

- “仅保存”：更新配置并确认 llama-swap 接受热重载，不加载模型。
- “保存并重新加载”：保存后卸载同 ID 的旧实例，再请求加载并等待健康检查。
- 模型运行失败不删除配置；UI 展示完整日志和失败阶段。

## 7. 模型操作与日志

管理台复用 llama-swap 的现有接口：

- 模型列表：`GET /v1/models`
- 加载：`GET /upstream/{model}/`
- 卸载单模型：`POST /api/models/unload/{model}`
- 卸载全部：`POST /api/models/unload`
- 状态和日志：`GET /api/events`（SSE）
- 运行状态：`GET /running`
- 硬件状态：`GET /api/hardware`

后端对模型 ID 做严格白名单校验，只允许操作当前配置中存在的模型。

## 8. GPU 与 Windows 进程

### 8.1 数据源

- GPU 总显存、已用显存、利用率和温度：NVIDIA SMI/NVML。
- Windows 每进程专用显存：

```powershell
Get-Counter '\GPU Process Memory(*)\Dedicated Usage'
```

- 进程名与路径：`Get-Process -Id <PID>`。
- 关联服务名：查询 `Win32_Service` 中 `ProcessId` 相同的服务。

不能仅依赖 `nvidia-smi --query-compute-apps`，因为 Windows WDDM 下 `used_memory` 通常返回 `N/A`。

### 8.2 表格行为

- 默认按专用显存降序。
- 字段：进程名、服务名、PID、专用显存、路径、来源。
- 支持按进程名、服务名和 PID 搜索。
- 显存统一显示 MiB/GiB，并保留原始 byte 值用于排序。
- 多个 GPU Process Memory instance 属于同一 PID 时求和。
- 无法读取名称时保留 PID，并显示“权限不足”。

### 8.3 结束命令复制

每行提供复制图标，复制：

```cmd
taskkill /PID <PID> /F
```

复制后显示短暂“已复制”状态。系统、桌面合成器和受保护进程显示额外警告。网页不执行该命令。

## 9. 模型扫描与登记

### 9.1 GGUF

- 每个 `.gguf` 文件作为单独候选。
- 扫描器读取文件大小和 GGUF metadata；读取失败仍显示文件，但标记“元数据不可读”。
- 默认后端为 llama.cpp。
- 不自动判断量化质量，只展示文件名、量化元数据和大小。

### 9.2 Hugging Face/vLLM

- 目录必须包含 `config.json`、tokenizer 文件和至少一个完整 safetensors 权重或索引。
- `.crdownload`、`.part` 和缺失索引分片的目录标记为“下载未完成”。
- 从 `quantization_config.quant_method` 提示后端参数，但不擅自覆盖模型卡要求。
- MTP 文件和 speculative 配置作为独立能力检查。

### 9.3 去重

- 规范化 WSL 路径后与现有模型命令中的路径比较。
- 同一路径已经登记时不进入待登记列表。
- 文件移动或路径失效时，在原模型上显示警告，不自动删除。

## 10. 当前模型的专用结论

### 10.1 Fable Fusion NVFP4A16

模型目录完整：

```text
/mnt/d/AI/models/Qwen3.6-27B-Fable-Fusion-711-Uncensored-Heretic-NM-DAU-MTP-NVFP4A16
```

权重包括：

```text
model.safetensors             27,702,363,760 bytes
model-mtp-bf16.safetensors       849,400,424 bytes
```

模型为 compressed-tensors NVFP4A16，敏感层和 MTP 保持 BF16。初始登记配置：

- 后端：vLLM 0.27
- 上下文：32768
- GPU 显存使用率：0.85
- MTP：method `mtp`，草稿深度 5
- 最大并发：1
- 分块预填充：开启
- reasoning parser：`qwen3`
- 自动工具调用：开启
- tool parser：`qwen3_coder`
- safetensors load strategy：`prefetch`

配置加入后必须进行一次真实启动、纯文本生成和标准 OpenAI tool call 测试。若显存不足，优先降低上下文或 MTP 深度，不修改模型权重。

### 10.2 Qwen3.6 35B-A3B GGUF

失败不是 Linux 路径或显存问题。当前最新版 llama.cpp 报错：

```text
key qwen35moe.rope.dimension_sections has wrong array length; expected 4, got 3
```

该 GGUF 的 RoPE metadata 由旧版或非标准转换器生成，与当前 llama.cpp 的 Qwen35 MoE 读取规则不一致。Windows 与 Linux 使用同一版 llama.cpp 时行为应一致；Bionic、LM Studio 或其他 Windows 程序可能捆绑旧版/私有兼容补丁，因此表现可能不同。

第一版管理台只检测并展示此错误，不自动改写 GGUF。修复应使用已验证的重新转换文件，或另行制作带备份和前后 metadata 验证的专用修复流程。

### 10.3 目录中的其他 GGUF

当前目录包含多个未登记 GGUF。它们没有出现在 llama-swap，是因为配置中没有对应 `models` 条目，而不是扫描失败。管理台上线后会将它们显示为“待登记模型”。

## 11. API 设计

第一版管理 API：

```text
GET    /api/health
GET    /api/settings
GET    /api/models
GET    /api/models/{id}
PUT    /api/models/{id}
POST   /api/models/{id}/load
POST   /api/models/{id}/unload
POST   /api/models/unload-all
GET    /api/models/{id}/logs
GET    /api/events
POST   /api/scan
GET    /api/discovered-models
POST   /api/discovered-models/{candidate_id}/register
GET    /api/gpu
POST   /api/config/rollback-latest
```

所有写 API 只接受预定义 JSON schema。路径必须位于允许的模型根目录或已存在的配置引用中。

## 12. 错误处理

- 配置解析失败：禁止编辑和保存，展示文件位置与解析错误。
- 路径不存在：表单字段报错，不写配置。
- llama-swap 不可用：保留配置编辑只读展示，禁用加载/卸载。
- 保存后热重载失败：自动恢复本次保存前的配置，并记录审计日志。
- 模型加载失败：保留配置，展示启动阶段和最后日志。
- Windows 计数器不可用：GPU 总量仍显示，进程区展示明确降级原因。
- PowerShell 权限不足：显示能取得的 PID 和显存，不伪造进程名。
- SSE 中断：指数退避重连，界面显示“日志连接中断”。

## 13. 测试与验收

### 13.1 单元测试

- llama.cpp 参数解析与生成往返。
- vLLM 参数解析与生成往返。
- 未识别参数保留。
- YAML 注释、顺序和非模型配置保持。
- 备份保留数量和原子保存。
- GGUF/HF 扫描、下载未完成识别和去重。
- Windows GPU counter instance 聚合、PID 映射和显存降序。
- `taskkill` 命令只使用验证后的整数 PID。
- 中英文翻译键完整。

### 13.2 集成测试

- 使用临时配置完成读取、编辑、保存和回滚。
- 对 `9292` 的列表、加载、卸载和 SSE 代理。
- llama-swap 不可用和超时行为。
- Fable 模型真实加载、短文本生成和 tool call。

### 13.3 浏览器验收

- 桌面 1440x900 和 1920x1080。
- 移动 390x844。
- 文本不溢出、不重叠。
- 编辑弹窗可滚动，底部保存操作始终可见。
- 中英文切换后字段布局稳定。
- GPU 表默认按显存降序。
- 复制按钮产生正确 CMD 命令并显示反馈。

## 14. 非目标

第一版不包括：

- 原始 YAML 或 shell 命令编辑器。
- 从网页下载、删除、移动或修改模型权重。
- 自动修补 GGUF metadata。
- 在网页内结束 Windows 进程。
- 多用户、远程访问、账号系统或公网部署。
- 替代 Cherry Studio 的聊天界面。

## 15. 交付与运行

- 项目目录：`D:\projects\just-thinking\llama-swap-console`。
- WSL 服务监听：`http://127.0.0.1:9293`。
- llama-swap 保持：`http://127.0.0.1:9292`。
- systemd user service 开机随 WSL 用户服务启动。
- 前端、API、测试、安装脚本和卸载说明包含在同一项目中。

