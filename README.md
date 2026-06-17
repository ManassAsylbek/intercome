# Intercom Management System — Bridge

Локальный bridge-сервер IP-домофонной системы. Связывает физические устройства подъезда (панели вызова, hardware-мониторы, замки) с облачным CRM и мобильным приложением. Базируется на Docker Compose: Asterisk + FastAPI + React + go2rtc + Postgres + coturn.

---

## 1. Сетевая топология

```
                                    Internet / любая сеть
                                              │
                                    https://dev-api-intercom.docx.kg
                                              │   (Let's Encrypt cert, nginx-reverse-proxy)
                                              │
                            ┌─────────────────┴─────────────────┐
                            ▼                                   ▼
                       Cloud (CRM)                         Mobile app (Flutter)
                       Web admin UI                        — REGISTER через WSS
                       FCM push                            — WHEP видео
                       Kafka events                        — JWT-auth к /api/mobile/*
                            │
                            │   wss://dev-api-intercom.docx.kg/api/devices/bridges/ws
                            │   (Bearer: CLOUD_BRIDGE_TOKEN)
                            ▼
              ┌─────────────────────────────┐
              │   Bridge — этот сервер      │   LAN: 192.168.31.132
              │   docker compose со 6       │   (плюс 10.2.2.x на VPN-интерфейсе)
              │   контейнерами              │
              └─────────────────────────────┘
                            │
                            ▼ LAN 192.168.31.0/24
                  ┌─────────┴─────────┐
                  ▼                   ▼
            Domofon-панели       Hardware-мониторы
            (sip_account=1001)   (sip_account=1003, 1004, …)
            ├ IP:80 web/unlock   ├ только SIP-UA
            ├ IP:554 RTSP        └ зарегистрированы по UDP
            └ SIP UDP/5060          в наш Asterisk
```

## 2. Контейнеры на bridge'е

```
┌─────────────────┐     ┌─────────────────┐
│  intercom-      │ ←── │  intercom-      │ ←── HTTPS :80/:443 от admin/mobile
│  frontend       │     │  nginx          │     /api/* → backend
│  (React UI)     │     │  TLS termination│     /go2rtc/* → go2rtc
└─────────────────┘     │  /sip & /asterisk
                        │  /ws → Asterisk │
                        └─────────────────┘
                                │
                ┌───────────────┼───────────────┐
                ▼               ▼               ▼
        ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
        │  backend     │  │ asterisk     │  │  go2rtc      │
        │ (FastAPI)    │  │  PJSIP+AMI   │  │  RTSP→WHEP   │
        │ :8000        │  │  :5060 UDP   │  │  :1984       │
        │              │  │  :8088 WS    │  │  :8555 WebRTC│
        │ ↔ Cloud WS   │  │ ↔ AMI :5038  │  │              │
        │ ↔ AMI :5038  │←─┤  ↔ devices   │  │              │
        │ ↔ Postgres   │  └──────────────┘  └──────────────┘
        └──────────────┘
                │
                ▼
        ┌──────────────┐                    ┌──────────────┐
        │  postgres    │                    │  coturn      │
        │  :5432       │                    │  :3478 STUN  │
        │              │                    │  TURN UDP+TCP│
        └──────────────┘                    └──────────────┘
```

| Контейнер    | За что отвечает                                                                                                                                                           |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **backend**  | FastAPI: апартменты, устройства, событийный bus, **cloud-bridge WS** (исходящий), **AMI** к Asterisk, **provisioning** `pjsip_webrtc.conf` и `extensions_apartments.conf` |
| **asterisk** | SIP-роутинг: панели/мониторы по UDP, мобильные клиенты по WSS, dialplan через `[intercom]` → `include intercom-apartments`                                                |
| **go2rtc**   | RTSP-камеры → WHEP/HLS для просмотра «через глазок» в браузере и мобиле                                                                                                   |
| **coturn**   | STUN+TURN для WebRTC, HMAC-secret для short-lived creds                                                                                                                   |
| **postgres** | Все persistent-данные (apartments, devices, monitors, webrtc_endpoints, entrances, activity logs)                                                                         |
| **frontend** | React-админка + nginx-фронт (TLS, прокси `/api/`, `/sip`, `/asterisk/ws`, `/go2rtc/`)                                                                                     |

## 3. Кого на bridge'е регистрируют

Три типа SIP-endpoint'ов, все живут в Asterisk PJSIP:

