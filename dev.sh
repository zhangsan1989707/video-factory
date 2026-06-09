#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$PROJECT_DIR/.dev.pid"
LOG_FILE="$PROJECT_DIR/.dev.log"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"

_red()   { printf "\033[31m%s\033[0m\n" "$*"; }
_green() { printf "\033[32m%s\033[0m\n" "$*"; }
_yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }

_pid() {
  [[ -f "$PID_FILE" ]] && cat "$PID_FILE" || echo ""
}

_running() {
  local pid
  pid=$(_pid)
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

cmd_start() {
  if _running; then
    _yellow "已在运行 (PID $(_pid)), http://$HOST:$PORT"
    return 0
  fi
  mkdir -p "$PROJECT_DIR/output"
  cd "$PROJECT_DIR"
  nohup .venv/bin/python -m src.console --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 1
  if _running; then
    _green "已启动 (PID $(_pid)), http://$HOST:$PORT"
  else
    _red "启动失败，查看日志: $LOG_FILE"
    return 1
  fi
}

cmd_stop() {
  if ! _running; then
    _yellow "未在运行"
    rm -f "$PID_FILE"
    return 0
  fi
  local pid
  pid=$(_pid)
  kill "$pid" 2>/dev/null || true
  for i in $(seq 1 10); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.5
  done
  if kill -0 "$pid" 2>/dev/null; then
    _yellow "优雅停止超时，强制终止"
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  _green "已停止"
}

cmd_restart() {
  cmd_stop
  cmd_start
}

cmd_status() {
  if _running; then
    _green "运行中 (PID $(_pid)), http://$HOST:$PORT"
  else
    _yellow "未运行"
  fi
}

cmd_log() {
  if [[ -f "$LOG_FILE" ]]; then
    tail -f "$LOG_FILE"
  else
    _yellow "日志文件不存在"
  fi
}

cmd_help() {
  cat <<EOF
用法: ./dev.sh <命令>

命令:
  start     启动控制台服务
  stop      停止控制台服务
  restart   重启控制台服务
  status    查看运行状态
  log       实时查看日志
  help      显示帮助

环境变量:
  HOST      监听地址 (默认 127.0.0.1)
  PORT      监听端口 (默认 8765)
EOF
}

case "${1:-help}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_restart ;;
  status)  cmd_status ;;
  log)     cmd_log ;;
  *)       cmd_help ;;
esac
