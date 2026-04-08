#!/bin/zsh
# ╔══════════════════════════════════════════════════════════════╗
# ║   Intercom Management Server — единый скрипт запуска        ║
# ║   Работает на любом Mac/Linux с Python 3.11+ и Node 18+     ║
# ╚══════════════════════════════════════════════════════════════╝
# Использование: ./start.sh [--no-frontend] [--port-backend 8000] [--port-frontend 5173]

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ─── Параметры ────────────────────────────────────────────────
BACKEND_PORT=8000
FRONTEND_PORT=5173
START_FRONTEND=true

while [[ $# -gt 0 ]]; do
  case $1 in
    --no-frontend) START_FRONTEND=false ;;
    --port-backend) BACKEND_PORT=$2; shift ;;
    --port-frontend) FRONTEND_PORT=$2; shift ;;
  esac
  shift
done

# ─── Определяем IP ────────────────────────────────────────────
# Сначала пробуем LAN-адаптер (en7), потом Wi-Fi (en0), fallback localhost
SERVER_IP=$(ipconfig getifaddr en7 2>/dev/null \
  || ipconfig getifaddr en0 2>/dev/null \
  || hostname -I 2>/dev/null | awk '{print $1}' \
  || echo "127.0.0.1")

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║        Intercom Management Server                   ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Server IP:    $SERVER_IP"
echo "  Backend:      http://$SERVER_IP:$BACKEND_PORT"
echo "  Frontend:     http://$SERVER_IP:$FRONTEND_PORT"
echo "  Login:        admin / admin123"
echo ""

# ─── Виртуальное окружение ────────────────────────────────────
VENV="$SCRIPT_DIR/venv"
if [[ ! -d "$VENV" ]]; then
  echo "⚙  Создаём Python venv..."
  python3 -m venv "$VENV"
fi

echo "⚙  Устанавливаем Python зависимости..."
"$VENV/bin/pip" install -q -e "$SCRIPT_DIR/backend[dev]" \
  && echo "   ✓ Python deps OK"

# ─── Миграции БД ──────────────────────────────────────────────
echo "⚙  Применяем миграции БД..."
(cd "$SCRIPT_DIR/backend" && PYTHONPATH="$SCRIPT_DIR/backend" \
  "$VENV/bin/alembic" upgrade head 2>&1 | tail -3)
echo "   ✓ DB OK"

# ─── Останавливаем старые процессы ────────────────────────────
lsof -ti :"$BACKEND_PORT" | xargs kill -9 2>/dev/null || true
[[ "$START_FRONTEND" == "true" ]] && \
  lsof -ti :"$FRONTEND_PORT" | xargs kill -9 2>/dev/null || true
sleep 1

# ─── Backend ──────────────────────────────────────────────────
echo "▶  Запускаем backend на :$BACKEND_PORT ..."
(
  export PYTHONPATH="$SCRIPT_DIR/backend"
  export SERVER_IP="$SERVER_IP"
  cd "$SCRIPT_DIR/backend"
  "$VENV/bin/uvicorn" app.main:app \
    --host 0.0.0.0 \
    --port "$BACKEND_PORT" \
    >> /tmp/intercom-backend.log 2>&1
) &
BACKEND_PID=$!
echo "   PID $BACKEND_PID  (log: /tmp/intercom-backend.log)"

# Ждём пока бэкенд поднимется
echo -n "   Ожидаем backend"
for i in {1..15}; do
  sleep 1
  if curl -sf "http://localhost:$BACKEND_PORT/api/health" &>/dev/null; then
    echo " ✓"
    break
  fi
  echo -n "."
done

# ─── Frontend ─────────────────────────────────────────────────
if [[ "$START_FRONTEND" == "true" ]]; then
  FRONTEND_DIR="$SCRIPT_DIR/frontend"
  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    echo "⚙  Устанавливаем npm зависимости..."
    (cd "$FRONTEND_DIR" && npm install --silent)
    echo "   ✓ npm deps OK"
  fi

  echo "▶  Запускаем frontend на :$FRONTEND_PORT ..."
  (
    export VITE_API_URL="http://$SERVER_IP:$BACKEND_PORT/api"
    cd "$FRONTEND_DIR"
    npm run dev -- --host --port "$FRONTEND_PORT" \
      >> /tmp/intercom-frontend.log 2>&1
  ) &
  FRONTEND_PID=$!
  echo "   PID $FRONTEND_PID  (log: /tmp/intercom-frontend.log)"
fi

# ─── Готово ───────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  ✅ Всё запущено!"
echo ""
echo "  Откройте в браузере:"
echo "  → http://$SERVER_IP:$FRONTEND_PORT"
echo ""
echo "  Или на этой машине:"
echo "  → http://localhost:$FRONTEND_PORT"
echo ""
echo "  Swagger (API docs):"
echo "  → http://$SERVER_IP:$BACKEND_PORT/docs"
echo ""
echo "  Устройства должны использовать этот IP как Server Address:"
echo "  → $SERVER_IP"
echo ""
echo "  Остановить: Ctrl+C"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Ждём Ctrl+C и убиваем дочерние процессы
trap "echo ''; echo 'Stopping...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM
wait
