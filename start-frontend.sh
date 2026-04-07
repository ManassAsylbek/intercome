#!/bin/zsh
# Запуск frontend сервера
# Использование: ./start-frontend.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "▶  Запускаем frontend..."
echo "   URL: http://localhost:5173"
echo "   Сеть: http://$(ipconfig getifaddr en0):5173"
echo ""

cd "$SCRIPT_DIR/frontend" && npm run dev -- --host
