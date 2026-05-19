import { useEffect, useState } from "react";
import { useForm, useFieldArray, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  useApartments,
  useCreateApartment,
  useUpdateApartment,
  useDeleteApartment,
} from "@/hooks/useApartments";
import { useEntrances } from "@/hooks/useEntrances";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";
import { Input, Select, Textarea } from "@/components/ui/FormFields";
import { toast } from "@/components/ui/Toast";
import type { Apartment } from "@/types";
import {
  Building2,
  Plus,
  Pencil,
  Trash2,
  Phone,
  X,
  Cloud,
  CloudOff,
  DoorOpen,
} from "lucide-react";
import { DEVICE_TYPE_LABELS } from "@/lib/utils";

const monitorSchema = z.object({
  sip_account: z.string().min(1, "Required"),
  label: z.string().nullable().optional(),
  mac_address: z.string().nullable().optional(),
  model: z.string().nullable().optional(),
  name: z.string().nullable().optional(),
});

const schema = z.object({
  number: z.string().min(1, "Apartment number is required"),
  // call_code это SIP extension — только цифры.
  call_code: z
    .string()
    .min(1, "Код вызова обязателен")
    .max(16, "Слишком длинный код")
    .regex(/^\d+$/, "Только цифры (например 1001)"),
  // Coerce because <select> emits a string.
  entrance_id: z.coerce.number().int().positive("Подъезд обязателен"),
  floor: z.coerce.number().int().optional().nullable(),
  notes: z.string().nullable().optional(),
  enabled: z.boolean(),
  cloud_relay_enabled: z.boolean(),
  cloud_sip_account: z.string().nullable().optional(),
  monitors: z.array(monitorSchema),
});

type FormData = z.infer<typeof schema>;

