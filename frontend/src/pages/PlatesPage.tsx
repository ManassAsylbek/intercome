import { usePlates, usePlateLog } from "@/hooks/usePlates";
import { useApartments } from "@/hooks/useApartments";
import { useEntrances } from "@/hooks/useEntrances";
import { Badge } from "@/components/ui/Badge";
import { formatDate } from "@/lib/utils";
import { Car, ScrollText, Smartphone } from "lucide-react";

const ACTION_TAG: Record<string, [string, string]> = {
  opened: ["Открыт", "bg-green-100 text-green-700"],
  denied: ["Отказ", "bg-red-100 text-red-700"],
  open_failed: ["Ошибка открытия", "bg-orange-100 text-orange-700"],
};

function ActionTag({ action }: { action: string }) {
  const [label, cls] = ACTION_TAG[action] ?? [
    action,
    "bg-gray-100 text-gray-600",
  ];
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

export function PlatesPage() {
  const { data, isLoading } = usePlates();
  const { data: logData, isLoading: logLoading } = usePlateLog();
  const { data: apartmentsData } = useApartments();
  const { data: entrances } = useEntrances();

  const apartmentById = new Map(
    (apartmentsData?.items ?? []).map((a) => [a.id, a]),
  );
  const entranceById = new Map((entrances ?? []).map((e) => [e.id, e]));

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Номера авто</h1>
        <p className="text-gray-500 text-sm mt-1">
          Белый список автомобилей для автоматического открытия шлагбаума
        </p>
      </div>

      {/* Cloud-managed banner — list is mirrored from cloud, edits go through the
          mobile app / CRM (see backend/app/api/routes/plates.py for the lock). */}
      <div className="flex items-start gap-3 rounded-xl border border-indigo-100 bg-indigo-50/60 px-4 py-3 text-sm">
        <Smartphone className="w-4 h-4 mt-0.5 text-indigo-500 shrink-0" />
        <div className="text-indigo-900">
          Номерами управляет облако — добавление, редактирование и удаление
          доступны только из мобильного приложения / CRM. На бридже отображается
          актуальная копия списка для контроля.
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-gray-400">Загрузка…</div>
        ) : !data?.items.length ? (
          <div className="p-12 text-center">
            <Car className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-400">
              Список номеров пуст. Добавьте первый номер из мобильного
              приложения.
            </p>
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
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Журнал проездов */}
      <div>
        <h2 className="text-lg font-bold text-gray-900">Журнал проездов</h2>
        <p className="text-gray-500 text-sm mt-1 mb-3">
          Последние распознавания номеров ANPR-камерами
        </p>
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          {logLoading ? (
            <div className="p-8 text-center text-gray-400">Загрузка…</div>
          ) : !logData?.items.length ? (
            <div className="p-10 text-center">
              <ScrollText className="w-9 h-9 text-gray-300 mx-auto mb-2" />
              <p className="text-gray-400">Проездов пока не зафиксировано.</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr>
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">
                    Время
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                    Номер
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                    Распознан
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                    Результат
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {logData.items.map((row) => (
                  <tr key={row.id} className="hover:bg-gray-50">
                    <td className="px-6 py-3 text-gray-500 text-xs whitespace-nowrap">
                      {formatDate(row.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <code className="bg-gray-100 text-indigo-700 px-2 py-1 rounded text-xs font-mono font-semibold">
                        {row.plate}
                      </code>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">
                      {row.matched ? "В списке" : "Не в списке"}
                    </td>
                    <td className="px-4 py-3">
                      <ActionTag action={row.action} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
