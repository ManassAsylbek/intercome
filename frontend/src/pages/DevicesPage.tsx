import { useState } from "react";
import { Link } from "react-router-dom";
import { useDevices, useDeleteDevice } from "@/hooks/useDevices";
import { Button } from "@/components/ui/Button";
import { Badge, OnlineBadge } from "@/components/ui/Badge";
import { DeviceFormModal } from "@/components/devices/DeviceFormModal";
import { toast } from "@/components/ui/Toast";
import { DEVICE_TYPE_LABELS } from "@/lib/utils";
import type { Device, DeviceType } from "@/types";
import { Plus, Pencil, Trash2, Eye, Filter } from "lucide-react";

const DEVICE_TYPES: { value: string; label: string }[] = [
  { value: "", label: "All Types" },
  { value: "door_station", label: "Door Station" },
  { value: "home_station", label: "Home Station" },
  { value: "guard_station", label: "Guard Station" },
  { value: "sip_client", label: "SIP Client" },
  { value: "camera", label: "Camera" },
];

const TYPE_BADGE: Record<
  DeviceType,
  "blue" | "green" | "purple" | "yellow" | "gray"
> = {
  door_station: "blue",
  home_station: "green",
  guard_station: "purple",
  sip_client: "yellow",
  camera: "gray",
};

export function DevicesPage() {
  const [typeFilter, setTypeFilter] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editDevice, setEditDevice] = useState<Device | null>(null);

  const { data, isLoading } = useDevices(
    typeFilter ? { device_type: typeFilter } : undefined,
  );
  const deleteDevice = useDeleteDevice();

  const handleDelete = async (device: Device) => {
    if (!confirm(`Delete device "${device.name}"?`)) return;
    try {
      await deleteDevice.mutateAsync(device.id);
      toast("Device deleted", "success");
    } catch {
      toast("Failed to delete device", "error");
    }
  };

  const openCreate = () => {
    setEditDevice(null);
    setModalOpen(true);
  };

  const openEdit = (device: Device) => {
    setEditDevice(device);
    setModalOpen(true);
  };

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Devices</h1>
          <p className="text-gray-500 text-sm mt-1">
            {data?.total ?? 0} device{data?.total !== 1 ? "s" : ""} configured
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="w-4 h-4" />
          Add Device
        </Button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2">
        <Filter className="w-4 h-4 text-gray-400" />
        {DEVICE_TYPES.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => setTypeFilter(value)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              typeFilter === value
                ? "bg-indigo-600 text-white"
                : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-gray-400">Loading…</div>
        ) : !data?.items.length ? (
          <div className="p-12 text-center">
            <p className="text-gray-400 mb-4">No devices found.</p>
            <Button onClick={openCreate} size="sm">
              <Plus className="w-4 h-4" />
              Add your first device
            </Button>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Name
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Type
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  IP Address
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Status
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Features
                </th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {data.items.map((device) => (
                <tr
                  key={device.id}
                  className="hover:bg-gray-50 transition-colors"
                >
                  <td className="px-6 py-4">
                    <div>
                      <p className="font-medium text-gray-900">{device.name}</p>
                      {device.notes && (
                        <p className="text-xs text-gray-400 mt-0.5 truncate max-w-xs">
                          {device.notes}
                        </p>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    <Badge variant={TYPE_BADGE[device.device_type]}>
                      {DEVICE_TYPE_LABELS[device.device_type]}
                    </Badge>
                  </td>
                  <td className="px-4 py-4 text-gray-600 font-mono text-xs">
                    {device.ip_address ?? "—"}
                    {device.web_port && (
                      <span className="text-gray-400">:{device.web_port}</span>
                    )}
                  </td>
                  <td className="px-4 py-4">
                    <OnlineBadge isOnline={device.is_online} />
                  </td>
                  <td className="px-4 py-4">
                    <div className="flex gap-1">
                      {device.sip_enabled && <Badge variant="blue">SIP</Badge>}
                      {device.rtsp_enabled && (
                        <Badge variant="purple">RTSP</Badge>
                      )}
                      {device.unlock_enabled && (
                        <Badge variant="green">Unlock</Badge>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    <div className="flex items-center gap-2 justify-end">
                      <Link to={`/devices/${device.id}`}>
                        <Button variant="ghost" size="sm" title="Details">
                          <Eye className="w-4 h-4" />
                        </Button>
                      </Link>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openEdit(device)}
                        title="Edit"
                      >
                        <Pencil className="w-4 h-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDelete(device)}
                        className="text-red-400 hover:text-red-600"
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <DeviceFormModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        device={editDevice}
      />
    </div>
  );
}
