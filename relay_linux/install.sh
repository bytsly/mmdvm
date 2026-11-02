#!/usr/bin/env bash
#
# P2P 中继（点名软件校验 + MMDVM 联系人同步）Linux 一键安装脚本
#
# 用法: sudo bash install.sh
# 同目录需包含: relay_server.py、p2p-relay.service
# 若同目录有 relay_data.db，会一并导入（保留已同步的联系人修改）
#
set -euo pipefail

SERVICE_NAME="p2p-relay"
INSTALL_DIR="/opt/p2p-relay"
HTTP_PORT="4570"
MMDVM_PORT="46001"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPEN_FIREWALL="no"

usage() {
  cat <<'EOF'
用法: sudo bash install.sh [选项]

  --src DIR          含 relay_server.py 的目录（默认: 本脚本所在目录）
  --install-dir DIR  安装目录（默认: /opt/p2p-relay）
  --http-port PORT   中继 HTTP 端口（默认: 4570）
  --mmdvm-port PORT  更新软件联系人同步 TCP 端口（默认: 46001，0=关闭）
  --open-firewall    自动放行端口（支持 firewalld / ufw）
  -h, --help         显示本帮助
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --src)            SRC_DIR="$2"; shift 2 ;;
    --install-dir)    INSTALL_DIR="$2"; shift 2 ;;
    --http-port)      HTTP_PORT="$2"; shift 2 ;;
    --mmdvm-port)     MMDVM_PORT="$2"; shift 2 ;;
    --open-firewall)  OPEN_FIREWALL="yes"; shift ;;
    -h|--help)        usage; exit 0 ;;
    *) echo "未知参数: $1"; echo; usage; exit 1 ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  echo "错误: 请用 root 运行（sudo bash install.sh）"
  exit 1
fi

if [ ! -f "$SRC_DIR/relay_server.py" ]; then
  echo "错误: 在 $SRC_DIR 下找不到 relay_server.py"
  echo "      可先用 --src 指定目录，或把 relay_server.py 放到本脚本同目录"
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "错误: 未找到 $PYTHON_BIN，请先安装 Python 3.7+"
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)'; then
  echo "错误: 需要 Python 3.7 及以上，当前版本: $("$PYTHON_BIN" -V 2>&1)"
  exit 1
fi

echo "==> 创建系统用户 $SERVICE_NAME"
if ! id -u "$SERVICE_NAME" >/dev/null 2>&1; then
  NOLOGIN_SH="$(command -v nologin || echo /usr/sbin/nologin)"
  useradd --system --no-create-home --shell "$NOLOGIN_SH" "$SERVICE_NAME"
  echo "    已创建"
else
  echo "    已存在，跳过"
fi

echo "==> 准备安装目录 $INSTALL_DIR"
install -d -m 0755 -o "$SERVICE_NAME" -g "$SERVICE_NAME" "$INSTALL_DIR"
install -m 0644 -o "$SERVICE_NAME" -g "$SERVICE_NAME" \
  "$SRC_DIR/relay_server.py" "$INSTALL_DIR/relay_server.py"

if [ -f "$INSTALL_DIR/relay_data.db" ]; then
  echo "    保留已有数据库 relay_data.db（含历史联系人修改）"
elif [ -f "$SRC_DIR/relay_data.db" ]; then
  install -m 0644 -o "$SERVICE_NAME" -g "$SERVICE_NAME" \
    "$SRC_DIR/relay_data.db" "$INSTALL_DIR/relay_data.db"
  echo "    已导入 relay_data.db"
else
  echo "    未发现 relay_data.db，首次启动自动创建空库"
fi

echo "==> Python 语法检查"
"$PYTHON_BIN" -m py_compile "$INSTALL_DIR/relay_server.py"
rm -rf "$INSTALL_DIR/__pycache__"
echo "    通过"

echo "==> 安装 systemd 服务"
UNIT_SRC="$SRC_DIR/p2p-relay.service"
UNIT_DST="/etc/systemd/system/${SERVICE_NAME}.service"
if [ ! -f "$UNIT_SRC" ]; then
  echo "错误: 找不到 $UNIT_SRC"
  exit 1
fi
sed -e "s#/opt/p2p-relay#${INSTALL_DIR}#g" \
    -e "s#--port 4570#--port ${HTTP_PORT}#g" \
    -e "s#--mmdvm-port 46001#--mmdvm-port ${MMDVM_PORT}#g" \
    "$UNIT_SRC" > "$UNIT_DST"
chown root:root "$UNIT_DST"
chmod 0644 "$UNIT_DST"
chown -R "$SERVICE_NAME:$SERVICE_NAME" "$INSTALL_DIR"
echo "    已写入 $UNIT_DST"

echo "==> 启动服务"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
systemctl restart "$SERVICE_NAME"

sleep 2
if ! systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "错误: 服务未启动，最近日志："
  journalctl -u "$SERVICE_NAME" -n 20 --no-pager || true
  exit 1
fi

echo "==> 健康检查 http://127.0.0.1:${HTTP_PORT}/health"
if ! "$PYTHON_BIN" - "$HTTP_PORT" <<'PY'
import json, sys, urllib.request
port = sys.argv[1]
try:
    with urllib.request.urlopen("http://127.0.0.1:%s/health" % port, timeout=5) as r:
        data = json.loads(r.read().decode("utf-8"))
except Exception as ex:
    print("    失败: %s" % ex)
    sys.exit(1)
print("    成功: %s" % json.dumps(data, ensure_ascii=False)[:300])
PY
then
  echo "错误: 健康检查未通过，最近日志："
  journalctl -u "$SERVICE_NAME" -n 20 --no-pager || true
  exit 1
fi

if [ "$OPEN_FIREWALL" = "yes" ]; then
  echo "==> 放行端口"
  if command -v firewall-cmd >/dev/null 2>&1; then
    firewall-cmd --permanent --add-port="${HTTP_PORT}/tcp" >/dev/null
    if [ "$MMDVM_PORT" != "0" ]; then
      firewall-cmd --permanent --add-port="${MMDVM_PORT}/tcp" >/dev/null
    fi
    firewall-cmd --reload >/dev/null
    echo "    已通过 firewalld 放行"
  elif command -v ufw >/dev/null 2>&1; then
    ufw allow "${HTTP_PORT}/tcp" >/dev/null
    if [ "$MMDVM_PORT" != "0" ]; then
      ufw allow "${MMDVM_PORT}/tcp" >/dev/null
    fi
    echo "    已通过 ufw 放行"
  else
    echo "    未检测到 firewalld/ufw，请手动放行 ${HTTP_PORT}/tcp 与 ${MMDVM_PORT}/tcp"
  fi
fi

echo
echo "安装完成"
echo "  服务名   : $SERVICE_NAME"
echo "  安装目录 : $INSTALL_DIR"
echo "  数据文件 : $INSTALL_DIR/relay_data.db"
echo "  HTTP     : http://0.0.0.0:${HTTP_PORT}  (健康检查 /health)"
echo "  MMDVM    : tcp://0.0.0.0:${MMDVM_PORT}  (更新软件联系人同步)"
echo
echo "常用命令:"
echo "  systemctl status $SERVICE_NAME"
echo "  journalctl -u $SERVICE_NAME -f"
echo "  systemctl restart $SERVICE_NAME"
echo
echo "注意: 若 Windows 那边还在跑 relay_server.exe（含开机启动项），请先停掉，"
echo "      否则同一个中继端口会同时被两台机器占用。"
