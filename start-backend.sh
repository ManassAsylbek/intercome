#!/bin/zsh
# Запуск backend сервера
# Использование: ./start-backend.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/venv/bin/uvicorn"
BACKEND="$SCRIPT_DIR/backend"

# Определяем IP текущей машины (Wi-Fi или LAN)
SERVER_IP=$(ipconfig getifaddr en7 2>/dev/null || ipconfig getifaddr en0 2>/dev/null || echo "127.0.0.1")

# Освобождаем порт если занят
if lsof -ti :8000 &>/dev/null; then
  echo "⚠️  Порт 8000 занят — останавливаем старый процесс..."
  lsof -ti :8000 | xargs kill -9 2>/dev/null
  sleep 1
fi

echo "▶  Запускаем backend..."
echo "   URL: http://0.0.0.0:8000"
echo "   API: http://$SERVER_IP:8000/api/health"
echo ""

cd "$BACKEND" && PYTHONPATH="$BACKEND" "$VENV" app.main:app \
  --reload \
  --host 0.0.0.0 \
  --port 8000
