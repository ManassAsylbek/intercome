#!/bin/zsh
# Настройка сети: Wi-Fi для интернета + LAN для устройств Leelen
# Wi-Fi (en0): 192.168.31.43 (DHCP) — интернет
# LAN  (en7): 192.168.31.132 (static, без шлюза) — Leelen устройства

LAN_IFACE="en7"
LAN_IP="192.168.31.132"
LAN_MASK="255.255.255.0"
LAN_NET="192.168.31.0/24"
WIFI_IFACE="en0"

echo "🔧 Настройка сети..."

# 1. Wi-Fi — DHCP (интернет)
echo "   Wi-Fi → DHCP..."
sudo networksetup -setdhcp "Wi-Fi"
sleep 2

# Получаем шлюз Wi-Fi
WIFI_GW=$(ipconfig getoption "$WIFI_IFACE" router 2>/dev/null)
echo "   Wi-Fi шлюз: $WIFI_GW"

# 2. LAN — статический IP БЕЗ шлюза (чтобы не добавлял default route)
echo "   LAN ($LAN_IFACE) → $LAN_IP (без шлюза)..."
sudo ifconfig "$LAN_IFACE" "$LAN_IP" "$LAN_MASK" 2>/dev/null
sleep 1

# 3. Удаляем все default-маршруты через LAN (macOS может добавить автоматически)
sudo route delete default -ifscope "$LAN_IFACE" 2>/dev/null
sudo route delete default -interface "$LAN_IFACE" 2>/dev/null

# Удаляем все записи default через en7 из таблицы
while netstat -rn | grep "^default" | grep -q "$LAN_IFACE"; do
  sudo route delete default 2>/dev/null
  sleep 0.3
done

# 4. Убеждаемся что default route через Wi-Fi
if [[ -n "$WIFI_GW" ]]; then
  # Если default route пропал — восстанавливаем через Wi-Fi
  if ! netstat -rn | grep "^default" | grep -q "$WIFI_IFACE"; then
    echo "   Восстанавливаем default route через Wi-Fi..."
    sudo route add default "$WIFI_GW" 2>/dev/null
  fi
  # Принудительно привязываем default к Wi-Fi
  sudo route change default "$WIFI_GW" -ifscope "$WIFI_IFACE" 2>/dev/null || true
fi

# 5. Убеждаемся что маршрут 192.168.50.x идёт через LAN
sudo route delete -net "$LAN_NET" 2>/dev/null
sudo route add -net "$LAN_NET" -interface "$LAN_IFACE" 2>/dev/null || \
  sudo route add -net "$LAN_NET" "$LAN_IP" 2>/dev/null

# 6. Отключаем ICMP Redirect
sudo sysctl -w net.inet.ip.redirect=0 2>/dev/null

# Итоговая таблица маршрутов
echo ""
echo "📋 Маршруты (default + 192.168.31):"
netstat -rn | grep -E "^default|192.168.31"

# 7. Проверка
echo ""
WIFI_IP=$(ipconfig getifaddr "$WIFI_IFACE" 2>/dev/null)
LAN_IP_ACTUAL=$(ifconfig "$LAN_IFACE" 2>/dev/null | awk '/inet /{print $2}')
INTERNET=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null)

echo "📡 Wi-Fi IP  : ${WIFI_IP:-НЕТ}"
echo "🔌 LAN IP    : ${LAN_IP_ACTUAL:-НЕТ (кабель не подключён?)}"
echo "🌐 Интернет  : ${INTERNET:-(нет подключения)}"

if ping -c 1 -t 2 192.168.31.100 &>/dev/null; then
  echo "📷 Панель    : 192.168.31.100 ✅"
else
  echo "📷 Панель    : 192.168.31.100 ❌"
fi

if ping -c 1 -t 2 192.168.31.31 &>/dev/null; then
  echo "🖥️  Монитор   : 192.168.31.31  ✅"
else
  echo "🖥️  Монитор   : 192.168.31.31  ❌"
fi

echo ""
echo "✅ Готово! Запускайте ./start-backend.sh"
