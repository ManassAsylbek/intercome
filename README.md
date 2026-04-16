# Intercom Management System

Система управления IP-домофоном. Объединяет Asterisk PBX, FastAPI бэкенд, React фронтенд и go2rtc в одном Docker-стеке. Позволяет принимать звонки с дверных панелей, калиток и шлагбаумов прямо в браузере: видеть кто звонит, разговаривать через WebRTC, открывать дверь. Поддерживает многоквартирные дома — несколько мониторов в квартире, несколько источников вызова, облачная переадресация на мобильное приложение.

---

## Что умеет

- 📞 **SIP в браузере** — принять/сбросить звонок прямо в браузере (JsSIP + WebRTC over WSS)
- 🎥 **Live видео** — WebRTC видеопоток с камеры двери через go2rtc (без плагинов)
- 🔔 **Одновременный звонок** — звонок идёт сразу на браузер, все мониторы квартиры и в облако
- 🏢 **Квартиры** — каждая квартира имеет код вызова и список мониторов; диалплан генерируется автоматически
- 📡 **Облачная переадресация** — при включении звонок через SIP-транк идёт в облако к мобильным пользователям
- 🚪 **Несколько источников** — любое количество дверей/калиток/шлагбаумов на одну квартиру
- 🔓 **Открытие двери** — кнопка в браузере отправляет HTTP-команду на разблокировку замка
- 📋 **Управление устройствами** — добавление/редактирование, SIP в Asterisk через кнопку
- 🔐 **HTTPS + JWT** — самоподписанный SSL, JWT-аутентификация
- 📊 **Дашборд** — статус устройств, активные звонки, лог активности

---

## Архитектура

```
[Дверь / Калитка / Шлагбаум]
  SIP 1002 / 1004 / 1005                    Набирает call_code квартиры
        │                                   (напр. 1042)
        ▼
[Asterisk PBX]  ─── network_mode: host ───  порт 5060/UDP
        │
        │  Dial одновременно:
        ├─── PJSIP/1099  ────────────────── Браузер (WebRTC/WSS через nginx)
        ├─── PJSIP/1001  ────────────────── Монитор 1 (Гостиная)
        ├─── PJSIP/1003  ────────────────── Монитор 2 (Спальня)
        └─── PJSIP/1042@cloud-trunk ──────── Облако → мобильное приложение (если включено)
                                             (опционально — CLOUD_SIP_TRUNK_ENDPOINT)
        │
[Nginx :443 HTTPS]
  /sip      → ws://asterisk:8088/ws   (WebSocket для JsSIP)
  /api/     → http://backend:8000      (REST API)
  /go2rtc/  → http://go2rtc:1984       (WebRTC видео)

[FastAPI Backend :8000]
  - CRUD: devices, apartments, routing_rules
  - SIP apply: пишет pjsip.conf + extensions.conf, docker exec перезагружает Asterisk
  - Webhooks: call_start / call_end от Asterisk
  - SSE: события звонков → браузер

[go2rtc :1984]       — RTSP → WebRTC конвертер
[coturn  :3478]      — STUN-сервер для WebRTC ICE
```

> **Важно:** `network_mode: host` (Asterisk) работает только на **Linux**. На macOS SIP/RTP не работает через Docker NAT.

---

## Стек технологий

| Компонент     | Технология                                        |
|---------------|---------------------------------------------------|
| SIP PBX       | Asterisk (`andrius/asterisk:latest`)              |
| Видео         | go2rtc (`alexxit/go2rtc:latest`) — RTSP→WebRTC    |
| STUN          | coturn (`coturn/coturn:latest`) — ICE для WebRTC  |
| Backend       | Python 3.11, FastAPI, SQLAlchemy async, SQLite    |
| Frontend      | React 18, TypeScript, Vite, Tailwind CSS, JsSIP   |
| Реверс прокси | Nginx (HTTPS, WSS proxy, SPA)                     |
| Авторизация   | JWT (python-jose), bcrypt                         |
| Контейнеры    | Docker, Docker Compose                            |

---

## Структура проекта

