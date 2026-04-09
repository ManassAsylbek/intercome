# Intercom Management System

Локальная система управления IP-домофоном на базе устройств **Leelen**. Объединяет Asterisk PBX, FastAPI бэкенд, React фронтенд и go2rtc в одном Docker-стеке. Позволяет принимать звонок с двери прямо в браузере: видеть кто звонит, разговаривать через WebRTC, открывать дверь.

---

## Что умеет

- 📞 **SIP в браузере** — принять/сбросить звонок с дверной панели прямо в браузере (JsSIP + WebRTC over WSS)
- 🎥 **Live видео** — WebRTC видеопоток с камеры двери через go2rtc (без плагинов)
- 🔔 **Одновременный звонок** — звонок с двери идёт сразу на браузер и монитор, кто первый ответил — тот говорит
- 🔓 **Открытие двери** — кнопка в браузере отправляет HTTP-команду на разблокировку замка
- 📋 **Управление устройствами** — добавление, редактирование, проверка доступности
- 🔐 **HTTPS + JWT** — самоподписанный SSL, JWT-аутентификация
- 📊 **Дашборд** — статус устройств, активные звонки, системная информация

---

## Архитектура

```
[Дверная панель Leelen]  ←── SIP/UDP ──→  [Asterisk PBX]  ←── SIP/UDP ──→  [Монитор Leelen]
     192.168.50.31                         network_mode:host                  192.168.50.100
     SIP: 1002                              порт 5060/UDP                     SIP: 1001
     RTSP: :554                                   │
                                    ┌─────────────┴──────────────┐
                                    │       SIP/WS :8088         │
                                    └─────────────┬──────────────┘
                                                  │ WSS (через nginx /sip)
                                         [Браузер — JsSIP 1099]
                                                  │
                              ┌───────────────────┼───────────────────┐
                              │                   │                   │
                    [Nginx :443 HTTPS]   [Backend FastAPI]    [go2rtc :1984]
                     SSL termination      :8000 (внутри)      WebRTC видео
                     /sip → WS proxy      Auth/Devices         RTSP → WebRTC
                     /go2rtc/ proxy       Unlock/Polling
                     /api/ proxy          SSE events
```

> **Важно:** `network_mode: host` (Asterisk и go2rtc) работает только на **Linux**. На macOS Docker Desktop NAT ломает SIP и RTP.

---

## Стек технологий

| Компонент    | Технология                                      |
| ------------ | ----------------------------------------------- |
| SIP PBX      | Asterisk (`andrius/asterisk:latest`)            |
| Видео        | go2rtc (`alexxit/go2rtc:latest`) — RTSP→WebRTC  |
| STUN         | coturn (`coturn/coturn:latest`) — LAN ICE       |
| Backend      | Python 3.12, FastAPI, SQLAlchemy, SQLite        |
| Frontend     | React 18, TypeScript, Vite, Tailwind CSS, JsSIP |
| Реверс прокси| Nginx (HTTPS, WSS proxy)                        |
| Авторизация  | JWT (python-jose), bcrypt                       |
| Контейнеры   | Docker, Docker Compose                          |

---

## Структура проекта

```
intercome/
├── docker-compose.yml          # Оркестрация: asterisk + backend + frontend + go2rtc + coturn
├── .env.example                # Шаблон настроек окружения
├── docker/
│   ├── asterisk/
│   │   ├── pjsip.conf          # SIP аккаунты (1001 монитор, 1002 дверь, 1099 браузер)
│   │   ├── extensions.conf     # Диалплан: одновременный звонок на браузер+монитор
│   │   ├── rtp.conf            # RTP порты (10000–20000), icesupport=yes
│   │   ├── http.conf           # WebSocket транспорт :8088 для браузера
│   │   ├── manager.conf        # AMI интерфейс
│   │   └── asterisk.conf       # Базовые настройки
│   ├── go2rtc/
│   │   └── go2rtc.yaml         # RTSP потоки (stream: door → rtsp://192.168.50.31)
│   └── nginx/
│       ├── server.crt          # Самоподписанный SSL сертификат
│       └── server.key          # Приватный ключ
├── backend/
│   └── app/
│       ├── api/routes/         # auth, devices, routing_rules, dashboard, calls
│       ├── services/           # sip, unlock, rtsp, connectivity, polling, call_store
│       ├── models/             # SQLAlchemy: User, Device, RoutingRule
│       ├── schemas/            # Pydantic схемы
│       └── core/               # config, logging, security (JWT/bcrypt)
└── frontend/
    ├── nginx.conf              # HTTPS, /sip WSS proxy, /go2rtc/ proxy, /api/ proxy
    └── src/
        ├── pages/              # Dashboard, Devices, DeviceDetail, Login, Routing, Settings
        ├── components/
        │   ├── ui/             # CallBanner, WebRTCPlayer, Badge, Button, Modal, Toast
        │   └── layout/         # AppLayout (SIP клиент), RequireAuth
        └── hooks/              # useAuth, useSIPClient, useCallEvents, useDevices, ...
```

---

## Быстрый старт (Ubuntu/Linux)

### 1. Клонировать репозиторий

```bash
git clone git@github.com:ManassAsylbek/intercome.git
cd intercome
```

### 2. Сгенерировать SSL сертификат