function ApartmentFormModal({
  open,
  onClose,
  apartment,
}: {
  open: boolean;
  onClose: () => void;
  apartment: Apartment | null;
}) {
  const isEdit = !!apartment;
  const create = useCreateApartment();
  const update = useUpdateApartment(apartment?.id ?? 0);
  const {
    data: entrances,
    isLoading: entrancesLoading,
    refetch: refetchEntrances,
  } = useEntrances();

  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    resolver: zodResolver(schema) as any,
    mode: "onBlur",
    reValidateMode: "onChange",
    defaultValues: apartment
      ? {
          number: apartment.number,
          call_code: apartment.call_code,
          entrance_id: apartment.entrance_id ?? undefined,
          floor: apartment.floor ?? undefined,
          notes: apartment.notes ?? "",
          enabled: apartment.enabled,
          cloud_relay_enabled: apartment.cloud_relay_enabled,
          cloud_sip_account: apartment.cloud_sip_account ?? "",
          monitors: apartment.monitors.map((m) => ({
            sip_account: m.sip_account,
            label: m.label ?? "",
            mac_address: m.mac_address ?? "",
            model: m.model ?? "",
            name: m.name ?? "",
          })),
        }
      : { enabled: true, cloud_relay_enabled: false, monitors: [] },
  });

  const { fields, append, remove } = useFieldArray({
    control,
    name: "monitors",
  });

  // useForm's defaultValues only initialise on first mount. Closing the modal
  // does not remount the form, so stale values persist on the next open.
  // Reset explicitly when the modal opens (or the row being edited changes).
  // Also force-refetch entrances so a freshly created one (pushed by cloud
  // via bootstrap_snapshot) appears in the dropdown without a hard reload.
  useEffect(() => {
    if (!open) return;
    refetchEntrances();
    if (apartment) {
      reset({
        number: apartment.number,
        call_code: apartment.call_code,
        entrance_id: apartment.entrance_id ?? undefined,
        floor: apartment.floor ?? undefined,
        notes: apartment.notes ?? "",
        enabled: apartment.enabled,
        cloud_relay_enabled: apartment.cloud_relay_enabled,
        cloud_sip_account: apartment.cloud_sip_account ?? "",
        monitors: apartment.monitors.map((m) => ({
          sip_account: m.sip_account,
          label: m.label ?? "",
          mac_address: m.mac_address ?? "",
          model: m.model ?? "",
          name: m.name ?? "",
        })),
      });
    } else {
      reset({
        number: "",
        call_code: "",
        entrance_id: undefined,
        floor: undefined,
        notes: "",
        enabled: true,
        cloud_relay_enabled: false,
        cloud_sip_account: "",
        monitors: [],
      });
    }
  }, [open, apartment, reset]);

  const onSubmit: SubmitHandler<FormData> = async (data) => {
    const payload = {
      ...data,
      // Floor may be NaN if user left the input blank — coerce to null.
      floor: data.floor && !Number.isNaN(data.floor) ? data.floor : null,
      monitors: data.monitors.map((m) => ({
        sip_account: m.sip_account,
        label: m.label || null,
        mac_address: m.mac_address || null,
        model: m.model || null,
        name: m.name || null,
      })),
    };
    try {
      if (isEdit && apartment) {
        await update.mutateAsync(payload);
        toast("Apartment updated", "success");
      } else {
        await create.mutateAsync(payload);
        toast("Apartment created", "success");
      }
      reset();
      onClose();
    } catch {
      toast("Failed to save apartment", "error");
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={
        isEdit
          ? `Редактировать квартиру ${apartment?.number}`
          : "Добавить квартиру"
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <Input
            label="Номер квартиры"
            placeholder="101"
            hint="Отображаемое название (напр. 101, 2Б)"
            {...register("number")}
            error={errors.number?.message}
          />
          <Input
            label="Код вызова"
            placeholder="1001"
            hint="Только цифры. SIP-номер, набираемый с панели домофона."
            inputMode="numeric"
            pattern="[0-9]*"
            {...register("call_code")}
            error={errors.call_code?.message}
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <Select
            label="Подъезд"
            hint={
              entrancesLoading
                ? "Загрузка списка подъездов…"
                : entrances && entrances.length === 0
                  ? "Подъезды появятся после первого подключения к облаку"
                  : "Список приходит из облака (bootstrap_snapshot)"
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
          <Input
            label="Этаж"
            placeholder="3"
            hint="Опционально"
            type="number"
            {...register("floor")}
            error={errors.floor?.message}
          />
        </div>

        {/* Monitors */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium text-gray-700">
              Мониторы / Трубки
            </label>
            <button
              type="button"
              onClick={() =>
                append({
                  sip_account: "",
                  label: "",
                  mac_address: "",
                  model: "",
                  name: "",
                })
              }
              className="flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 font-medium"
            >
              <Plus className="w-3.5 h-3.5" /> Добавить монитор
            </button>
          </div>

          {fields.length === 0 && (
            <p className="text-xs text-gray-400 bg-gray-50 rounded-lg p-3 text-center">
              Нет мониторов — звонок придёт только в браузер
            </p>
          )}

          <div className="space-y-3">
            {fields.map((field, idx) => (
              <div
                key={field.id}
                className="rounded-lg border border-gray-200 p-3 space-y-2 bg-gray-50/50"
              >
                <div className="flex items-start justify-between">
                  <span className="text-xs text-gray-500">
                    Монитор #{idx + 1}
                  </span>
                  <button
                    type="button"
                    onClick={() => remove(idx)}
                    className="p-1 text-gray-400 hover:text-red-500 flex-shrink-0"
                    title="Удалить монитор"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Input
                    placeholder="SIP-аккаунт (напр. 1001)"
                    {...register(`monitors.${idx}.sip_account`)}
                    error={errors.monitors?.[idx]?.sip_account?.message}
                  />
                  <Input
                    placeholder="MAC-адрес (для cloud upsert)"
                    {...register(`monitors.${idx}.mac_address`)}
                  />
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <Input
                    placeholder="Имя (напр. Гостиная)"
                    {...register(`monitors.${idx}.name`)}
                  />
                  <Input
                    placeholder="Модель"
                    {...register(`monitors.${idx}.model`)}
                  />
                  <Input
                    placeholder="Метка (label)"
                    {...register(`monitors.${idx}.label`)}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              {...register("enabled")}
              className="rounded border-gray-300 text-indigo-600"
            />
            <span className="text-sm text-gray-700">Активна</span>
          </label>
        </div>

        {/* Cloud relay */}
        <div className="rounded-lg border border-blue-100 bg-blue-50 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <Cloud className="w-4 h-4 text-blue-500" />
            <span className="text-sm font-medium text-blue-800">
              Облачная переадресация
            </span>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              {...register("cloud_relay_enabled")}
              className="rounded border-gray-300 text-blue-600"
            />
            <span className="text-sm text-gray-700">
              Пересылать звонок в облако → мобильным пользователям
            </span>
          </label>
          <Input
            label="SIP-аккаунт на облачном транке"
            placeholder="42 (по умолчанию = код вызова)"
            hint="Оставьте пустым — будет использован код вызова квартиры"
            {...register("cloud_sip_account")}
          />
        </div>

        <Textarea
          label="Примечания"
          placeholder="Необязательное описание…"
          {...register("notes")}
        />

        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" loading={isSubmitting}>
            {isEdit ? "Сохранить" : "Создать квартиру"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function ApartmentsPage() {
  const { data, isLoading } = useApartments();
  const deleteApartment = useDeleteApartment();
  const [modalOpen, setModalOpen] = useState(false);
  const [editApartment, setEditApartment] = useState<Apartment | null>(null);

  const handleDelete = async (apt: Apartment) => {
    if (!confirm(`Delete apartment ${apt.number}?`)) return;
    try {
      await deleteApartment.mutateAsync(apt.id);
      toast("Apartment deleted", "success");
    } catch {
      toast("Failed to delete", "error");
    }
  };

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Квартиры</h1>
          <p className="text-gray-500 text-sm mt-1">
            У каждой квартиры есть код вызова и список мониторов, которые звонят
            одновременно
          </p>
        </div>
        <Button
          onClick={() => {
            setEditApartment(null);
            setModalOpen(true);
          }}
        >
          <Plus className="w-4 h-4" /> Добавить квартиру
        </Button>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-gray-400">Loading…</div>
        ) : !data?.items.length ? (
          <div className="p-12 text-center">
            <Building2 className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-400 mb-4">Квартиры не настроены.</p>
            <Button
              size="sm"
              onClick={() => {
                setEditApartment(null);
                setModalOpen(true);
              }}
            >
              <Plus className="w-4 h-4" /> Добавить первую квартиру
            </Button>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">
                  Квартира
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Код вызова
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Источники
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Мониторы
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Облако
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Cloud sync
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Статус
                </th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {data.items.map((apt) => (
                <tr key={apt.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 bg-indigo-100 rounded-lg flex items-center justify-center flex-shrink-0">
                        <Building2 className="w-4 h-4 text-indigo-600" />
                      </div>
                      <div>
                        <p className="font-semibold text-gray-900">
                          кв. {apt.number}
                        </p>
                        {apt.notes && (
                          <p className="text-xs text-gray-400">{apt.notes}</p>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-4">
                    <span className="inline-flex items-center gap-1 px-2 py-1 bg-gray-100 rounded text-xs font-mono font-medium text-gray-700">
                      <Phone className="w-3 h-3" />
                      {apt.call_code}
                    </span>
                  </td>
                  <td className="px-4 py-4">
                    {apt.source_devices.length === 0 ? (
                      <span className="text-xs text-gray-400">—</span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {apt.source_devices.map((d) => (
                          <span
                            key={d.id}
                            title={DEVICE_TYPE_LABELS[d.device_type]}
                            className="inline-flex items-center gap-1 px-2 py-0.5 bg-orange-50 text-orange-700 rounded text-xs"
                          >
                            <DoorOpen className="w-3 h-3" />
                            {d.name}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-4">
                    {apt.monitors.length === 0 ? (
                      <span className="text-xs text-gray-400">
                        Только браузер
                      </span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {apt.monitors.map((m) => (
                          <span
                            key={m.id}
                            className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-xs font-mono"
                            title={m.label ?? undefined}
                          >
                            {m.sip_account}
                            {m.label && (
                              <span className="text-blue-400 font-sans font-normal">
                                · {m.label}
                              </span>
                            )}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-4">
                    {apt.cloud_relay_enabled ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-xs">
                        <Cloud className="w-3 h-3" />{" "}
                        {apt.cloud_sip_account || apt.call_code}
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">Отключено</span>
                    )}
                  </td>
                  <td className="px-4 py-4">
                    {apt.cloud_synced ? (
                      <span
                        title={`cloud_id=${apt.cloud_id ?? "—"}`}
                        className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-50 text-green-700 rounded text-xs"
                      >
                        <Cloud className="w-3 h-3" /> synced
                      </span>
                    ) : (
                      <span
                        title={
                          apt.last_cloud_sync_error ??
                          "ожидает sync — нет entrance_id или нет связи с облаком"
                        }
                        className="inline-flex items-center gap-1 px-2 py-0.5 bg-red-50 text-red-700 rounded text-xs"
                      >
                        <CloudOff className="w-3 h-3" /> pending
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-4">
                    <Badge variant={apt.enabled ? "green" : "gray"}>
                      {apt.enabled ? "Активна" : "Отключена"}
                    </Badge>
                  </td>
                  <td className="px-4 py-4 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => {
                          setEditApartment(apt);
                          setModalOpen(true);
                        }}
                        className="p-1.5 text-gray-400 hover:text-indigo-600 rounded-md hover:bg-indigo-50"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDelete(apt)}
                        className="p-1.5 text-gray-400 hover:text-red-600 rounded-md hover:bg-red-50"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <ApartmentFormModal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          setEditApartment(null);
        }}
        apartment={editApartment}
      />
    </div>
  );
}
