#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="llama-swap-console.service"
USER_UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_PATH="${USER_UNIT_DIR}/${SERVICE_NAME}"
EXPECTED_PATH="$(realpath -m -- "${UNIT_PATH}")"

if [[ "${EXPECTED_PATH}" != "${UNIT_PATH}" ]]; then
  echo "拒绝卸载：服务文件路径解析结果异常：${EXPECTED_PATH}" >&2
  exit 1
fi

systemctl --user disable --now llama-swap-console.service 2>/dev/null || true

if [[ -f "${UNIT_PATH}" ]]; then
  rm -f -- "${UNIT_PATH}"
fi

systemctl --user daemon-reload
systemctl --user reset-failed "${SERVICE_NAME}" 2>/dev/null || true

cat <<'EOF'
llama-swap Console 服务已卸载。
虚拟环境、管理台备份、llama-swap 配置和模型文件均已保留。
EOF