Браузерный SIP (WebRTC) требует HTTPS. Генерируем самоподписанный сертификат:

```bash
mkdir -p docker/nginx
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout docker/nginx/server.key \
  -out docker/nginx/server.crt \
  -subj "/CN=192.168.50.132"
```

Замени `192.168.50.132` на IP своего сервера.

### 3. Настроить окружение

```bash
cp .env.example .env
nano .env
```

Обязательно изменить:

```dotenv
SERVER_IP=192.168.50.132          # IP вашего Ubuntu-сервера
APP_SECRET_KEY=замените-на-случайную-строку-32-символа
ADMIN_PASSWORD=ваш-пароль
```

### 4. Установить Docker (если не установлен)

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

### 5. Запустить

```bash
docker compose up -d
```

### 6. Проверить статус

```bash
docker compose ps

# SIP регистрации — должны быть 1001 (монитор) и 1002 (дверь) со статусом Avail
sudo docker exec intercom-asterisk asterisk -rx "pjsip show contacts"
```

### 7. Открыть веб-интерфейс

```
https://192.168.50.132
```

Браузер покажет предупреждение о самоподписанном сертификате — нажми «Продолжить».

Логин: `admin` / пароль из `.env`

---

## Открыть порты (UFW)

```bash
sudo ufw allow 80/tcp             # HTTP → редирект на HTTPS
sudo ufw allow 443/tcp            # HTTPS веб-интерфейс
sudo ufw allow 5060/udp           # SIP (дверь и монитор)
sudo ufw allow 8088/tcp           # Asterisk WebSocket (SIP из браузера)
sudo ufw allow 3478/udp           # STUN (coturn — ICE для WebRTC)
sudo ufw allow 10000:20000/udp    # RTP аудио/видео
sudo ufw reload
```

---

## Конфигурация устройств Leelen

| Устройство       | IP               | SIP аккаунт | Пароль           |
| ---------------- | ---------------- | ----------- | ---------------- |
| Дверная панель   | `192.168.50.31`  | `1002`      | `StrongPass1002` |
| Монитор квартиры | `192.168.50.100` | `1001`      | `StrongPass1001` |
| Браузер          | —                | `1099`      | `BrowserSip1099` |

На устройствах Leelen в SIP-настройках указать:

- **SIP Server**: `192.168.50.132`
- **Port**: `5060`
- **Transport**: UDP

---

## Как работает звонок

1. Человек нажимает кнопку на **дверной панели** (SIP `1002`)
2. Панель делает SIP INVITE → **Asterisk** (`192.168.50.132:5060`)
3. Asterisk видит caller ID `1002` → одновременно звонит на **монитор** (`1001`) и **браузер** (`1099`)
4. Кто первый ответил — говорит, остальным Asterisk шлёт CANCEL
5. В браузере появляется баннер с **live видео** с камеры двери (WebRTC через go2rtc)
6. Пользователь нажимает **Open Door** → HTTP-команда на разблокировку замка

---

## Отладка

```bash
# Логи всех контейнеров
docker compose logs -f

# Только Asterisk (SIP события)
sudo docker logs intercom-asterisk -f

# Включить verbose SIP лог
sudo docker exec intercom-asterisk asterisk -rx "pjsip set logger on"

# Статус SIP регистраций
sudo docker exec intercom-asterisk asterisk -rx "pjsip show contacts"
sudo docker exec intercom-asterisk asterisk -rx "pjsip show endpoints"

# Перезагрузить dialplan без перезапуска
sudo docker exec intercom-asterisk asterisk -rx "dialplan reload"
sudo docker exec intercom-asterisk asterisk -rx "module reload res_pjsip.so"
```

### Браузер не слышит звук / звонок сразу сбрасывается

Самая частая причина — браузерный HTTPS генерирует mDNS ICE-кандидаты (`*.local`), которые Asterisk не может разрешить. Убедись что:

1. Контейнер `coturn` запущен (`docker compose ps coturn` — статус Up)
2. Порт `3478/udp` открыт в UFW
3. Браузер открыт именно по **HTTPS** (не HTTP)

### Эхо во время разговора

Эхо возникает когда микрофон улавливает звук из динамика. Решения:
- Используй **наушники** на стороне браузера — убирает эхо полностью
- На дверной панели в веб-интерфейсе найди **Echo Cancellation (AEC)** и включи
- Убавь громкость динамика на дверной панели до 60–70%

# Перезагрузить конфиг Asterisk без рестарта
docker exec intercom-asterisk asterisk -rx "core reload"
```

---

## Переменные окружения

| Переменная         | Описание                         | По умолчанию          |
| ------------------ | -------------------------------- | --------------------- |
| `SERVER_IP`        | IP сервера (для CORS и конфигов) | `192.168.50.132`      |
| `FRONTEND_PORT`    | Порт веб-интерфейса              | `80`                  |
| `APP_SECRET_KEY`   | Секрет JWT (минимум 32 символа)  | ⚠️ сменить!           |
| `ADMIN_USERNAME`   | Логин администратора             | `admin`               |
| `ADMIN_PASSWORD`   | Пароль администратора            | ⚠️ сменить!           |
| `APP_CORS_ORIGINS` | Разрешённые origins для CORS     | localhost + SERVER_IP |
| `ASTERISK_MODE`    | `local` или `ssh`                | `local`               |
