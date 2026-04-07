import { useEffect } from "react";
import { useForm, Controller, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Input, Select, Textarea, Checkbox } from "@/components/ui/FormFields";
import { useCreateDevice, useUpdateDevice } from "@/hooks/useDevices";
import { toast } from "@/components/ui/Toast";
import type { Device } from "@/types";

const schema = z.object({
  name: z.string().min(1, "Name is required"),
  device_type: z.enum([
    "door_station",
    "home_station",
    "guard_station",
    "sip_client",
    "camera",
  ]),
  ip_address: z.string().nullable().optional(),
  web_port: z.coerce.number().int().min(1).max(65535).nullable().optional(),
  enabled: z.boolean(),
  notes: z.string().nullable().optional(),
  // SIP
  sip_enabled: z.boolean(),

  sip_account: z.string().nullable().optional(),
  sip_password: z.string().nullable().optional(),
  sip_server: z.string().nullable().optional(),
  sip_port: z.coerce.number().int().min(1).max(65535).nullable().optional(),
  sip_proxy: z.string().nullable().optional(),
  // RTSP
  rtsp_enabled: z.boolean(),
  rtsp_url: z.string().nullable().optional(),
  // Unlock
  unlock_enabled: z.boolean(),
  unlock_method: z.enum(["http_get", "http_post", "sip_dtmf", "none"]),

  unlock_url: z.string().nullable().optional(),
  unlock_username: z.string().nullable().optional(),
  unlock_password: z.string().nullable().optional(),
});

type FormData = z.infer<typeof schema>;

interface Props {
  open: boolean;
  onClose: () => void;
  device: Device | null;
}

export function DeviceFormModal({ open, onClose, device }: Props) {
  const isEdit = !!device;
  const create = useCreateDevice();
  const update = useUpdateDevice(device?.id ?? 0);

  const {
    register,
    handleSubmit,
    control,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    resolver: zodResolver(schema) as any,
    defaultValues: {
      device_type: "door_station",
      enabled: true,
      sip_enabled: false,
      rtsp_enabled: false,
      unlock_enabled: false,
      unlock_method: "none",
    },
  });

  const sipEnabled = watch("sip_enabled");
  const rtspEnabled = watch("rtsp_enabled");
  const unlockEnabled = watch("unlock_enabled");

  useEffect(() => {
    if (device) {
      reset({
        ...device,
        web_port: device.web_port ?? undefined,
        sip_port: device.sip_port ?? undefined,
      } as FormData);
    } else {
      reset({
        device_type: "door_station",
        enabled: true,
        sip_enabled: false,
        rtsp_enabled: false,
        unlock_enabled: false,
        unlock_method: "none",
      });
    }
  }, [device, reset, open]);

  const onSubmit = async (data: FormData) => {
    try {
      if (isEdit && device) {
        await update.mutateAsync(data);
        toast("Device updated", "success");
      } else {
        await create.mutateAsync(
          data as Parameters<typeof create.mutateAsync>[0],
        );
        toast("Device created", "success");
      }
      onClose();
    } catch {
      toast("Failed to save device", "error");
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? `Edit: ${device?.name}` : "Add New Device"}
      size="xl"
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        {/* Basic Info */}
        <section>
          <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">
            Basic Information
          </h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <Input
                label="Device Name"
                {...register("name")}
                error={errors.name?.message}
              />
            </div>
            <Select
              label="Device Type"
              {...register("device_type")}
              error={errors.device_type?.message}
            >
              <option value="door_station">Door Station</option>
              <option value="home_station">Home Station</option>
              <option value="guard_station">Guard Station</option>
              <option value="sip_client">SIP Client</option>
              <option value="camera">Camera</option>
            </Select>
            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-gray-700">
                Enabled
              </label>
              <div className="flex items-center h-9">
                <Controller
                  control={control}
                  name="enabled"
                  render={({ field }) => (
                    <Checkbox
                      label="Device is active"
                      {...field}
                      checked={field.value}
                    />
                  )}
                />
              </div>
            </div>
            <Input
              label="IP Address"
              placeholder="192.168.31.31"
              {...register("ip_address")}
              error={errors.ip_address?.message}
            />
            <Input
              label="Web Port"
              type="number"
              placeholder="8000"
              {...register("web_port")}
              error={errors.web_port?.message}
            />
            <div className="col-span-2">
              <Textarea
                label="Notes"
                placeholder="Optional notes…"
                {...register("notes")}
              />
            </div>
          </div>
        </section>

        <hr className="border-gray-100" />

        {/* SIP */}
        <section>
          <div className="flex items-center gap-3 mb-3">
            <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
              SIP Configuration
            </h3>
            <Controller
              control={control}
              name="sip_enabled"
              render={({ field }) => (
                <Checkbox label="Enable SIP" {...field} checked={field.value} />
              )}
            />
          </div>
          {sipEnabled && (
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="SIP Account"
                placeholder="door001"
                {...register("sip_account")}
              />
              <Input
                label="SIP Password"
                type="password"
                placeholder="••••••"
                {...register("sip_password")}
              />
              <Input
                label="SIP Server"
                placeholder="192.168.31.132"
                {...register("sip_server")}
              />
              <Input
                label="SIP Port"
                type="number"
                placeholder="5060"
                {...register("sip_port")}
              />
              <div className="col-span-2">
                <Input
                  label="SIP Proxy"
                  placeholder="Optional proxy"
                  {...register("sip_proxy")}
                />
              </div>
            </div>
          )}
        </section>

        <hr className="border-gray-100" />

        {/* RTSP */}
        <section>
          <div className="flex items-center gap-3 mb-3">
            <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
              RTSP Stream
            </h3>
            <Controller
              control={control}
              name="rtsp_enabled"
              render={({ field }) => (
                <Checkbox
                  label="Enable RTSP"
                  {...field}
                  checked={field.value}
                />
              )}
            />
          </div>
          {rtspEnabled && (
            <Input
              label="RTSP URL"
              placeholder="rtsp://admin:password@192.168.31.31:554/h264"
              {...register("rtsp_url")}
            />
          )}
        </section>

        <hr className="border-gray-100" />

        {/* Unlock */}
        <section>
          <div className="flex items-center gap-3 mb-3">
            <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
              Door Unlock
            </h3>
            <Controller
              control={control}
              name="unlock_enabled"
              render={({ field }) => (
                <Checkbox
                  label="Enable Unlock"
                  {...field}
                  checked={field.value}
                />
              )}
            />
          </div>
          {unlockEnabled && (
            <div className="grid grid-cols-2 gap-4">
              <Select label="Unlock Method" {...register("unlock_method")}>
                <option value="http_get">HTTP GET</option>
                <option value="http_post">HTTP POST</option>
                <option value="sip_dtmf">SIP DTMF</option>
                <option value="none">None</option>
              </Select>
              <Input
                label="Unlock URL"
                placeholder="http://192.168.31.31:8000/unlock"
                {...register("unlock_url")}
              />
              <Input
                label="Username"
                placeholder="admin"
                {...register("unlock_username")}
              />
              <Input
                label="Password"
                type="password"
                placeholder="123456"
                {...register("unlock_password")}
              />
            </div>
          )}
        </section>

        {/* Actions */}
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={isSubmitting}>
            {isEdit ? "Save Changes" : "Create Device"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