| Тип                             | Где описан                                                     | Транспорт                          | Кто это                                   |
| ------------------------------- | -------------------------------------------------------------- | ---------------------------------- | ----------------------------------------- |
| **Hardware (панели, мониторы)** | `pjsip.conf` — managed-блоки `[1001]`/`[1003]`/`[1004]`        | UDP 5060                           | Физические устройства в подъезде/квартире |
| **Browser SIP**                 | `pjsip.conf` — `[1099]` фиксированный                          | WS 8088 (через nginx /sip)         | Тест-клиент в web-админке                 |
| **Mobile WebRTC**               | `pjsip_webrtc.conf` — auto-generated `[200001]`, `[200002]`, … | WS 8088 (через nginx /asterisk/ws) | Flutter мобильное приложение              |

Mobile-endpoint'ы создаются **облаком** через WS-команду `provision_webrtc_endpoint` — это единственный способ, локально admin их не делает.

## 4. Что приходит от cloud → bridge (WS-команды)

```
                cloud
                  │
                  │  wss://…/api/devices/bridges/ws
                  │  Bearer: CLOUD_BRIDGE_TOKEN
                  ▼
                bridge backend
       (handlers в _dispatch_command)
                  │
   ┌──────────────┼──────────────┬──────────────┬──────────────┬──────────────┐
   ▼              ▼              ▼              ▼              ▼              ▼
provision_     create_         rename_       delete_       set_apartment    bootstrap_
webrtc_        apartment       apartment     apartment     _monitors        snapshot
endpoint       create row      rename        cascade       refresh         entrances[]
write          apartments      call_code     delete row    apartment_       devices[]
pjsip_webrtc   table                                       monitors;        (read-only
.conf;                                                     regen dialplan   sync)
pjsip reload

   ▼              ▼              ▼              ▼              ▼
unlock_door    answer_call    reject_call   re_invite_      update_bridge_
HTTP→device   verify mobile  hangup ALL    apartment        token
              leg exists      legs in       AMI Originate    persist + mutate
              else fail       group         to mobile        settings, await
                              individually  bridge to panel  close 4005
```

Что bridge шлёт обратно (events): `hello`, `device_snapshot`, `apartment_upserted`, `device_upserted`, `call_started`, `call_answered`, `call_ended`, `door_unlocked`, `system_health`, `media_config`, `ack` (на каждую WS-команду).

## 5. Полный жизненный цикл от подключения устройства до звонка

### Шаг 1. Admin добавляет апартмент и устройства через web-UI

```
admin → POST /api/apartments     {number: "101", call_code: "1003",
                                  entrance_id: 1, floor: 3, monitors: [
                                    {sip_account: "1003", mac_address: "AA:..."},
                                  ]}
        │
        ├─→ INSERT apartments + apartment_monitors          (Postgres)
        ├─→ write_apartments_dialplan() → extensions_apartments.conf
        │                                ↳ dialplan reload (AMI)
        └─→ emit_apartment_upserted() → cloud
            └─→ cloud upserts in CRM, ack с cloud_id

admin → POST /api/devices        {name: "Front Door Panel", device_type: "door_station",
                                  ip_address: "192.168.31.43", sip_account: "1001",
                                  rtsp_enabled: true, rtsp_url: "rtsp://…",
                                  entrance_id: 1, mac_address: "BB:..."}
        │
        ├─→ INSERT devices                                  (Postgres)
        ├─→ go2rtc_service.sync_stream(device_id, rtsp_url)
        │                                ↳ переписывает go2rtc.yaml
        └─→ emit_device_upserted() → cloud
            └─→ ack с cloud_id

admin → POST /api/devices/{id}/sip-apply  {password: "..."}
        │
        └─→ sip_service.apply_credentials()
            └─→ injects [{ext}] managed block в pjsip.conf
                + module reload res_pjsip.so (AMI)
```

### Шаг 2. Hardware-устройство регистрируется

```
panel 1001 (Hikvision) ──REGISTER──→ asterisk:5060 UDP
                       ←──401  WWW-Authenticate realm="192.168.31.132"
                       ──REGISTER+Digest─→
                       ←──200 OK Expires:299
                       (повторяет каждые 300 сек)

→ pjsip show contacts:
    Contact: 1001/sip:1001@192.168.31.43:5060   NonQual
```

### Шаг 3. Mobile-клиент проходит онбординг

