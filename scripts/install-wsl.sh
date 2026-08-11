#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="llama-swap-console.service"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
INSTALL_DIR="${HOME}/.local/share/llama-swap-console"
VENV_DIR="${INSTALL_DIR}/.venv"
USER_UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_PATH="${USER_UNIT_DIR}/${SERVICE_NAME}"
SOURCE_UNIT="${PROJECT_ROOT}/deploy/${SERVICE_NAME}"
HEALTH_URL="http://127.0.0.1:9293/api/health"

if [[ ! -r /proc/version ]] || ! grep -qi microsoft /proc/version; then
  echo "错误：此安装脚本只用于 WSL2。" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "错误：未找到 python3，请先安装 Python 3.12 或更高版本。" >&2
  exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 12))'; then
  echo "错误：需要 Python 3.12 或更高版本。当前版本：$(python3 --version 2>&1)" >&2
  exit 1
fi

if ! systemctl --user show-environment >/dev/null 2>&1; then
  cat >&2 <<'EOF'
错误：当前 WSL 用户的 systemd 服务不可用。
请确认 /etc/wsl.conf 包含：

[boot]
systemd=true

然后在 Windows PowerShell 执行 wsl --shutdown，再重新进入 WSL。
EOF
  exit 1
fi

mkdir -p "${INSTALL_DIR}" "${USER_UNIT_DIR}" \
  "${HOME}/.local/state/llama-swap-console/backups"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

if command -v uv >/dev/null 2>&1; then
  uv pip install --quiet --python "${VENV_DIR}/bin/python" --upgrade "${PROJECT_ROOT}"
else
  "${VENV_DIR}/bin/python" -m pip install --quiet --upgrade "${PROJECT_ROOT}"
fi
install -m 0644 "${SOURCE_UNIT}" "${UNIT_PATH}"

systemctl --user daemon-reload
systemctl --user enable --now llama-swap-console.service
systemctl --user restart llama-swap-console.service

healthy=0
for _ in {1..30}; do
  if command -v curl >/dev/null 2>&1; then
    if curl --fail --silent --show-error "${HEALTH_URL}" >/dev/null; then
      healthy=1
      break
    fi
  elif "${VENV_DIR}/bin/python" -c \
    'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2).read()' \
    "${HEALTH_URL}" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 1
done

if [[ "${healthy}" -ne 1 ]]; then
  echo "错误：服务启动后未通过健康检查。" >&2
  systemctl --user --no-pager --full status "${SERVICE_NAME}" >&2 || true
  journalctl --user -u "${SERVICE_NAME}" -n 80 --no-pager >&2 || true
  exit 1
fi

systemctl --user --no-pager --full status "${SERVICE_NAME}" | sed -n '1,12p' || true
cat <<'EOF'

安装完成。
管理台：http://localhost:9293
推理 API 仍由 llama-swap 提供：http://localhost:9292
EOF