```
intercome/
├── docker-compose.yml
├── .env                            # Настройки (из .env.example)
├── docker/
│   ├── asterisk/
│   │   ├── pjsip.conf              # SIP аккаунты (управляемые блоки + ручные)
│   │   ├── extensions.conf         # Диалплан (генерируется автоматически из квартир)
│   │   ├── rtp.conf                # RTP порты 10000–20000
│   │   ├── http.conf               # WebSocket :8088 для браузера
│   │   ├── manager.conf            # AMI
│   │   └── asterisk.conf
│   ├── go2rtc/
│   │   └── go2rtc.yaml             # RTSP потоки
│   ├── nginx/
│   │   ├── server.crt              # SSL сертификат
│   │   └── server.key
│   └── bin/
│       └── docker                  # docker CLI (x86_64) для reload из backend
├── backend/
│   └── app/
│       ├── api/routes/             # auth, devices, apartments, routing_rules, dashboard
│       ├── services/
│       │   ├── sip_service.py      # pjsip.conf + extensions.conf + dialplan reload
│       │   ├── unlock_service.py
│       │   ├── connectivity_service.py
│       │   └── polling_service.py
│       ├── models/                 # User, Device, Apartment, ApartmentMonitor, RoutingRule
│       ├── schemas/                # Pydantic схемы
│       └── core/                   # config, logging, security
└── frontend/
    └── src/
        ├── pages/
        │   ├── ApartmentsPage.tsx  # Квартиры + мониторы + cloud relay
        │   ├── DevicesPage.tsx
        │   ├── RoutingRulesPage.tsx
        │   ├── DashboardPage.tsx
        │   └── SettingsPage.tsx
        ├── components/
        │   ├── ui/                 # CallBanner, WebRTCPlayer, Button, Modal, Toast…
        │   └── layout/             # AppLayout (SIP клиент), RequireAuth
        └── hooks/                  # useAuth, useSIPClient, useCallEvents, useApartments…
```

---

## Быстрый старт (Ubuntu/Linux)

### 1. Клонировать репозиторий

```bash
git clone git@github.com:ManassAsylbek/intercome.git
cd intercome
```

### 2. Сгенерировать SSL сертификат

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

Обязательные параметры:

```dotenv
SERVER_IP=192.168.50.132          # IP Ubuntu-сервера
APP_SECRET_KEY=замените-на-случайную-строку-32-символа
ADMIN_PASSWORD=ваш-пароль
ASTERISK_MODE=local               # local | ami | ssh
```

### 4. Запустить

```bash
sudo docker compose up -d --build
```

### 5. Проверить статус

```bash
sudo docker compose ps

# SIP регистрации
sudo docker exec intercom-asterisk asterisk -rx "pjsip show contacts"
```

### 6. Открыть веб-интерфейс

```
https://192.168.50.132
```

Браузер покажет предупреждение о самоподписанном сертификате — нажми «Продолжить».

Логин: `admin` / пароль из `.env`

---

## Открыть порты (UFW)

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp            # HTTPS веб-интерфейс
sudo ufw allow 5060/udp           # SIP (устройства)
sudo ufw allow 8088/tcp           # Asterisk WebSocket (браузерный SIP)
sudo ufw allow 3478/udp           # STUN (coturn)
sudo ufw allow 10000:20000/udp    # RTP аудио/видео
sudo ufw reload
```

---

## Добавление квартиры

1. **Квартиры** → Добавить квартиру
2. Указать **Номер** (отображаемое, напр. `42`) и **Код вызова** (SIP-номер, напр. `1042`)
3. Добавить **Мониторы** — SIP-аккаунты устройств внутри квартиры (`1001`, `1003`,…)
4. При необходимости включить **Облачную переадресацию** (требует настроенного SIP-транка в `.env`)
5. Сохранить → `extensions.conf` и dialplan обновятся автоматически

## Добавление устройства (дверь / калитка / шлагбаум)

1. **Устройства** → Добавить → тип "Панель домофона"
2. Включить **SIP**, указать аккаунт (напр. `1004`) и пароль
3. Выбрать **Квартиру** к которой будет привязано устройство
4. Сохранить → кнопка **Применить в Asterisk** создаёт блок в `pjsip.conf`
5. На самом устройстве прописать: сервер `192.168.50.132`, порт `5060`, аккаунт/пароль, **номер для набора** = код вызова квартиры

Несколько устройств могут звонить на одну квартиру — Asterisk принимает любой вызов на `call_code`.

---

## Как работает звонок

```
1. Нажата кнопка на дверной панели (SIP 1004)
2. Панель делает INVITE → Asterisk (195.168.50.132:5060) с номером 1042
3. Asterisk dial: PJSIP/1099 & PJSIP/1001 & PJSIP/1003 & PJSIP/1042@cloud-trunk
4. Кто первый ответил — говорит, остальным Asterisk шлёт CANCEL
5. В браузере появляется баннер с live видео (WebRTC через go2rtc)
6. Нажать "Открыть дверь" → HTTP POST на unlock URL устройства
```

---

## Облачная переадресация

Для переадресации звонков на мобильное приложение через облачный SIP-провайдер:

1. Настроить SIP-транк в `docker/asterisk/pjsip.conf` с именем, напр. `cloud-trunk`
2. В `.env` добавить:
   ```dotenv
   CLOUD_SIP_TRUNK_ENDPOINT=cloud-trunk
   ```
3. Для каждой квартиры включить **Облачная переадресация** и указать SIP-аккаунт на транке
4. `extensions.conf` пересгенерируется автоматически при следующем изменении квартиры (или через кнопку "Синхронизировать dialplan")

---

## Отладка

```bash
# Логи всех контейнеров
sudo docker compose logs -f

