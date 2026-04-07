import { useDashboard } from "@/hooks/useDashboard";
import { StatCard } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ACTIVITY_ACTION_LABELS, formatDate } from "@/lib/utils";
import {
  Monitor,
  DoorOpen,
  Home,
  Wifi,
  WifiOff,
  GitFork,
  HelpCircle,
} from "lucide-react";

export function DashboardPage() {
  const { data, isLoading, isError } = useDashboard();

  if (isLoading)
    return (
      <div className="p-8 text-gray-400 flex items-center gap-2">
        <svg className="animate-spin h-5 w-5" fill="none" viewBox="0 0 24 24">
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8v8H4z"
          />
        </svg>
        Loading dashboard…
      </div>
    );

  if (isError || !data)
    return <div className="p-8 text-red-500">Failed to load dashboard.</div>;

  return (
    <div className="p-8 space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-500 text-sm mt-1">Intercom system overview</p>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Total Devices"
          value={data.total_devices}
          icon={<Monitor className="w-5 h-5" />}
        />
        <StatCard
          label="Online"
          value={data.online_devices}
          color="text-green-600"
          icon={<Wifi className="w-5 h-5 text-green-600" />}
        />
        <StatCard
          label="Offline"
          value={data.offline_devices}
          color="text-red-600"
          icon={<WifiOff className="w-5 h-5 text-red-600" />}
        />
        <StatCard
          label="Unknown"
          value={data.unknown_devices}
          color="text-yellow-600"
          icon={<HelpCircle className="w-5 h-5 text-yellow-600" />}
        />
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Door Stations"
          value={data.door_stations}
          icon={<DoorOpen className="w-5 h-5" />}
        />
        <StatCard
          label="Home Stations"
          value={data.home_stations}
          icon={<Home className="w-5 h-5" />}
        />
        <StatCard
          label="Routing Rules"
          value={data.total_routing_rules}
          sub={`${data.active_routing_rules} active`}
          icon={<GitFork className="w-5 h-5" />}
        />
        <StatCard
          label="Other Devices"
          value={data.guard_stations + data.sip_clients + data.cameras}
          sub="Guard / SIP / Camera"
          icon={<Monitor className="w-5 h-5" />}
        />
      </div>

      {/* Recent activity */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 className="text-base font-semibold text-gray-900">
            Recent Activity
          </h2>
        </div>
        <div className="divide-y divide-gray-50">
          {data.recent_activity.length === 0 && (
            <p className="px-6 py-6 text-sm text-gray-400">No activity yet.</p>
          )}
          {data.recent_activity.map((log) => (
            <div
              key={log.id}
              className="px-6 py-3 flex items-center justify-between"
            >
              <div className="flex items-center gap-3">
                <Badge variant={log.success ? "green" : "red"}>
                  {log.success ? "✓" : "✕"}
                </Badge>
                <div>
                  <p className="text-sm font-medium text-gray-800">
                    {ACTIVITY_ACTION_LABELS[log.action] ?? log.action}
                  </p>
                  {log.detail && (
                    <p className="text-xs text-gray-400 mt-0.5 truncate max-w-md">
                      {log.detail}
                    </p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-3 text-xs text-gray-400">
                {log.actor && <span>{log.actor}</span>}
                <span>{formatDate(log.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
