import { useState, useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  usePlates,
  useCreatePlate,
  useUpdatePlate,
  useDeletePlate,
} from "@/hooks/usePlates";
import { useApartments } from "@/hooks/useApartments";
import { useEntrances } from "@/hooks/useEntrances";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";
import { Input, Select, Textarea } from "@/components/ui/FormFields";
import { toast } from "@/components/ui/Toast";
import type { Plate } from "@/types";
import { Plus, Pencil, Trash2, Car } from "lucide-react";

// Empty <Select> submits "" — coerce that to null rather than letting
// z.coerce.number() turn it into 0 (no apartment/entrance has id 0, the
// backend would reject it with a FK violation).
const nullableId = z.preprocess(
  (v) => (v === "" || v == null ? null : v),
  z.coerce.number().int().positive().nullable(),
);

const schema = z.object({
  plate: z
    .string()
    .min(1, "Номер обязателен")
    .max(16, "Слишком длинный номер"),
  owner_name: z.string().max(128, "Не более 128 символов").nullable().optional(),
  apartment_id: nullableId,
  entrance_id: nullableId,
  enabled: z.boolean(),
  notes: z.string().max(1000, "Не более 1000 символов").nullable().optional(),
});
type FormData = z.infer<typeof schema>;

function apiErrorDetail(e: unknown): string | undefined {
  return (e as { response?: { data?: { detail?: string } } })?.response?.data
    ?.detail;
}