# Только Asterisk
sudo docker logs intercom-asterisk -f

# SIP лог
sudo docker exec intercom-asterisk asterisk -rx "pjsip set logger on"

# Статус SIP
sudo docker exec intercom-asterisk asterisk -rx "pjsip show contacts"
sudo docker exec intercom-asterisk asterisk -rx "pjsip show endpoints"

# Перезагрузить dialplan
sudo docker exec intercom-asterisk asterisk -rx "dialplan reload"
sudo docker exec intercom-asterisk asterisk -rx "module reload res_pjsip.so"

# Посмотреть текущий диалплан
sudo docker exec intercom-asterisk asterisk -rx "dialplan show intercom"
```

### Браузер не слышит звук / звонок сразу сбрасывается

Самая частая причина — mDNS ICE-кандидаты (`*.local`) в HTTPS браузере. Убедись:

1. Контейнер `coturn` запущен (`docker compose ps`)
2. Порт `3478/udp` открыт в UFW
3. Браузер открыт по **HTTPS** (не HTTP)

### Эхо во время разговора

- Используй **наушники** на стороне браузера
- На дверной панели включи **Echo Cancellation (AEC)**
- Убавь громкость динамика панели до 60–70%

---

## Переменные окружения

| Переменная                    | Описание                                          | По умолчанию     |
|-------------------------------|---------------------------------------------------|------------------|
| `SERVER_IP`                   | IP сервера                                        | `192.168.50.132` |
| `FRONTEND_PORT`               | Порт веб-интерфейса                               | `80`             |
| `APP_SECRET_KEY`              | Секрет JWT (минимум 32 символа)                   | ⚠️ сменить!      |
| `ADMIN_USERNAME`              | Логин администратора                              | `admin`          |
| `ADMIN_PASSWORD`              | Пароль администратора                             | ⚠️ сменить!      |
| `ASTERISK_MODE`               | `local` / `ami` / `ssh`                           | `local`          |
| `ASTERISK_RELOAD_CMD`         | Команда перезагрузки Asterisk                     | —                |
| `ASTERISK_AMI_HOST`           | AMI хост                                          | `asterisk-host`  |
| `ASTERISK_AMI_PORT`           | AMI порт                                          | `5038`           |
| `ASTERISK_AMI_USER`           | AMI пользователь                                  | `intercom`       |
| `ASTERISK_AMI_SECRET`         | AMI пароль                                        | —                |
| `CLOUD_SIP_TRUNK_ENDPOINT`    | Имя PJSIP endpoint для облачного транка           | —                |


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

| Компонент     | Технология                                      |
| ------------- | ----------------------------------------------- |
| SIP PBX       | Asterisk (`andrius/asterisk:latest`)            |
| Видео         | go2rtc (`alexxit/go2rtc:latest`) — RTSP→WebRTC  |
| STUN          | coturn (`coturn/coturn:latest`) — LAN ICE       |
| Backend       | Python 3.12, FastAPI, SQLAlchemy, SQLite        |
| Frontend      | React 18, TypeScript, Vite, Tailwind CSS, JsSIP |
| Реверс прокси | Nginx (HTTPS, WSS proxy)                        |
| Авторизация   | JWT (python-jose), bcrypt                       |
| Контейнеры    | Docker, Docker Compose                          |

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
```
