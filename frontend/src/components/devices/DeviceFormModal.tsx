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
import { useEntrances } from "@/hooks/useEntrances";
import { toast } from "@/components/ui/Toast";
import { devicesApi } from "@/api";
import type { Device } from "@/types";

// ─── Validation helpers ──────────────────────────────────────────────────────

const opt = (s: string | null | undefined) =>
  s == null || s === "" ? undefined : s;

const IPV4_RE =
  /^((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$/;
const MAC_RE = /^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$/;
const SIP_USER_RE = /^[A-Za-z0-9._-]{1,128}$/;
const HOST_RE = /^[A-Za-z0-9.\-_]{1,255}$/;

const optionalIp = z
  .string()
  .optional()
  .nullable()
  .transform(opt)
  .refine((v) => v === undefined || IPV4_RE.test(v), {
    message: "Введите корректный IPv4 (например 192.168.1.42)",
  });

const optionalPort = z
  .preprocess(
    (v) => (v === "" || v === null || v === undefined ? undefined : Number(v)),
    z
      .number({ message: "Только целое число" })
      .int("Только целое число")
      .min(1, "Порт от 1 до 65535")
      .max(65535, "Порт от 1 до 65535"),
  )
  .optional();

const optionalMac = z
  .string()
  .optional()
  .nullable()
  .transform(opt)
  .refine((v) => v === undefined || MAC_RE.test(v), {
    message: "Формат MAC: AA:BB:CC:DD:EE:FF (шесть пар HEX через :)",
  });

const optionalProtoUrl = (proto: "http" | "rtsp") =>
  z
    .string()
    .optional()
    .nullable()
    .transform(opt)
    .refine(
      (v) => {
        if (v === undefined) return true;
        try {
          const u = new URL(v);
          if (proto === "rtsp") return u.protocol === "rtsp:";
          return u.protocol === "http:" || u.protocol === "https:";
        } catch {
          return false;
        }
      },
      {
        message:
          proto === "rtsp"
            ? "URL должен начинаться с rtsp:// (rtsp://user:pass@host:554/h264)"
            : "URL должен начинаться с http:// или https://",
      },
    );

const schema = z
  .object({
    name: z
      .string()
      .min(1, "Название обязательно")
      .max(128, "Не более 128 символов"),
    device_type: z.enum([
      "door_station",
      "home_station",
      "guard_station",
      "sip_client",
      "camera",
    ]),
    ip_address: optionalIp,
    web_port: optionalPort,
    enabled: z.boolean(),
    notes: z
      .string()
      .max(1000, "Не более 1000 символов")
      .nullable()
      .optional(),
    // Cloud mirror — backend requires entrance_id on POST /api/devices.
    entrance_id: z.coerce.number().int().positive("Подъезд обязателен"),
    mac_address: optionalMac,
    model: z
      .string()
      .max(128, "Не более 128 символов")
      .nullable()
      .optional(),
    // SIP
    sip_enabled: z.boolean(),
    sip_account: z
      .string()
      .optional()
      .nullable()
      .transform(opt)
      .refine((v) => v === undefined || SIP_USER_RE.test(v), {
        message:
          "Только буквы, цифры, . _ - (1–128 символов). Пример: 1001 или mobile-john",
      }),
    sip_password: z
      .string()
      .optional()
      .nullable()
      .transform(opt)
      .refine((v) => v === undefined || (v.length >= 6 && v.length <= 128), {
        message: "От 6 до 128 символов",
      }),
    sip_server: z
      .string()
      .optional()
      .nullable()
      .transform(opt)
      .refine((v) => v === undefined || HOST_RE.test(v), {
        message: "Хост или IP без пробелов",
      }),
    sip_port: optionalPort,
    sip_proxy: z
      .string()
      .optional()
      .nullable()
      .transform(opt)
      .refine((v) => v === undefined || HOST_RE.test(v), {
        message: "Хост или IP",
      }),
    // RTSP
    rtsp_enabled: z.boolean(),
    rtsp_url: optionalProtoUrl("rtsp"),
    // Unlock
    unlock_enabled: z.boolean(),
    unlock_method: z.enum(["http_get", "http_post", "sip_dtmf", "none"]),
    unlock_url: optionalProtoUrl("http"),
    unlock_username: z
      .string()
      .max(128, "Не более 128 символов")
      .nullable()
      .optional(),
    unlock_password: z
      .string()
      .max(128, "Не более 128 символов")
      .nullable()
      .optional(),
    apartment_id: z.coerce.number().nullable().optional(),
  })
  // ── Cross-field requirements: required-when-enabled ──────────────────────
  .superRefine((data, ctx) => {
    if (data.sip_enabled) {
      if (!data.sip_account) {
        ctx.addIssue({
          path: ["sip_account"],
          code: z.ZodIssueCode.custom,
          message: "Обязательно при включённом SIP",
        });
      }
      if (!data.sip_password) {
        ctx.addIssue({
          path: ["sip_password"],
          code: z.ZodIssueCode.custom,
          message: "Обязательно при включённом SIP",
        });
      }
    }
    if (data.rtsp_enabled && !data.rtsp_url) {
      ctx.addIssue({
        path: ["rtsp_url"],
        code: z.ZodIssueCode.custom,
        message: "Обязательно при включённом RTSP",
      });
    }
    if (data.unlock_enabled) {
      const httpMethod =
        data.unlock_method === "http_get" || data.unlock_method === "http_post";
      if (httpMethod && !data.unlock_url) {
        ctx.addIssue({
          path: ["unlock_url"],
          code: z.ZodIssueCode.custom,
          message: "URL обязателен для HTTP-метода",
        });
      }
      if (data.unlock_method === "none") {
        ctx.addIssue({
          path: ["unlock_method"],
          code: z.ZodIssueCode.custom,
          message: "Выберите метод (HTTP GET/POST или SIP DTMF)",
        });
      }
    }
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
  const {
    data: entrances,
    isLoading: entrancesLoading,
    refetch: refetchEntrances,
  } = useEntrances();
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
    // Show validation errors as soon as a field loses focus, and re-validate
    // on every change once an error has been surfaced. Default ("onSubmit")
    // hides issues until the user clicks Save, which feels broken on a long
    // form like this one — admin enters bad data, clicks elsewhere, sees no
    // feedback, then is surprised by a wall of errors at submit.
    mode: "onBlur",
    reValidateMode: "onChange",
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
    if (!open) return;
    // Pull a fresh entrances list so a newly created one shows up in the
    // dropdown without requiring a hard page reload.
    refetchEntrances();
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
  }, [device, reset, open, refetchEntrances]);

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
    } catch (err: unknown) {
      // Surface the actual backend reason instead of a generic message.
      // Pydantic 422 returns {detail: [{loc, msg, type}, ...]}; HTTPException
      // returns {detail: "string"}. Axios wraps both into err.response.data.
      type ApiErr = {
        response?: {
          data?: {
            detail?:
              | string
              | { loc?: (string | number)[]; msg?: string }[];
          };
        };
        message?: string;
      };
      const e = err as ApiErr;
      const detail = e.response?.data?.detail;
      let msg = "Не удалось сохранить устройство";
      if (typeof detail === "string") {
        msg = detail;
      } else if (Array.isArray(detail) && detail.length) {
        msg = detail
          .map((d) => {
            const field = Array.isArray(d.loc)
              ? d.loc.filter((p) => p !== "body").join(".")
              : "";
            return field ? `${field}: ${d.msg}` : d.msg ?? "";
          })
          .filter(Boolean)
          .join("; ");
      } else if (e.message) {
        msg = e.message;
      }
      toast(msg, "error");
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
              {/* <option value="guard_station">Пост охраны</option>
              <option value="sip_client">SIP-клиент</option>
              <option value="camera">Камера</option> */}
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
                label="Подъезд"
                hint={
                  entrancesLoading
                    ? "Загрузка списка подъездов…"
                    : entrances && entrances.length === 0
                      ? "Подъезды появятся после подключения к облаку"
                      : "Список приходит из облака (bootstrap_snapshot). Обязательное поле."
                }
                {...register("entrance_id")}
                error={errors.entrance_id?.message}
              >
                <option value="">— выберите подъезд —</option>
                {entrances?.map((e) => (
                  <option key={e.id} value={e.id}>
                    Подъезд {e.number}
                    {e.building_address ? ` · ${e.building_address}` : ""}
                  </option>
                ))}
              </Select>
            </div>
            <Input
              label="MAC-адрес"
              placeholder="AA:BB:CC:DD:EE:FF"
              hint="Используется как natural key при синхронизации с облаком"
              {...register("mac_address")}
              error={errors.mac_address?.message}
            />
            <Input
              label="Модель"
              placeholder="Hikvision DS-KD8003"
              {...register("model")}
              error={errors.model?.message}
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
                error={errors.notes?.message}
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
                error={errors.sip_account?.message}
              />
              <PasswordInput
                label="SIP-пароль"
                placeholder="••••••"
                {...register("sip_password")}
                error={errors.sip_password?.message}
              />
              <Input
                label="SIP-сервер"
                placeholder="192.168.50.132"
                {...register("sip_server")}
                error={errors.sip_server?.message}
              />
              <Input
                label="SIP-порт"
                type="number"
                placeholder="5060"
                {...register("sip_port")}
                error={errors.sip_port?.message}
              />
              <div className="col-span-2">
                <Input
                  label="SIP-прокси"
                  placeholder="Необязательно"
                  {...register("sip_proxy")}
                  error={errors.sip_proxy?.message}
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
              error={errors.rtsp_url?.message}
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
              <Select
                label="Метод открытия"
                {...register("unlock_method")}
                error={errors.unlock_method?.message}
              >
                <option value="http_get">HTTP GET</option>
                <option value="http_post">HTTP POST</option>
                <option value="sip_dtmf">SIP DTMF</option>
                <option value="none">Нет</option>
              </Select>
              <Input
                label="URL открытия"
                placeholder="http://192.168.31.31:8000/unlock"
                {...register("unlock_url")}
                error={errors.unlock_url?.message}
              />
              <Input
                label="Пользователь"
                placeholder="admin"
                {...register("unlock_username")}
                error={errors.unlock_username?.message}
              />
              <PasswordInput
                label="Пароль"
                placeholder="123456"
                {...register("unlock_password")}
                error={errors.unlock_password?.message}
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
