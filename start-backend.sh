#!/bin/zsh
# Запуск backend сервера
# Использование: ./start-backend.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv/bin/uvicorn"
BACKEND="$SCRIPT_DIR/backend"

echo "▶  Запускаем backend..."
echo "   URL: http://0.0.0.0:8000"
echo "   API: http://localhost:8000/api/health"
echo ""

cd "$BACKEND" && PYTHONPATH="$BACKEND" "$VENV" app.main:app \
  --reload \
  --host 0.0.0.0 \
  --port 8000