function PlateFormModal({
  open,
  onClose,
  plate,
}: {
  open: boolean;
  onClose: () => void;
  plate: Plate | null;
}) {
  const isEdit = !!plate;
  const create = useCreatePlate();
  const update = useUpdatePlate(plate?.id ?? 0);
  const { data: apartmentsData } = useApartments();
  const { data: entrances, refetch: refetchEntrances } = useEntrances();
  const apartments = apartmentsData?.items ?? [];

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    resolver: zodResolver(schema) as any,
    mode: "onBlur",
    reValidateMode: "onChange",
    defaultValues: { enabled: true },
  });

  // defaultValues only apply on first mount; the modal stays mounted between
  // opens, so reset explicitly whenever it opens or the edited row changes.
  useEffect(() => {
    if (!open) return;
    refetchEntrances();
    if (plate) {
      reset({
        plate: plate.plate,
        owner_name: plate.owner_name ?? "",
        apartment_id: plate.apartment_id,
        entrance_id: plate.entrance_id,
        enabled: plate.enabled,
        notes: plate.notes ?? "",
      });
    } else {
      reset({
        plate: "",
        owner_name: "",
        apartment_id: null,
        entrance_id: null,
        enabled: true,
        notes: "",
      });
    }
  }, [open, plate, reset, refetchEntrances]);

  const onSubmit = async (data: FormData) => {
    try {
      if (isEdit && plate) {
        await update.mutateAsync(data);
        toast("Номер обновлён", "success");
      } else {
        await create.mutateAsync(
          data as Parameters<typeof create.mutateAsync>[0],
        );
        toast("Номер добавлен", "success");
      }
      onClose();
    } catch (e) {
      toast(apiErrorDetail(e) || "Не удалось сохранить номер", "error");
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={
        isEdit
          ? `Редактировать номер: ${plate?.plate}`
          : "Добавить номер авто"
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <Input
          label="Гос. номер"
          placeholder="01KG123ABC"
          hint="Регистр и пробелы не важны — номер нормализуется автоматически."
          {...register("plate")}
          error={errors.plate?.message}
        />
        <Input
          label="Владелец (необязательно)"
          placeholder="Иванов И.И."
          {...register("owner_name")}
          error={errors.owner_name?.message}
        />

        <Select
          label="Квартира (необязательно)"
          hint="Привязка номера к жильцу"
          {...register("apartment_id")}
        >
          <option value="">— Не привязан —</option>
          {apartments.map((a) => (
            <option key={a.id} value={a.id}>
              Кв. {a.number} (код {a.call_code})
            </option>
          ))}
        </Select>

        <Select
          label="Подъезд / шлагбаум (необязательно)"
          hint="Какому шлагбауму принадлежит разрешение"
          {...register("entrance_id")}
        >
          <option value="">— Любой —</option>
          {(entrances ?? []).map((e) => (
            <option key={e.id} value={e.id}>
              Подъезд {e.number}
              {e.building_address ? ` — ${e.building_address}` : ""}
            </option>
          ))}
        </Select>

        <div className="flex flex-col gap-1 justify-end">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              {...register("enabled")}
              className="rounded border-gray-300 text-indigo-600"
            />
            <span className="text-sm text-gray-700">Номер активен</span>
          </label>
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
            {isEdit ? "Сохранить" : "Добавить номер"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function PlatesPage() {
  const { data, isLoading } = usePlates();
  const { data: apartmentsData } = useApartments();
  const { data: entrances } = useEntrances();
  const deletePlate = useDeletePlate();
  const [modalOpen, setModalOpen] = useState(false);
  const [editPlate, setEditPlate] = useState<Plate | null>(null);

  const apartmentById = new Map(
    (apartmentsData?.items ?? []).map((a) => [a.id, a]),
  );
  const entranceById = new Map((entrances ?? []).map((e) => [e.id, e]));

  const handleDelete = async (plate: Plate) => {
    if (!confirm(`Удалить номер "${plate.plate}" из списка?`)) return;
    try {
      await deletePlate.mutateAsync(plate.id);
      toast("Номер удалён", "success");
    } catch {
      toast("Не удалось удалить номер", "error");
    }
  };

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Номера авто</h1>
          <p className="text-gray-500 text-sm mt-1">
            Белый список автомобилей для автоматического открытия шлагбаума
          </p>
        </div>
        <Button
          onClick={() => {
            setEditPlate(null);
            setModalOpen(true);
          }}
        >
          <Plus className="w-4 h-4" /> Добавить номер
        </Button>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-gray-400">Загрузка…</div>
        ) : !data?.items.length ? (
          <div className="p-12 text-center">
            <Car className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-400 mb-4">Список номеров пуст.</p>
            <Button
              size="sm"
              onClick={() => {
                setEditPlate(null);
                setModalOpen(true);
              }}
            >
              <Plus className="w-4 h-4" /> Добавить первый номер
            </Button>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">
                  Номер
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Владелец
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Квартира
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Подъезд
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Статус
                </th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {data.items.map((plate) => {
                const apt = plate.apartment_id
                  ? apartmentById.get(plate.apartment_id)
                  : null;
                const ent = plate.entrance_id
                  ? entranceById.get(plate.entrance_id)
                  : null;
                return (
                  <tr key={plate.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <code className="bg-gray-100 text-indigo-700 px-2 py-1 rounded text-xs font-mono font-semibold">
                        {plate.plate}
                      </code>
                      {plate.notes && (
                        <p className="text-xs text-gray-400 mt-1 truncate max-w-xs">
                          {plate.notes}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-4 text-gray-600 text-xs">
                      {plate.owner_name ?? (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-4 text-gray-600 text-xs">
                      {apt ? `Кв. ${apt.number}` : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-4 text-gray-600 text-xs">
                      {ent ? `Подъезд ${ent.number}` : (
                        <span className="text-gray-400">Любой</span>
                      )}
                    </td>
                    <td className="px-4 py-4">
                      <Badge variant={plate.enabled ? "green" : "gray"}>
                        {plate.enabled ? "Активен" : "Отключён"}
                      </Badge>
                    </td>
                    <td className="px-4 py-4">
                      <div className="flex items-center gap-2 justify-end">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setEditPlate(plate);
                            setModalOpen(true);
                          }}
                        >
                          <Pencil className="w-4 h-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-red-400 hover:text-red-600"
                          onClick={() => handleDelete(plate)}
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <PlateFormModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        plate={editPlate}
      />
    </div>
  );
}