```
1. Юзер логинится в Flutter → cloud отдаёт JWT
2. Cloud:  POST /internal/provisioning-snapshot → знает наш bridge_id
3. Cloud → bridge: provision_webrtc_endpoint {extension: "200001", password: "..."}
4. Bridge: → INSERT webrtc_endpoints + write pjsip_webrtc.conf + pjsip reload
           → ack {extension, sip_ws_url: "wss://192.168.31.132/asterisk/ws",
                  sip_domain: "192.168.31.132", stun: "stun:192.168.31.132:3478"}
5. Cloud сохраняет ack в bridges.media_config.sip → отдаёт мобиле
   через GET /api/mobile/media-config
6. Flutter:
   sip.js connect wss://192.168.31.132/asterisk/ws  (или wss://dev-api-…
                                                     если bridge публичный)
   REGISTER sip:200001@192.168.31.132
   ← 401 Digest realm="192.168.31.132"
   REGISTER+Digest →
   ← 200 OK Expires:60
   → pjsip show contacts:
       Contact: 200001/sip:abc@*.invalid;transport=WS
```

### Шаг 4. Cloud делает push_provisioning

```
Cloud при reconnect или setup-apartment шлёт:
  · provision_webrtc_endpoint(s)
  · set_apartment_monitors {apartment_code: "1003",
                             monitors: ["1003", "200001"]}
  · bootstrap_snapshot {entrances[], devices[]}
                                          ↑
                  fire-and-forget broadcast, ack не нужен
```

После `set_apartment_monitors`:

```
extensions_apartments.conf теперь:

[intercom-apartments]
; === apt: 1003 ===
exten => 1003,1,NoOp(Call to apartment 1003)
 same => n,Set(__CALL_ID=${UNIQUEID})
 same => n,Set(__APARTMENT_CODE=1003)
 same => n,Dial(PJSIP/1003 & PJSIP/200001, 30, tT)
 same => n,Hangup()
; === end apt: 1003 ===
```

И главный `extensions.conf` сводится к:

```
[intercom]
include => intercom-apartments
exten => h,1,NoOp(Hangup: ${CALLERID(num)})
```

## 6. Звонок панель → квартира (полный путь)

```
1. Жилец нажал кнопку «1003» на панели у входа
   panel 1001 → asterisk: INVITE sip:1003@192.168.31.132 SDP(audio UDP)

2. Asterisk:
   - Найдена exten 1003 в context intercom (через include → intercom-apartments)
   - Set __CALL_ID = ${UNIQUEID} = "1778683456.789"
   - Dial(PJSIP/1003 & PJSIP/200001, 30, tT)
     ├─→ INVITE PJSIP/1003 UDP → hardware monitor в квартире
     └─→ INVITE PJSIP/200001 WS → mobile (если контакт жив)

3. AMI events:
   - DialBegin (Linkedid=Uniqueid=1778683456.789)
     └─→ consumer.on_dial_begin
         ├─→ call_store.on_call_started(call_id="1778683456.789")
         ├─→ event_bus.publish("call_started", ...) → local SSE
         └─→ cloud_bridge.send_event("call_started", {
               call_id, caller_device_id, video_webrtc_url,
               video_hls_url, apartment_code: "1003"
             })

4. Cloud:
   - Получает call_started → создаёт запись в Kafka intercom.calls
   - SSE → mobile-clients: "incoming call"
   - FCM push → если приложение в фоне

5. Mobile:
   - Получает CallKit incoming UI
   - Юзер тапает Accept → POST /api/mobile/calls/answer
     └─→ cloud → bridge: answer_call {call_id, answered_by_sip: "200001"}
         └─→ bridge ищет в CoreShowChannels канал PJSIP/200001-* с тем же Linkedid
             ├─ если есть → call_answered → cloud silences other devices → ack ok
             └─ если нет (mobile contact умер в Doze) → "callee_leg_missing"
                 └─→ cloud → bridge: re_invite_apartment {call_id, callee_sip_extension: "200001"}
                     ├─→ poll "pjsip show contacts" пока mobile не зарегистрируется (≤10s)
                     ├─→ AMI Originate {Channel: PJSIP/200001, Application: Bridge,
                     │                  Data: <panel_chan>, Async: true}
                     └─→ ack ok, audio_status: established

6. Mobile отвечает SIP 200 OK на INVITE:
   - Asterisk → BridgeEnter event → consumer.on_bridge_enter
     └─→ call_answered → cloud
   - Audio: SRTP(mobile) ↔ Asterisk media bridge ↔ RTP(panel) — Asterisk транскодит DTLS↔plain
   - Hardware monitor получает CANCEL (parallel dial cancels losers)

7. Юзер слушает гостя, нажимает «Open Door»:
   - POST /api/mobile/calls/unlock
     └─→ cloud → bridge: unlock_door {call_id, device_local_id: 2}
         └─→ bridge → HTTP GET http://192.168.31.43:8000/unlock?lock=1
             └─→ event_bus.publish("door_opened", ...) → cloud (door_unlocked)

8. Один из них кладёт трубку:
   - SIP BYE → Asterisk → Hangup event
   - consumer.on_hangup ловит ТОЛЬКО когда Uniqueid == Linkedid (panel-channel)
     └─→ call_ended → cloud → mobile dismisses UI
```

