import { useEffect, useState } from "react";
import { useForm, Controller, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import {
  Input,
  Select,
  Textarea,
  Checkbox,
  PasswordInput,
} from "@/components/ui/FormFields";
import { useCreateDevice, useUpdateDevice } from "@/hooks/useDevices";
import { useApartments } from "@/hooks/useApartments";
import { toast } from "@/components/ui/Toast";
import { devicesApi } from "@/api";
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
  apartment_id: z.coerce.number().nullable().optional(),
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
  const { data: apartmentsData } = useApartments();
  const apartments = apartmentsData?.items ?? [];
  const [sipApplying, setSipApplying] = useState(false);
  const [sipApplyResult, setSipApplyResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

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
      let savedId: number | undefined;
      if (isEdit && device) {
        await update.mutateAsync(data);
        savedId = device.id;
        toast("Device updated", "success");
      } else {
        const created = await create.mutateAsync(
          data as Parameters<typeof create.mutateAsync>[0],
        );
        savedId = created.id;
        toast("Device created", "success");
      }

      // Auto-apply SIP to Asterisk if SIP is enabled and credentials are filled
      if (
        data.sip_enabled &&
        data.sip_account &&
        data.sip_password &&
        savedId
      ) {
        setSipApplying(true);
        try {
          const result = await devicesApi.sipApply(savedId, {
            sip_account: data.sip_account,
            sip_password: data.sip_password,
            update_device: false,
          });
          if (result.success) {
            toast("SIP применён в Asterisk ✓", "success");
          } else {
            toast(`SIP: ${result.message}`, "error");
          }
        } catch {
          toast("Не удалось применить SIP в Asterisk", "error");
        } finally {
          setSipApplying(false);
        }
      }

      onClose();
    } catch {
      toast("Failed to save device", "error");
    }
  };

  const handleSipApply = async () => {
    if (!device?.id) return;
    const account = watch("sip_account");
    const password = watch("sip_password");
    if (!account || !password) {
      toast("Fill in SIP Account and Password first", "error");
      return;
    }
    setSipApplying(true);
    setSipApplyResult(null);
    try {
      const result = await devicesApi.sipApply(device.id, {
        sip_account: account,
        sip_password: password,
        update_device: true,
      });
      setSipApplyResult(result);
      if (result.success) {
        toast("Applied to Asterisk ✓", "success");
      } else {
        toast(result.message, "error");
      }
    } catch {
      setSipApplyResult({ success: false, message: "Network error" });
      toast("Failed to apply SIP credentials", "error");
    } finally {
      setSipApplying(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? `Редактировать: ${device?.name}` : "Добавить устройство"}
      size="xl"
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
        {/* Basic Info */}
        <section>
          <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">
            Основная информация
          </h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <Input
                label="Название устройства"
                {...register("name")}
                error={errors.name?.message}
              />
            </div>
            <Select
              label="Тип устройства"
              {...register("device_type")}
              error={errors.device_type?.message}
            >
              <option value="door_station">Панель домофона</option>
              <option value="home_station">Домашний монитор</option>
              <option value="guard_station">Пост охраны</option>
              <option value="sip_client">SIP-клиент</option>
              <option value="camera">Камера</option>
            </Select>
            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-gray-700">
                Активно
              </label>
              <div className="flex items-center h-9">
                <Controller
                  control={control}
                  name="enabled"
                  render={({ field }) => (
                    <Checkbox
                      label="Устройство активно"
                      {...field}
                      checked={field.value}
                    />
                  )}
                />
              </div>
            </div>
            <Input
              label="IP-адрес"
              placeholder="192.168.31.31"
              {...register("ip_address")}
              error={errors.ip_address?.message}
            />
            <Input
              label="Веб-порт"
              type="number"
              placeholder="8000"
              {...register("web_port")}
              error={errors.web_port?.message}
            />
            <div className="col-span-2">
              <Select
                label="Квартира (источник вызова)"
                hint="Для дверей/калиток/шлагбаумов — к какой квартире привязано устройство"
                {...register("apartment_id")}
              >
                <option value="">— Не привязано —</option>
                {apartments.map((apt) => (
                  <option key={apt.id} value={apt.id}>
                    кв. {apt.number} (код {apt.call_code})
                  </option>
                ))}
              </Select>
            </div>
            <div className="col-span-2">
              <Textarea
                label="Примечания"
                placeholder="Необязательно…"
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
              SIP-конфигурация
            </h3>
            <Controller
              control={control}
              name="sip_enabled"
              render={({ field }) => (
                <Checkbox
                  label="Включить SIP"
                  {...field}
                  checked={field.value}
                />
              )}
            />
          </div>
          {sipEnabled && (
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="SIP-аккаунт"
                placeholder="1001"
                {...register("sip_account")}
              />
              <PasswordInput
                label="SIP-пароль"
                placeholder="••••••"
                {...register("sip_password")}
              />
              <Input
                label="SIP-сервер"
                placeholder="192.168.50.132"
                {...register("sip_server")}
              />
              <Input
                label="SIP-порт"
                type="number"
                placeholder="5060"
                {...register("sip_port")}
              />
              <div className="col-span-2">
                <Input
                  label="SIP-прокси"
                  placeholder="Необязательно"
                  {...register("sip_proxy")}
                />
              </div>
              {isEdit && (
                <div className="col-span-2 pt-1">
                  <div className="flex items-center gap-3">
                    <Button
                      type="button"
                      variant="secondary"
                      loading={sipApplying}
                      onClick={handleSipApply}
                    >
                      Применить в Asterisk (pjsip.conf)
                    </Button>
                    {sipApplyResult && (
                      <span
                        className={`text-xs font-medium px-2 py-1 rounded-md ${
                          sipApplyResult.success
                            ? "bg-green-50 text-green-700"
                            : "bg-red-50 text-red-600"
                        }`}
                      >
                        {sipApplyResult.success ? "✓ " : "✗ "}
                        {sipApplyResult.message}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400 mt-1">
                    Записывает аккаунт в pjsip.conf на сервере Asterisk и
                    перезагружает его. Режим настраивается в backend/.env
                    (ASTERISK_MODE=local|ssh).
                  </p>
                </div>
              )}
            </div>
          )}
        </section>

        <hr className="border-gray-100" />

        {/* RTSP */}
        <section>
          <div className="flex items-center gap-3 mb-3">
            <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
              RTSP-поток
            </h3>
            <Controller
              control={control}
              name="rtsp_enabled"
              render={({ field }) => (
                <Checkbox
                  label="Включить RTSP"
                  {...field}
                  checked={field.value}
                />
              )}
            />
          </div>
          {rtspEnabled && (
            <Input
              label="RTSP адрес"
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
              Открытие двери
            </h3>
            <Controller
              control={control}
              name="unlock_enabled"
              render={({ field }) => (
                <Checkbox
                  label="Включить открытие"
                  {...field}
                  checked={field.value}
                />
              )}
            />
          </div>
          {unlockEnabled && (
            <div className="grid grid-cols-2 gap-4">
              <Select label="Метод открытия" {...register("unlock_method")}>
                <option value="http_get">HTTP GET</option>
                <option value="http_post">HTTP POST</option>
                <option value="sip_dtmf">SIP DTMF</option>
                <option value="none">Нет</option>
              </Select>
              <Input
                label="URL открытия"
                placeholder="http://192.168.31.31:8000/unlock"
                {...register("unlock_url")}
              />
              <Input
                label="Пользователь"
                placeholder="admin"
                {...register("unlock_username")}
              />
              <PasswordInput
                label="Пароль"
                placeholder="123456"
                {...register("unlock_password")}
              />
            </div>
          )}
        </section>

        {/* Actions */}
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" loading={isSubmitting}>
            {isEdit ? "Сохранить" : "Создать устройство"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
