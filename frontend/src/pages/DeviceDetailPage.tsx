import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
  useDevice,
  useTestConnection,
  useTestUnlock,
  useDeleteDevice,
} from "@/hooks/useDevices";
import { Button } from "@/components/ui/Button";
import { Badge, OnlineBadge } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { DeviceFormModal } from "@/components/devices/DeviceFormModal";
import { WebRTCPlayer } from "@/components/ui/WebRTCPlayer";
import { toast } from "@/components/ui/Toast";
import {
  DEVICE_TYPE_LABELS,
  UNLOCK_METHOD_LABELS,
  formatDate,
  formatLatency,
} from "@/lib/utils";
import type { ActionResult } from "@/types";
import {
  ArrowLeft,
  Pencil,
  Trash2,
  Wifi,
  Unlock,
  Check,
  X,
  Video,
} from "lucide-react";

function ResultBanner({ result }: { result: ActionResult }) {
  return (
    <div
      className={`mt-3 flex items-start gap-2 rounded-lg px-4 py-3 text-sm ${
        result.success
          ? "bg-green-50 border border-green-200 text-green-800"
          : "bg-red-50 border border-red-200 text-red-800"
      }`}
    >
      {result.success ? (
        <Check className="w-4 h-4 mt-0.5" />
      ) : (
        <X className="w-4 h-4 mt-0.5" />
      )}
      <div>
        <p className="font-medium">{result.message}</p>
        {result.detail && (
          <p className="text-xs mt-0.5 opacity-80">{result.detail}</p>
        )}
        {result.latency_ms != null && (
          <p className="text-xs mt-0.5 opacity-60">
            Задержка: {formatLatency(result.latency_ms)}
          </p>
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  value,
}: {
  label: string;
  value?: string | number | boolean | null;
}) {
  if (value === null || value === undefined || value === "") return null;
  const display =
    typeof value === "boolean" ? (value ? "Yes" : "No") : String(value);
  return (
    <div>
      <dt className="text-xs text-gray-400 uppercase tracking-wide">{label}</dt>
      <dd className="text-sm text-gray-900 font-medium mt-0.5 font-mono">
        {display}
      </dd>
    </div>
  );
}

export function DeviceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const deviceId = Number(id);

  const { data: device, isLoading } = useDevice(deviceId);
  const testConnection = useTestConnection();
  const testUnlock = useTestUnlock();
  const deleteDevice = useDeleteDevice();

  const [connResult, setConnResult] = useState<ActionResult | null>(null);
  const [unlockResult, setUnlockResult] = useState<ActionResult | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [showStream, setShowStream] = useState(false);

  const handleTestConn = async () => {
    setConnResult(null);
    try {
      const res = await testConnection.mutateAsync(deviceId);
      setConnResult(res);
    } catch {
      toast("Connection test failed", "error");
    }
  };

  const handleTestUnlock = async () => {
    setUnlockResult(null);
    try {
      const res = await testUnlock.mutateAsync(deviceId);
      setUnlockResult(res);
    } catch {
      toast("Unlock test failed", "error");
    }
  };

  const handleDelete = async () => {
    if (!device || !confirm(`Delete "${device.name}"?`)) return;
    await deleteDevice.mutateAsync(device.id);
    toast("Device deleted", "success");
    navigate("/devices");
  };

  if (isLoading) return <div className="p-8 text-gray-400">Загрузка…</div>;
  if (!device)
    return <div className="p-8 text-red-500">Устройство не найдено.</div>;

  return (
    <div className="p-8 space-y-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <Link to="/devices">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="w-4 h-4" />
            </Button>
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{device.name}</h1>
            <div className="flex items-center gap-2 mt-1">
              <Badge variant="blue">
                {DEVICE_TYPE_LABELS[device.device_type]}
              </Badge>
              <OnlineBadge isOnline={device.is_online} />
              {!device.enabled && <Badge variant="gray">Disabled</Badge>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setEditOpen(true)}
          >
            <Pencil className="w-4 h-4" /> Редактировать
          </Button>
          <Button variant="danger" size="sm" onClick={handleDelete}>
            <Trash2 className="w-4 h-4" /> Удалить
          </Button>
        </div>
      </div>

      {/* Actions */}
      <Card>
        <CardHeader>
          <CardTitle>Действия</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-3">
            <div className="flex-1">
              <Button
                variant="secondary"
                onClick={handleTestConn}
                loading={testConnection.isPending}
              >
                <Wifi className="w-4 h-4" /> Проверить соединение
              </Button>
              {connResult && <ResultBanner result={connResult} />}
            </div>
            {device.unlock_enabled && (
              <div className="flex-1">
                <Button
                  variant="success"
                  onClick={handleTestUnlock}
                  loading={testUnlock.isPending}
                >
                  <Unlock className="w-4 h-4" /> Тест открытия
                </Button>
                {unlockResult && <ResultBanner result={unlockResult} />}
              </div>
            )}
            {device.rtsp_enabled && (
              <div className="flex-1">
                <Button
                  variant="secondary"
                  onClick={() => setShowStream((v) => !v)}
                >
                  <Video className="w-4 h-4" />
                  {showStream ? "Скрыть видео" : "Смотреть видео"}
                </Button>
              </div>
            )}
          </div>
          {showStream && device.rtsp_enabled && (
            <div className="mt-4 rounded-xl overflow-hidden border border-gray-200">
              <WebRTCPlayer src={`panel-${device.id}`} />
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-4">
        {/* Network */}
        <Card>
          <CardHeader>
            <CardTitle>Сеть</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="space-y-3">
              <Field label="IP-адрес" value={device.ip_address} />
              <Field label="Веб-порт" value={device.web_port} />
              <Field
                label="Последная активность"
                value={formatDate(device.last_seen)}
              />
            </dl>
          </CardContent>
        </Card>

        {/* SIP */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              SIP-конфигурация
              {device.sip_enabled ? (
                <Badge variant="green">Enabled</Badge>
              ) : (
                <Badge variant="gray">Disabled</Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {device.sip_enabled ? (
              <dl className="space-y-3">
                <Field label="SIP-аккаунт" value={device.sip_account} />
                <Field label="SIP-сервер" value={device.sip_server} />
                <Field label="SIP-порт" value={device.sip_port} />
                <Field label="SIP-прокси" value={device.sip_proxy} />
              </dl>
            ) : (
              <p className="text-sm text-gray-400">SIP не настроен</p>
            )}
          </CardContent>
        </Card>

        {/* RTSP */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Видеопоток RTSP
              {device.rtsp_enabled ? (
                <Badge variant="green">Enabled</Badge>
              ) : (
                <Badge variant="gray">Disabled</Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {device.rtsp_enabled && device.rtsp_url ? (
              <div>
                <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">
                  RTSP адрес
                </p>
                <p className="text-sm font-mono text-gray-900 break-all">
                  {device.rtsp_url}
                </p>
              </div>
            ) : (
              <p className="text-sm text-gray-400">RTSP не настроен</p>
            )}
          </CardContent>
        </Card>

        {/* Unlock */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Открытие двери
              {device.unlock_enabled ? (
                <Badge variant="green">Enabled</Badge>
              ) : (
                <Badge variant="gray">Disabled</Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {device.unlock_enabled ? (
              <dl className="space-y-3">
                <Field
                  label="Метод"
                  value={UNLOCK_METHOD_LABELS[device.unlock_method]}
                />
                <Field label="URL открытия" value={device.unlock_url} />
                <Field label="Пользователь" value={device.unlock_username} />
              </dl>
            ) : (
              <p className="text-sm text-gray-400">Открытие не настроено</p>
            )}
          </CardContent>
        </Card>
      </div>

      {device.notes && (
        <Card>
          <CardHeader>
            <CardTitle>Примечания</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-gray-700">{device.notes}</p>
          </CardContent>
        </Card>
      )}

      <div className="text-xs text-gray-400 flex gap-4">
        <span>Создано: {formatDate(device.created_at)}</span>
        <span>Обновлено: {formatDate(device.updated_at)}</span>
      </div>

      <DeviceFormModal
        open={editOpen}
        onClose={() => setEditOpen(false)}
        device={device}
      />
    </div>
  );
}
