import { useState } from "react";
import { useSystemInfo, useAsteriskHealth } from "@/hooks/useDashboard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { apiClient } from "@/api/client";
import {
  Settings,
  Server,
  Database,
  Radio,
  CheckCircle2,
  XCircle,
  Wifi,
  RefreshCw,
} from "lucide-react";

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-gray-50 last:border-0">
      <span className="text-sm text-gray-500">{label}</span>
      <span className="text-sm font-medium text-gray-900 font-mono">
        {value}
      </span>
    </div>
  );
}

function StatusDot({ ok }: { ok: boolean }) {
  return ok ? (
    <CheckCircle2 className="w-4 h-4 text-green-500" />
  ) : (
    <XCircle className="w-4 h-4 text-red-400" />
  );
}

export function SettingsPage() {
  const { data: sysInfo } = useSystemInfo();
  const {
    data: asterisk,
    isLoading: asteriskLoading,
    refetch,
  } = useAsteriskHealth();
  const [reloading, setReloading] = useState(false);

  const asteriskOk = asterisk?.status === "configured";

  const handleAsteriskReload = async () => {
    setReloading(true);
    try {
      const res = await apiClient.post<{ success: boolean; message: string }>(
        "/system/asterisk-reload",
      );
      if (res.data.success) {
        toast(res.data.message, "success");
      } else {
        toast(res.data.message, "error");
      }
      refetch();
    } catch {
      toast("Ошибка при перезагрузке Asterisk", "error");
    } finally {
      setReloading(false);
    }
  };

  return (
    <div className="p-8 space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Настройки</h1>
        <p className="text-gray-500 text-sm mt-1">
          Конфигурация сервера и статус интеграций
        </p>
      </div>

      {/* Server info */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="w-4 h-4" /> Информация о сервере
          </CardTitle>
        </CardHeader>
        <CardContent>
          {sysInfo ? (
            <div>
              <InfoRow label="IP-адрес сервера" value={sysInfo.server_ip} />
              <InfoRow label="Среда" value={sysInfo.app_env} />
              <InfoRow label="Версия" value={sysInfo.version} />
              <InfoRow label="База данных" value={sysInfo.database_url_safe} />
              <div className="flex items-center justify-between py-3 border-b border-gray-50 last:border-0">
                <span className="text-sm text-gray-500">URL фронтенда</span>
                <span className="text-sm font-medium text-blue-600 font-mono">
                  {window.location.origin}
                </span>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-400">Загрузка…</p>
          )}
        </CardContent>
      </Card>

      {/* Asterisk */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Radio className="w-4 h-4" /> Asterisk / SIP Integration
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Live status */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-600">Статус pjsip.conf</span>
            <div className="flex items-center gap-3">
              {asteriskLoading ? (
                <Badge variant="yellow">Проверка…</Badge>
              ) : asteriskOk ? (
                <div className="flex items-center gap-2">
                  <StatusDot ok={true} />
                  <Badge variant="green">Настроено</Badge>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <StatusDot ok={false} />
                  <Badge variant="yellow">Не настроено</Badge>
                </div>
              )}
              <Button
                size="sm"
                variant="secondary"
                loading={reloading}
                onClick={handleAsteriskReload}
                title="Перезагрузить модули Asterisk через AMI"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Reload Asterisk
              </Button>
            </div>
          </div>

          {asterisk && (
            <div className="grid grid-cols-2 gap-2 text-xs text-gray-500 bg-gray-50 rounded-lg p-3 border border-gray-100">
              <span>Mode:</span>
              <span className="font-mono font-medium text-gray-800">
                {asterisk.mode}
              </span>
              <span>pjsip.conf:</span>
              <span className="font-mono font-medium text-gray-800 break-all">
                {asterisk.pjsip_conf}
              </span>
              <span>Readable:</span>
              <span className="font-mono font-medium text-gray-800">
                {asterisk.pjsip_readable ? "yes" : "no"}
              </span>
              {asterisk.detail && asterisk.detail !== "OK" && (
                <>
                  <span>Detail:</span>
                  <span className="font-mono text-red-600 break-all">
                    {asterisk.detail}
                  </span>
                </>
              )}
            </div>
          )}

          {/* Setup instructions */}
          <div className="rounded-lg border border-blue-100 bg-blue-50 p-4 space-y-3">
            <p className="text-sm font-semibold text-blue-800">
              Как подключить Asterisk
            </p>
            <p className="text-xs text-blue-700">
              Откройте{" "}
              <code className="bg-blue-100 px-1 rounded">backend/.env</code> и
              задайте:
            </p>

            <div className="space-y-3">
              <div>
                <p className="text-xs font-medium text-blue-700 mb-1">
                  Вариант A — Asterisk на том же сервере:
                </p>
                <pre className="bg-gray-900 text-green-400 rounded-lg p-3 text-xs overflow-auto">{`ASTERISK_MODE=local
ASTERISK_PJSIP_CONF=/etc/asterisk/pjsip.conf
ASTERISK_RELOAD_CMD=sudo systemctl restart asterisk`}</pre>
              </div>
              <div>
                <p className="text-xs font-medium text-blue-700 mb-1">
                  Вариант B — Asterisk на удалённом сервере (по SSH):
                </p>
                <pre className="bg-gray-900 text-green-400 rounded-lg p-3 text-xs overflow-auto">{`ASTERISK_MODE=ssh
ASTERISK_PJSIP_CONF=/etc/asterisk/pjsip.conf
ASTERISK_RELOAD_CMD=sudo systemctl restart asterisk
ASTERISK_SSH_HOST=192.168.50.10
ASTERISK_SSH_PORT=22
ASTERISK_SSH_USER=pi
ASTERISK_SSH_KEY_FILE=/home/user/.ssh/id_rsa`}</pre>
              </div>
            </div>
            <p className="text-xs text-blue-600">
              После изменения .env — перезапустите бэкенд. Затем в карточке
              устройства (Edit → SIP Configuration) появится кнопка{" "}
              <strong>Apply to Asterisk</strong>, которая запишет аккаунт в
              pjsip.conf и перезагрузит Asterisk одним кликом.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Quick Start */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Wifi className="w-4 h-4" /> Быстрый старт на новом устройстве
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-gray-500">
            Чтобы запустить проект на любом компьютере в одну команду:
          </p>
          <pre className="bg-gray-900 text-green-400 rounded-lg p-3 text-xs overflow-auto">{`# Клонировать и запустить
git clone <repo>
cd intercome-v2

# Docker (рекомендуется — всё в одном)
docker compose up -d
# → открыть http://localhost

# Или без Docker:
./start.sh`}</pre>
          <p className="text-xs text-gray-400">
            После запуска — открыть браузер, войти как{" "}
            <code className="bg-gray-100 px-1 rounded">admin / admin123</code>,
            добавить устройства через <strong>Devices → Add Device</strong>,
            указать IP, тип, SIP-аккаунт.
          </p>
        </CardContent>
      </Card>

      {/* RTSP */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings className="w-4 h-4" /> RTSP / Media Server
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm text-gray-600">MediaMTX / RTSP proxy</span>
            <Badge variant="yellow">Не настроено</Badge>
          </div>
          <p className="text-sm text-gray-400 bg-gray-50 rounded-lg p-4 border border-gray-100">
            RTSP URL для каждого устройства уже хранится в базе. Для просмотра
            видео в браузере настройте MediaMTX как прокси HLS/WebRTC.
          </p>
        </CardContent>
      </Card>

      {/* Database */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="w-4 h-4" /> Database
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-gray-400 bg-gray-50 rounded-lg p-4 border border-gray-100">
            По умолчанию используется SQLite. Для PostgreSQL обновите{" "}
            <code className="bg-gray-100 px-1 rounded">DATABASE_URL</code> в{" "}
            <code className="bg-gray-100 px-1 rounded">backend/.env</code> и
            выполните{" "}
            <code className="bg-gray-100 px-1 rounded">
              alembic upgrade head
            </code>
            .
          </p>
          <div className="mt-3">
            <pre className="bg-gray-900 text-green-400 rounded-lg p-3 overflow-auto text-xs">
              {`DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/intercom`}
            </pre>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
