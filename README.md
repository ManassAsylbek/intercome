# Intercom Management System

Локальная система управления IP-домофоном на базе устройств **Leelen**. Объединяет Asterisk PBX, FastAPI бэкенд и React фронтенд в одном Docker-стеке. Позволяет управлять домофонными устройствами через браузер: смотреть кто звонит, открывать дверь, просматривать видео с камеры.

---

## Что умеет

- 📞 **SIP маршрутизация** — Asterisk соединяет дверную панель и монитор квартиры
- 🎥 **RTSP видео** — просмотр видеопотока с камеры двери в браузере
- 🔓 **Открытие двери** — HTTP-команда на разблокировку замка
- 📋 **Управление устройствами** — добавление, редактирование, проверка доступности
- 🔐 **Авторизация** — JWT-аутентификация, защищённый веб-интерфейс
- 📊 **Дашборд** — статус устройств, активность, системная информация

---

## Архитектура

```
[Дверная панель Leelen]  ←── SIP ──→  [Asterisk PBX]  ←── SIP ──→  [Монитор Leelen]
     192.168.50.31                    network_mode:host               192.168.50.100
     SIP: 1002                         порт 5060/UDP                  SIP: 1001
     RTSP: :554                              │
                                             │ HTTP / shared volume
                                    [Backend FastAPI :8000]
                                    Auth │ Devices │ Routing
                                    Unlock │ Polling │ RTSP
                                             │
                                    [Frontend React :80]
                                             │
                                    [Браузер пользователя]
```

> **Важно:** `network_mode: host` работает только на **Linux/Ubuntu**. На macOS Docker Desktop UDP NAT ломает SIP Contact заголовки.

---

## Стек технологий

| Компонент   | Технология                               |
| ----------- | ---------------------------------------- |
| SIP PBX     | Asterisk 22 (`andrius/asterisk:latest`)  |
| Backend     | Python 3.12, FastAPI, SQLAlchemy, SQLite |
| Frontend    | React 18, TypeScript, Vite, Tailwind CSS |
| Контейнеры  | Docker, Docker Compose                   |
| Авторизация | JWT (python-jose), bcrypt                |

---

## Структура проекта

```
intercome-v2/
├── docker-compose.yml          # Оркестрация: asterisk + backend + frontend
├── .env.example                # Шаблон настроек окружения
├── docker/
│   └── asterisk/
│       ├── pjsip.conf          # SIP аккаунты и транспорт
│       ├── extensions.conf     # Диалплан (маршрутизация звонков)
│       ├── rtp.conf            # RTP порты (7000–7100)
│       ├── manager.conf        # AMI интерфейс
│       └── asterisk.conf       # Базовые настройки Asterisk
├── backend/
│   ├── app/
│   │   ├── api/routes/         # REST эндпоинты
│   │   │   ├── auth.py         # POST /api/auth/login, GET /api/auth/me
│   │   │   ├── devices.py      # CRUD + test-connection + test-unlock
│   │   │   ├── routing_rules.py
│   │   │   └── dashboard.py    # /api/health, /api/dashboard/summary
│   │   ├── services/
│   │   │   ├── sip_service.py          # Управление pjsip.conf
│   │   │   ├── unlock_service.py       # HTTP GET/POST разблокировка
│   │   │   ├── rtsp_service.py         # Проверка RTSP потока
│   │   │   ├── connectivity_service.py # Ping / TCP проверка
│   │   │   └── polling_service.py      # Фоновый опрос устройств
│   │   ├── models/             # SQLAlchemy модели (User, Device, RoutingRule)
│   │   ├── schemas/            # Pydantic схемы запросов/ответов
│   │   └── core/               # Конфиг, логирование, JWT/bcrypt
│   └── alembic/                # Миграции БД
└── frontend/
    └── src/
        ├── pages/              # Dashboard, Devices, Login, RoutingRules, Settings
        ├── components/         # UI: Badge, Button, Modal, Toast, FormFields
        ├── hooks/              # useAuth, useDevices, useDashboard, useRoutingRules
        └── api/                # HTTP клиент (axios)
```

---

## Быстрый старт (Ubuntu/Linux)

### 1. Клонировать репозиторий

```bash
git clone git@github.com:ManassAsylbek/intercome.git
cd intercome
```

### 2. Настроить окружение

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

### 3. Установить Docker (если не установлен)

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

### 4. Запустить

```bash
docker compose up -d
```

### 5. Проверить

```bash
# Статус контейнеров
docker compose ps

# SIP регистрации устройств (должны показать реальные IP устройств)
docker exec intercom-asterisk asterisk -rx "pjsip show contacts"
```

### 6. Открыть веб-интерфейс

```
http://192.168.50.132
```

Логин: `admin` / пароль из `.env`

---

## Открыть порты (UFW)

```bash
sudo ufw allow 80/tcp       # Веб-интерфейс
sudo ufw allow 8000/tcp     # Backend API
sudo ufw allow 5060/udp     # SIP
sudo ufw allow 7000:7100/udp # RTP (аудио/видео)
sudo ufw reload
```

---

## Конфигурация устройств Leelen

| Устройство       | IP               | SIP аккаунт | Пароль           |
| ---------------- | ---------------- | ----------- | ---------------- |
| Дверная панель   | `192.168.50.31`  | `1002`      | `StrongPass1002` |
| Монитор квартиры | `192.168.50.100` | `1001`      | `StrongPass1001` |

На каждом устройстве в SIP-настройках указать:

- **SIP Server**: `192.168.50.132`
- **Port**: `5060`

---

## Как работает звонок

1. Человек нажимает кнопку на **дверной панели** (SIP `1002`)
2. Панель делает SIP INVITE → **Asterisk** (`192.168.50.132:5060`)
3. Asterisk видит caller ID `1002` → звонит на **монитор** (`1001`)
4. Монитор принимает → двусторонняя аудио/видео связь
5. Пользователь нажимает `*` → DTMF проходит через bridge → дверь открывается

---

## Отладка

```bash
# Логи всех контейнеров
docker compose logs -f

# Только Asterisk
docker logs intercom-asterisk

# SIP логи в реальном времени
docker exec intercom-asterisk asterisk -rx "pjsip set logger on"
docker logs -f intercom-asterisk

# Статус SIP регистраций
docker exec intercom-asterisk asterisk -rx "pjsip show endpoints"

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