## 7. Ключевые архитектурные решения

| Что                                                                                | Почему так                                                                                                       |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| **TLS только на nginx**                                                            | Self-signed → Let's Encrypt через `dev-api-intercom.docx.kg`. До Asterisk идёт plain `ws`.                       |
| **`direct_media=no` у WebRTC**                                                     | Asterisk обязан сидеть в media path: панель=plain UDP, мобила=DTLS-SRTP — peer-to-peer не сошлись бы.            |
| **`rewrite_contact=yes` + `rtp_symmetric=yes`**                                    | Mobile шлёт Contact `sip:*.invalid;transport=ws`. Asterisk подменяет на реальный сокет для re-INVITE/Hangup.     |
| **`default_expiration=120` + `remove_existing=no` + `qualify_frequency=0`**        | Mobile Doze (60-90s sleep) не должен убивать AOR. Не пингуем OPTIONS — энерго-жор и ложные Unreachable.          |
| **Линки `set_apartment_monitors` → `_rebuild_all_dialplan`**                       | Cloud — source of truth для маппинга apartment→monitors. Bridge пассивно sync'ает.                               |
| **`__CALL_ID` channel var**                                                        | Чтобы `re_invite_apartment` и `reject_call` могли найти panel-channel через AMI после long delay.                |
| **`emit_apartment_upserted` / `emit_device_upserted` с `cloud_synced` durability** | Admin может создать сущность пока cloud offline → флаг в БД → retry на startup.                                  |
| **`bootstrap_snapshot` от cloud**                                                  | После hello cloud один раз шлёт entrances+devices, bridge кеширует — admin UI знает какие entrance_id допустимы. |
| **`on_hangup` фильтрует `Uniqueid == Linkedid`**                                   | Иначе CANCEL на cancelled leg в parallel-Dial вызывал бы phantom `call_ended` через 3 сек после answer.          |
| **`_cmd_reject_call` энумерирует ВСЕ legs в группе**                               | Asterisk не пропагирует CANCEL детям Dial() в early-media — каждую ногу убиваем явно.                            |

## 8. Типичные проблемы и где смотреть

| Симптом                                                            | Корень                                                   | Чем чинить                                                                         |
| ------------------------------------------------------------------ | -------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Mobile не получает INVITE                                          | Контакт умер между REGISTER и Dial (Doze)                | `re_invite_apartment` fallback срабатывает автоматически                           |
| `answer_call` ack OK но звонок «провалился»                        | Mobile leg в Dial-группе никогда не создавался           | `_cmd_answer_call` проверяет существование leg'а → `callee_leg_missing` → fallback |
| `reject_call` ack OK но gate продолжает звонить                    | Asterisk не propagates CANCEL детям Dial() в early-media | Bridge явно Hangup'ит каждый канал по Linkedid                                     |
| 404 на `?src=panel-N` в WHEP                                       | Device c этим id не имеет `rtsp_enabled=true`            | Включить RTSP у устройства или фронт не должен запрашивать                         |
| `cloud_synced=false` у apartment/device                            | Нет `entrance_id`, либо cloud отверг (e.g. dup MAC)      | Видно в admin UI как красный bullet с tooltip `last_cloud_sync_error`              |
| INVITE на mobile падает с `Could not create dialog to invalid URI` | Контакт в AOR удалён, AOR пуст                           | `re_invite_apartment` после REGISTER                                               |

---

## 9. Установка и эксплуатация

### Требования

