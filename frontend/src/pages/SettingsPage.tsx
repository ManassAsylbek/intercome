import { useSystemInfo } from "@/hooks/useDashboard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Settings, Server, Database, Radio } from "lucide-react";

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

export function SettingsPage() {
  const { data: sysInfo } = useSystemInfo();

  return (
    <div className="p-8 space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 text-sm mt-1">
          Server configuration and integration status
        </p>
      </div>

      {/* Server info */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="w-4 h-4" /> Server Information
          </CardTitle>
        </CardHeader>
        <CardContent>
          {sysInfo ? (
            <div>
              <InfoRow label="Server IP" value={sysInfo.server_ip} />
              <InfoRow label="Environment" value={sysInfo.app_env} />
              <InfoRow label="Version" value={sysInfo.version} />
              <InfoRow label="Database" value={sysInfo.database_url_safe} />
            </div>
          ) : (
            <p className="text-sm text-gray-400">Loading…</p>
          )}
        </CardContent>
      </Card>

      {/* Integrations */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Radio className="w-4 h-4" /> Asterisk / SIP Integration
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm text-gray-600">
              Asterisk AMI connection
            </span>
            <Badge variant="yellow">Not Configured</Badge>
          </div>
          <p className="text-sm text-gray-400 bg-gray-50 rounded-lg p-4 border border-gray-100">
            <strong>Future integration:</strong> Configure Asterisk AMI
            credentials in{" "}
            <code className="bg-gray-100 px-1 rounded">.env</code> to enable SIP
            call routing, peer registration, and DTMF-based door unlock. This
            server acts as the management layer — Asterisk handles the actual
            SIP signaling.
          </p>
          <div className="mt-4 space-y-2 text-xs text-gray-400">
            <p>Planned .env settings:</p>
            <pre className="bg-gray-900 text-green-400 rounded-lg p-3 overflow-auto">
              {`ASTERISK_HOST=192.168.31.132
ASTERISK_AMI_PORT=5038
ASTERISK_AMI_USER=admin
ASTERISK_AMI_PASSWORD=secret`}
            </pre>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Settings className="w-4 h-4" /> RTSP / Media Server
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm text-gray-600">MediaMTX / RTSP proxy</span>
            <Badge variant="yellow">Not Configured</Badge>
          </div>
          <p className="text-sm text-gray-400 bg-gray-50 rounded-lg p-4 border border-gray-100">
            <strong>Future integration:</strong> Set up MediaMTX (or similar) to
            proxy RTSP streams as HLS/WebRTC for browser playback. The RTSP URL
            per device is already stored and ready.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="w-4 h-4" /> Database Migration (PostgreSQL)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-gray-400 bg-gray-50 rounded-lg p-4 border border-gray-100">
            The backend uses SQLAlchemy with async support. To switch from
            SQLite to PostgreSQL, update{" "}
            <code className="bg-gray-100 px-1 rounded">DATABASE_URL</code> in
            <code className="bg-gray-100 px-1 rounded"> backend/.env</code> and
            run{" "}
            <code className="bg-gray-100 px-1 rounded">
              alembic upgrade head
            </code>
            .
          </p>
          <div className="mt-3">
            <pre className="bg-gray-900 text-green-400 rounded-lg p-3 overflow-auto text-xs">
              {`# PostgreSQL example
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/intercom`}
            </pre>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
