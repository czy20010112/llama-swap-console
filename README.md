# llama-swap Console

这是为 Windows 11 + WSL2 上的 llama-swap 提供的本地管理台。它监听
`127.0.0.1:9293`，负责结构化配置、模型扫描、加载/卸载、日志和 Windows WDDM
显存进程展示；推理 API 仍由 `127.0.0.1:9292` 的 llama-swap 提供。

管理台默认中文，可切换英文。网页不提供任意 YAML、Shell 命令或直接结束 Windows
进程的入口。显存进程行只复制 `taskkill /PID <PID> /F`，由你在 CMD 中确认执行。

## 环境要求

- Windows 11、WSL2 Ubuntu，WSL 已启用 systemd。
- Python 3.12 或更高版本及 `python3-venv`。
- llama-swap 已监听 `127.0.0.1:9292`。
- 配置文件：`~/.config/llama-swap/config.yaml`。
- 模型目录：`/mnt/d/AI/models`。

若 WSL 尚未启用 systemd，在 `/etc/wsl.conf` 中加入：

```ini
[boot]
systemd=true
```

随后在 Windows PowerShell 执行 `wsl --shutdown`，重新进入 Ubuntu。

## 安装

在 WSL 中进入本仓库目录并执行：

```bash
cd /mnt/d/projects/just-thinking/llama-swap-console
bash scripts/install-wsl.sh
```

脚本会创建 `~/.local/share/llama-swap-console/.venv`，将当前源码安装到独立虚拟
环境，安装并启动 systemd 用户服务，然后检查健康接口。重复执行同一命令即可更新，
不会重复创建配置或修改模型权重。

启动成功后，在 Windows 浏览器打开：

- 管理台：<http://localhost:9293>
- llama-swap 原管理页：<http://localhost:9292/ui>

## 常用运维

```bash
# 状态
systemctl --user status llama-swap-console

# 实时日志
journalctl --user -u llama-swap-console -f

# 重启
systemctl --user restart llama-swap-console

# 健康检查
curl http://127.0.0.1:9293/api/health
```

### 端口占用

若 9293 启动失败，先检查端口占用：

```bash
ss -ltnp | grep ':9293'
```

管理台的 unit 固定监听 `127.0.0.1:9293`。不要同时手工启动第二个 uvicorn 实例。

### Windows localhost 转发

新版 WSL2 默认会把 WSL 的 localhost 映射到 Windows。若
`curl http://127.0.0.1:9293/api/health` 在 WSL 内成功，但 Windows 浏览器打不开：

1. 在 Windows PowerShell 执行 `wsl --shutdown` 后重开 WSL。
2. 检查 `%UserProfile%\.wslconfig` 是否禁用了 `localhostForwarding`。
3. 确认服务没有改成监听其他端口，且 Windows 没有程序占用 9293。

### 配置回滚与手工恢复

管理台每次保存前会把旧配置备份到：

```text
~/.local/state/llama-swap-console/backups/
```

保存后若 llama-swap 拒绝热重载，管理台会自动回滚本次修改。需要手工恢复时：

```bash
systemctl --user stop llama-swap-console
ls -lt ~/.local/state/llama-swap-console/backups/
cp --preserve=mode <选定的备份文件> ~/.config/llama-swap/config.yaml
systemctl --user restart llama-swap-console
```

恢复前建议再复制一份当前 `config.yaml`。模型启动失败不会触碰模型权重。

## 卸载

```bash
bash scripts/uninstall-wsl.sh
```

卸载脚本只停止并移除 `llama-swap-console.service` unit。它不会删除模型文件，
不会删除 llama-swap 配置，也不会删除管理台备份或虚拟环境。需要彻底清理虚拟环境时，
请在确认路径后另行处理 `~/.local/share/llama-swap-console`。

## 开发验证

```bash
uv run --isolated --extra dev pytest -q
node --check src/llama_swap_console/web/app.js
```

浏览器验收脚本位于 `tests/browser/verify_console.py`，会模拟 API，不修改真实配置。
