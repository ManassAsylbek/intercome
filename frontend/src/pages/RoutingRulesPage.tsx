import { useState } from "react";
import { useForm, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  useRoutingRules,
  useCreateRule,
  useUpdateRule,
  useDeleteRule,
} from "@/hooks/useRoutingRules";
import { useDevices } from "@/hooks/useDevices";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";
import { Input, Select, Textarea } from "@/components/ui/FormFields";
import { toast } from "@/components/ui/Toast";
import { DEVICE_TYPE_LABELS } from "@/lib/utils";
import type { RoutingRule } from "@/types";
import { Plus, Pencil, Trash2, GitFork } from "lucide-react";

const schema = z.object({
  name: z.string().min(1, "Name is required"),
  call_code: z.string().min(1, "Call code is required"),
  source_device_id: z.coerce.number().nullable().optional(),
  target_device_id: z.coerce.number().nullable().optional(),
  target_sip_account: z.string().nullable().optional(),
  enabled: z.boolean(),
  priority: z.coerce.number().int(),
  notes: z.string().nullable().optional(),
});
type FormData = z.infer<typeof schema>;

function RuleFormModal({
  open,
  onClose,
  rule,
}: {
  open: boolean;
  onClose: () => void;
  rule: RoutingRule | null;
}) {
  const isEdit = !!rule;
  const create = useCreateRule();
  const update = useUpdateRule(rule?.id ?? 0);
  const { data: devicesData } = useDevices();
  const devices = devicesData?.items ?? [];

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    resolver: zodResolver(schema) as any,
    defaultValues: rule
      ? {
          ...rule,
          source_device_id: rule.source_device_id ?? undefined,
          target_device_id: rule.target_device_id ?? undefined,
        }
      : { enabled: true, priority: 0 },
  });

  const onSubmit = async (data: FormData) => {
    try {
      if (isEdit && rule) {
        await update.mutateAsync(data);
        toast("Rule updated", "success");
      } else {
        await create.mutateAsync(
          data as Parameters<typeof create.mutateAsync>[0],
        );
        toast("Rule created", "success");
      }
      reset();
      onClose();
    } catch {
      toast("Failed to save rule", "error");
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={
        isEdit
          ? `Редактировать правило: ${rule?.name}`
          : "Добавить правило маршрутизации"
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <Input
          label="Название правила"
          placeholder="Главная дверь → Гостиная"
          {...register("name")}
          error={errors.name?.message}
        />
        <Input
          label="Код вызова"
          placeholder="101"
          hint="Код набора, который запускает это правило"
          {...register("call_code")}
          error={errors.call_code?.message}
        />

        <Select
          label="Устройство-источник (необязательно)"
          {...register("source_device_id")}
        >
          <option value="">— Любой —</option>
          {devices.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name} ({DEVICE_TYPE_LABELS[d.device_type]})
            </option>
          ))}
        </Select>

        <Select
          label="Целевое устройство (необязательно)"
          {...register("target_device_id")}
        >
          <option value="">— Без целевого устройства —</option>
          {devices.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name} ({DEVICE_TYPE_LABELS[d.device_type]})
            </option>
          ))}
        </Select>

        <Input
          label="Целевой SIP-аккаунт (необязательно)"
          placeholder="sip:home001@192.168.31.132"
          hint="Используется при маршрутизации на SIP URI"
          {...register("target_sip_account")}
        />

        <div className="grid grid-cols-2 gap-4">
          <Input label="Приоритет" type="number" {...register("priority")} />
          <div className="flex flex-col gap-1 justify-end">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                {...register("enabled")}
                className="rounded border-gray-300 text-indigo-600"
              />
              <span className="text-sm text-gray-700">Правило активно</span>
            </label>
          </div>
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
            {isEdit ? "Сохранить" : "Создать правило"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function RoutingRulesPage() {
  const { data, isLoading } = useRoutingRules();
  const deleteRule = useDeleteRule();
  const [modalOpen, setModalOpen] = useState(false);
  const [editRule, setEditRule] = useState<RoutingRule | null>(null);

  const handleDelete = async (rule: RoutingRule) => {
    if (!confirm(`Delete rule "${rule.name}"?`)) return;
    try {
      await deleteRule.mutateAsync(rule.id);
      toast("Rule deleted", "success");
    } catch {
      toast("Failed to delete rule", "error");
    }
  };

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            Правила маршрутизации
          </h1>
          <p className="text-gray-500 text-sm mt-1">
            Привязка кодов вызова к целевым устройствам или SIP-аккаунтам
          </p>
        </div>
        <Button
          onClick={() => {
            setEditRule(null);
            setModalOpen(true);
          }}
        >
          <Plus className="w-4 h-4" /> Добавить правило
        </Button>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-gray-400">Loading…</div>
        ) : !data?.items.length ? (
          <div className="p-12 text-center">
            <GitFork className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-400 mb-4">
              Правила маршрутизации не настроены.
            </p>
            <Button
              size="sm"
              onClick={() => {
                setEditRule(null);
                setModalOpen(true);
              }}
            >
              <Plus className="w-4 h-4" /> Создать первое правило
            </Button>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">
                  Название
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Код вызова
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Источник
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Цель
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Приоритет
                </th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">
                  Статус
                </th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {data.items.map((rule) => (
                <tr key={rule.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <p className="font-medium text-gray-900">{rule.name}</p>
                    {rule.notes && (
                      <p className="text-xs text-gray-400 mt-0.5 truncate max-w-xs">
                        {rule.notes}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-4">
                    <code className="bg-gray-100 text-indigo-700 px-2 py-1 rounded text-xs font-mono">
                      {rule.call_code}
                    </code>
                  </td>
                  <td className="px-4 py-4 text-gray-600 text-xs">
                    {rule.source_device?.name ?? (
                      <span className="text-gray-400">Любой</span>
                    )}
                  </td>
                  <td className="px-4 py-4 text-gray-600 text-xs">
                    {rule.target_device?.name ?? rule.target_sip_account ?? (
                      <span className="text-gray-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-4 text-gray-500 text-xs">
                    {rule.priority}
                  </td>
                  <td className="px-4 py-4">
                    <Badge variant={rule.enabled ? "green" : "gray"}>
                      {rule.enabled ? "Активно" : "Отключено"}
                    </Badge>
                  </td>
                  <td className="px-4 py-4">
                    <div className="flex items-center gap-2 justify-end">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setEditRule(rule);
                          setModalOpen(true);
                        }}
                      >
                        <Pencil className="w-4 h-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-red-400 hover:text-red-600"
                        onClick={() => handleDelete(rule)}
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

      <RuleFormModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        rule={editRule}
      />
    </div>
  );
}
