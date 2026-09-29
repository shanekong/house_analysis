#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
frontend_dir="$project_dir/frontend"
runtime_dir="$project_dir/.dev"
api_pid_file="$runtime_dir/backend.pid"
web_pid_file="$runtime_dir/frontend.pid"
api_port_file="$runtime_dir/backend.port"
web_port_file="$runtime_dir/frontend.port"
api_log_file="$runtime_dir/backend.log"
web_log_file="$runtime_dir/frontend.log"
api_port="${API_PORT:-8787}"
web_port_start="${PORT:-4173}"

die() {
  echo "[FAIL] $1" >&2
  exit 1
}

pid_is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] &&
    [[ "$(cat "$pid_file")" =~ ^[0-9]+$ ]] &&
    kill -0 "$(cat "$pid_file")" 2>/dev/null
}

url_is_ready() {
  curl -fsS --max-time 2 -o /dev/null "$1" 2>/dev/null
}

port_is_available() {
  python3 - "$1" <<'PY'
import socket
import sys

with socket.socket() as sock:
    sock.settimeout(0.2)
    raise SystemExit(1 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 0)
PY
}

find_available_port() {
  local candidate="$1"
  while ! port_is_available "$candidate"; do
    candidate=$((candidate + 1))
  done
  echo "$candidate"
}

read_port() {
  local port_file="$1" fallback="$2"
  if [[ -f "$port_file" ]]; then
    cat "$port_file"
  else
    echo "$fallback"
  fi
}

environment_ready() {
  command -v python3 >/dev/null 2>&1 &&
    command -v curl >/dev/null 2>&1 &&
    [[ -x "$project_dir/backend/.venv/bin/python" ]] &&
    [[ -x "$project_dir/backend/.venv/bin/uvicorn" ]] &&
    [[ -f "$frontend_dir/index.html" ]] &&
    [[ -f "$frontend_dir/app.js" ]] &&
    [[ -f "$frontend_dir/styles.css" ]]
}

check_environment() {
  environment_ready || die "运行环境不完整；请确认 backend/.venv 和 frontend 静态资源存在"
  echo "前端资源与后端虚拟环境完整"
  (cd "$project_dir/backend" && .venv/bin/python -m unittest discover -s tests -q)
  echo "环境检查通过"
}

descendant_pids() {
  local parent_pid="$1" child_pid
  command -v pgrep >/dev/null 2>&1 || return 0
  for child_pid in $(pgrep -P "$parent_pid" 2>/dev/null || true); do
    descendant_pids "$child_pid"
    echo "$child_pid"
  done
}

stop_process() {
  local label="$1" pid_file="$2" pid descendants attempt
  if ! pid_is_running "$pid_file"; then
    rm -f "$pid_file"
    echo "${label}：已停止"
    return 0
  fi

  pid="$(cat "$pid_file")"
  descendants="$(descendant_pids "$pid")"
  kill "$pid" $descendants 2>/dev/null || true
  for attempt in 1 2 3 4 5; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" $descendants 2>/dev/null || true
  fi
  rm -f "$pid_file"
  echo "${label}：已停止"
}

stop_services() {
  stop_process "Web" "$web_pid_file"
  stop_process "API" "$api_pid_file"
  rm -f "$web_port_file" "$api_port_file"
  rm -f "$frontend_dir/runtime-config.js"
}

wait_for_url() {
  local label="$1" url="$2" pid_file="$3" attempt
  for attempt in $(seq 1 30); do
    if ! pid_is_running "$pid_file"; then
      echo "$label 启动进程已退出。" >&2
      return 1
    fi
    if url_is_ready "$url"; then
      return 0
    fi
    sleep 1
  done
  echo "$label 在 30 秒内未就绪。" >&2
  return 1
}