- Ubuntu 22.04+ или любой Linux с Docker 24+ и Docker Compose v2
- 2 ГБ ОЗУ, 10 ГБ диска
- Открытые порты: `80`, `443` (web/WSS), `5060/udp` (SIP), `3478/udp+tcp` (STUN/TURN), `8088` (только в localhost — Asterisk WS)

### Быстрый старт

```bash
git clone <repo> intercome
cd intercome
cp backend/.env.example .env
# отредактируй .env — обязательно укажи свой SERVER_IP, PUBLIC_BRIDGE_HOST и CLOUD_*

docker compose up -d --build
```

### Ключевые переменные `.env`

| Имя                  | Что значит                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------------ |
| `SERVER_IP`          | LAN-IP машины, на которой крутится bridge. Используется по умолчанию там где не задано иное.           |
| `PUBLIC_BRIDGE_HOST` | Адрес, по которому mobile-клиент видит bridge. На LAN-тестах = `SERVER_IP`, в проде — публичный домен. |
| `SIP_DOMAIN`         | SIP realm для Digest auth. Должен совпадать с `default_realm` в `pjsip.conf`.                          |
| `CLOUD_WS_URL`       | WS URL облака. Сейчас `wss://dev-api-intercom.docx.kg/api/devices/bridges/ws`.                         |
| `CLOUD_BRIDGE_TOKEN` | Bearer-токен, выдаваемый облаком после `POST /api/devices/bridges`.                                    |
| `COTURN_SECRET`      | HMAC-secret для short-lived TURN credentials. Должен совпадать с `--static-auth-secret` у coturn.      |
| `INTERCOM_STUN_URL`  | URL STUN, отдаваемый мобиле. По умолчанию `stun:${SERVER_IP}:3478`.                                    |
| `DATABASE_URL`       | Строка подключения Postgres. По умолчанию использует containerized `postgres:5432`.                    |

### Полезные команды

```bash
# Все логи
docker compose logs -f backend

# Только Asterisk
docker logs -f intercom-asterisk

# SIP-трафик (детальный)
docker exec intercom-asterisk asterisk -rx "pjsip set logger on"

# Текущие SIP-контакты
docker exec intercom-asterisk asterisk -rx "pjsip show contacts"

# Текущий dialplan для апартмента
docker exec intercom-asterisk asterisk -rx "dialplan show 1003@intercom-apartments"

# Перезагрузить dialplan вручную
docker exec intercom-asterisk asterisk -rx "dialplan reload"

# Перезагрузить PJSIP без рестарта Asterisk
docker exec intercom-asterisk asterisk -rx "module reload res_pjsip.so"

# Список устройств в БД
docker exec intercom-postgres psql -U intercom -d intercom -c \
  "SELECT id, name, device_type, sip_account, entrance_id, cloud_id, cloud_synced FROM devices;"

# Список квартир
docker exec intercom-postgres psql -U intercom -d intercom -c \
  "SELECT id, call_code, entrance_id, cloud_id, cloud_synced, last_cloud_sync_error FROM apartments;"

# Кэшированные entrances
docker exec intercom-postgres psql -U intercom -d intercom -c \
  "SELECT id, cloud_id, number, building_address FROM entrances;"
```

### Web-UI

- `https://<SERVER_IP>` — админка (логин из `.env` `ADMIN_USERNAME`/`ADMIN_PASSWORD`)
- `https://<SERVER_IP>/api/docs` — Swagger
- `https://<SERVER_IP>/api/redoc` — ReDoc

### Troubleshooting checklist

1. **Bridge не подключается к облаку**: проверь сетевую достижимость `CLOUD_WS_URL` (`curl -I https://dev-api-intercom.docx.kg/`), валидность токена в `.env` или в `/app/data/cloud_bridge_token` (если был `update_bridge_token`).
2. **Mobile не регистрируется**: проверь что в `pjsip_webrtc.conf` есть нужный `[200xxx]` блок и `pjsip show endpoint 200xxx` показывает `transport-ws`.
3. **Звонок не доходит до Flutter**: смотри `pjsip show contacts 200xxx` — если пусто, контакт умер в Doze, `re_invite_apartment` должен сработать на следующий answer.
4. **Видео нет в браузере**: проверь `https://<SERVER_IP>/go2rtc/api/streams` — нужный `panel-{device_id}` должен быть в списке.
5. **Apartment не уезжает в облако**: смотри `cloud_synced=false` в БД и `last_cloud_sync_error` — обычно `entrance_id` не задан или невалиден.
