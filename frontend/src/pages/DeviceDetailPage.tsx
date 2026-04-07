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
            Latency: {formatLatency(result.latency_ms)}
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

  if (isLoading) return <div className="p-8 text-gray-400">Loading…</div>;
  if (!device) return <div className="p-8 text-red-500">Device not found.</div>;

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
            <Pencil className="w-4 h-4" /> Edit
          </Button>
          <Button variant="danger" size="sm" onClick={handleDelete}>
            <Trash2 className="w-4 h-4" /> Delete
          </Button>
        </div>
      </div>

      {/* Actions */}
      <Card>
        <CardHeader>
          <CardTitle>Actions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-3">
            <div className="flex-1">
              <Button
                variant="secondary"
                onClick={handleTestConn}
                loading={testConnection.isPending}
              >
                <Wifi className="w-4 h-4" /> Test Connection
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
                  <Unlock className="w-4 h-4" /> Test Unlock
                </Button>
                {unlockResult && <ResultBanner result={unlockResult} />}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-4">
        {/* Network */}
        <Card>
          <CardHeader>
            <CardTitle>Network</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="space-y-3">
              <Field label="IP Address" value={device.ip_address} />
              <Field label="Web Port" value={device.web_port} />
              <Field label="Last Seen" value={formatDate(device.last_seen)} />
            </dl>
          </CardContent>
        </Card>

        {/* SIP */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              SIP Configuration
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
                <Field label="SIP Account" value={device.sip_account} />
                <Field label="SIP Server" value={device.sip_server} />
                <Field label="SIP Port" value={device.sip_port} />
                <Field label="SIP Proxy" value={device.sip_proxy} />
              </dl>
            ) : (
              <p className="text-sm text-gray-400">SIP not configured</p>
            )}
          </CardContent>
        </Card>

        {/* RTSP */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              RTSP Stream
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
                  RTSP URL
                </p>
                <p className="text-sm font-mono text-gray-900 break-all">
                  {device.rtsp_url}
                </p>
              </div>
            ) : (
              <p className="text-sm text-gray-400">RTSP not configured</p>
            )}
          </CardContent>
        </Card>

        {/* Unlock */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Door Unlock
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
                  label="Method"
                  value={UNLOCK_METHOD_LABELS[device.unlock_method]}
                />
                <Field label="Unlock URL" value={device.unlock_url} />
                <Field label="Username" value={device.unlock_username} />
              </dl>
            ) : (
              <p className="text-sm text-gray-400">Unlock not configured</p>
            )}
          </CardContent>
        </Card>
      </div>

      {device.notes && (
        <Card>
          <CardHeader>
            <CardTitle>Notes</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-gray-700">{device.notes}</p>
          </CardContent>
        </Card>
      )}

      <div className="text-xs text-gray-400 flex gap-4">
        <span>Created: {formatDate(device.created_at)}</span>
        <span>Updated: {formatDate(device.updated_at)}</span>
      </div>

      <DeviceFormModal
        open={editOpen}
        onClose={() => setEditOpen(false)}
        device={device}
      />
    </div>
  );
}