services_are_ready() {
  local current_api_port current_web_port
  current_api_port="$(read_port "$api_port_file" "$api_port")"
  current_web_port="$(read_port "$web_port_file" "$web_port_start")"
  pid_is_running "$api_pid_file" &&
    pid_is_running "$web_pid_file" &&
    url_is_ready "http://127.0.0.1:${current_api_port}/api/health" &&
    url_is_ready "http://127.0.0.1:${current_web_port}/"
}

start_services() {
  local web_port api_url web_url
  environment_ready || die "运行环境不完整；请先准备 backend/.venv"
  mkdir -p "$runtime_dir"

  if services_are_ready; then
    echo "服务已经启动；使用 ./dev.sh status 查看状态。"
    return 0
  fi

  if pid_is_running "$api_pid_file" || pid_is_running "$web_pid_file"; then
    echo "检测到不完整或未就绪的旧进程，先清理后重启。"
    stop_services
  else
    rm -f "$api_pid_file" "$web_pid_file" "$api_port_file" "$web_port_file"
  fi

  port_is_available "$api_port" || die "API 端口 ${api_port} 已被其他进程占用"
  web_port="$(find_available_port "$web_port_start")"
  api_url="http://127.0.0.1:${api_port}"
  web_url="http://localhost:${web_port}"

  : > "$api_log_file"
  : > "$web_log_file"
  printf 'window.HOUSE_API_BASE = "http://127.0.0.1:%s";\n' "$api_port" > "$frontend_dir/runtime-config.js"

  (
    cd "$project_dir/backend"
    HOUSE_WEB_ORIGIN="$web_url" nohup .venv/bin/uvicorn house_analysis.server:app \
      --host 127.0.0.1 --port "$api_port" > "$api_log_file" 2>&1 &
    echo "$!" > "$api_pid_file"
  )
  echo "$api_port" > "$api_port_file"

  (
    cd "$frontend_dir"
    nohup python3 -m http.server "$web_port" --bind 127.0.0.1 > "$web_log_file" 2>&1 &
    echo "$!" > "$web_pid_file"
  )
  echo "$web_port" > "$web_port_file"

  echo "正在等待服务就绪..."
  if ! wait_for_url "API" "$api_url/api/health" "$api_pid_file" ||
     ! wait_for_url "Web" "http://127.0.0.1:${web_port}/" "$web_pid_file"; then
    echo "启动失败。最近日志：" >&2
    tail -n 30 "$api_log_file" "$web_log_file" >&2 || true
    stop_services
    return 1
  fi

  echo "服务启动完成："
  echo "  Web  $web_url"
  echo "  API  $api_url"
  echo "  日志 ./dev.sh logs"
}

service_status() {
  local label="$1" pid_file="$2" url="$3"
  if ! pid_is_running "$pid_file"; then
    echo "${label}：未运行"
    return 1
  fi
  if url_is_ready "$url"; then
    echo "${label}：运行中（PID $(cat "$pid_file")，${url}）"
    return 0
  fi
  echo "${label}：进程存在但健康检查失败（PID $(cat "$pid_file")，${url}）"
  return 1
}

show_status() {
  local result=0 current_api_port current_web_port
  current_api_port="$(read_port "$api_port_file" "$api_port")"
  current_web_port="$(read_port "$web_port_file" "$web_port_start")"
  service_status "API" "$api_pid_file" "http://127.0.0.1:${current_api_port}/api/health" || result=1
  service_status "Web" "$web_pid_file" "http://127.0.0.1:${current_web_port}/" || result=1
  return "$result"
}

show_logs() {
  mkdir -p "$runtime_dir"
  touch "$api_log_file" "$web_log_file"
  tail -n 50 -f "$api_log_file" "$web_log_file"
}

show_usage() {
  echo "用法：./dev.sh [start|stop|restart|status|check|logs]"
}

command_name="${1:-start}"
case "$command_name" in
  start) start_services ;;
  stop) stop_services ;;
  restart) stop_services; start_services ;;
  status) show_status ;;
  check) check_environment ;;
  logs) show_logs ;;
  -h|--help|help) show_usage ;;
  *) show_usage >&2; exit 2 ;;
esac
