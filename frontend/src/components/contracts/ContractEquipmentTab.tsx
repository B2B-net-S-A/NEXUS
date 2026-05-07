"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  contractEquipmentApi,
  type ContractEquipmentItem,
  type EquipmentItemType,
  type EquipmentOwner,
  type EquipmentReturnStatus,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { Laptop, Plus, Trash2, Check, AlertTriangle } from "lucide-react";

interface Props {
  contractId: number;
}

const ITEM_TYPE_LABELS: Record<EquipmentItemType, string> = {
  laptop: "Laptop",
  phone: "Telefon",
  monitor: "Monitor",
  headset: "Słuchawki",
  docking_station: "Docking station",
  security_token: "Token",
  keycard: "Karta dostępu",
  sim_card: "Karta SIM",
  other: "Inne",
};

const OWNER_LABELS: Record<EquipmentOwner, string> = {
  ours: "Nasze",
  client: "Klienta",
};

const STATUS_STYLES: Record<EquipmentReturnStatus, string> = {
  pending: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  returned: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  lost: "bg-destructive/15 text-red-800 dark:bg-red-900 dark:text-red-200",
  written_off:
    "bg-muted text-foreground dark:bg-muted dark:text-muted-foreground",
};

const STATUS_LABELS: Record<EquipmentReturnStatus, string> = {
  pending: "Oczekuje",
  returned: "Zwrócony",
  lost: "Zgubiony",
  written_off: "Spisany",
};

function isOverdue(item: ContractEquipmentItem): boolean {
  if (item.return_status !== "pending" || !item.return_due_date) return false;
  return new Date(item.return_due_date) < new Date();
}

export function ContractEquipmentTab({ contractId }: Props) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);

  const { data: items = [], isLoading } = useQuery({
    queryKey: ["contract-equipment", contractId],
    queryFn: async () => {
      const res = await contractEquipmentApi.list(contractId);
      return res.data as ContractEquipmentItem[];
    },
  });

  const createMut = useMutation({
    mutationFn: (payload: Partial<ContractEquipmentItem>) =>
      contractEquipmentApi.create(contractId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["contract-equipment", contractId] });
      setAdding(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: number;
      payload: Partial<ContractEquipmentItem>;
    }) => contractEquipmentApi.update(contractId, id, payload),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["contract-equipment", contractId] }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => contractEquipmentApi.delete(contractId, id),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["contract-equipment", contractId] }),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground dark:text-foreground">
          Sprzęt kontraktora ({items.length})
        </h3>
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary hover:bg-primary/90 text-white text-xs px-3 py-1.5"
        >
          <Plus className="w-3.5 h-3.5" />
          Dodaj sprzęt
        </button>
      </div>

      {adding && (
        <EquipmentForm
          onSubmit={(payload) => createMut.mutate(payload)}
          onCancel={() => setAdding(false)}
          submitting={createMut.isPending}
        />
      )}

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Ładowanie…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground italic">
          Brak pozycji. Dodaj laptop, telefon, token itp. aby śledzić zwrot.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border dark:border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted dark:bg-muted text-xs uppercase text-muted-foreground">
              <tr>
                <th className="text-left px-3 py-2">Typ</th>
                <th className="text-left px-3 py-2">Model / serial</th>
                <th className="text-left px-3 py-2">Właściciel</th>
                <th className="text-left px-3 py-2">Termin zwrotu</th>
                <th className="text-left px-3 py-2">Status</th>
                <th className="text-right px-3 py-2">Akcje</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {items.map((item) => (
                <tr
                  key={item.id}
                  className={
                    isOverdue(item)
                      ? "bg-destructive/10 dark:bg-red-950/30"
                      : "bg-card dark:bg-card"
                  }
                >
                  <td className="px-3 py-2">
                    <span className="inline-flex items-center gap-1.5">
                      <Laptop className="w-3.5 h-3.5 text-muted-foreground" />
                      {ITEM_TYPE_LABELS[item.item_type]}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="font-medium">{item.brand_model || "—"}</div>
                    <div className="text-xs text-muted-foreground">
                      {item.serial_number || "—"}
                    </div>
                  </td>
                  <td className="px-3 py-2">{OWNER_LABELS[item.owner]}</td>
                  <td className="px-3 py-2">
                    {item.return_due_date ? (
                      <span className="flex items-center gap-1">
                        {isOverdue(item) && (
                          <AlertTriangle className="w-3.5 h-3.5 text-destructive" />
                        )}
                        {formatDate(item.return_due_date)}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[item.return_status]}`}
                    >
                      {STATUS_LABELS[item.return_status]}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="inline-flex gap-1">
                      {item.return_status === "pending" && (
                        <button
                          type="button"
                          onClick={() =>
                            updateMut.mutate({
                              id: item.id,
                              payload: {
                                return_status: "returned",
                                returned_date: new Date()
                                  .toISOString()
                                  .slice(0, 10),
                              },
                            })
                          }
                          className="inline-flex items-center gap-1 text-xs text-green-700 hover:underline"
                        >
                          <Check className="w-3.5 h-3.5" />
                          Zwrócono
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => {
                          if (confirm("Usunąć pozycję ? ")) deleteMut.mutate(item.id);
                        }}
                        className="inline-flex items-center text-xs text-destructive hover:underline"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

interface EquipmentFormProps {
  onSubmit: (payload: Partial<ContractEquipmentItem>) => void;
  onCancel: () => void;
  submitting: boolean;
}

function EquipmentForm({ onSubmit, onCancel, submitting }: EquipmentFormProps) {
  const [form, setForm] = useState({
    item_type: "laptop" as EquipmentItemType,
    owner: "ours" as EquipmentOwner,
    brand_model: "",
    serial_number: "",
    handed_over_date: new Date().toISOString().slice(0, 10),
    return_due_date: "",
    description: "",
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      item_type: form.item_type,
      owner: form.owner,
      brand_model: form.brand_model || null,
      serial_number: form.serial_number || null,
      handed_over_date: form.handed_over_date || null,
      return_due_date: form.return_due_date || null,
      description: form.description || null,
    });
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-border dark:border-border p-4 space-y-3 bg-muted dark:bg-muted"
    >
      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="text-xs text-muted-foreground">Typ</span>
          <select
            value={form.item_type}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                item_type: e.target.value as EquipmentItemType,
              }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-card"
          >
            {Object.entries(ITEM_TYPE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Właściciel</span>
          <select
            value={form.owner}
            onChange={(e) =>
              setForm((f) => ({ ...f, owner: e.target.value as EquipmentOwner }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-card"
          >
            {Object.entries(OWNER_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Model</span>
          <input
            value={form.brand_model}
            onChange={(e) =>
              setForm((f) => ({ ...f, brand_model: e.target.value }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-card"
            placeholder="ThinkPad X1 Carbon Gen 11"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Numer seryjny</span>
          <input
            value={form.serial_number}
            onChange={(e) =>
              setForm((f) => ({ ...f, serial_number: e.target.value }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-card"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Wydany</span>
          <input
            type="date"
            value={form.handed_over_date}
            onChange={(e) =>
              setForm((f) => ({ ...f, handed_over_date: e.target.value }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-card"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">Termin zwrotu</span>
          <input
            type="date"
            value={form.return_due_date}
            onChange={(e) =>
              setForm((f) => ({ ...f, return_due_date: e.target.value }))
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-card"
          />
        </label>
      </div>
      <label className="block">
        <span className="text-xs text-muted-foreground">Notatka</span>
        <textarea
          value={form.description}
          onChange={(e) =>
            setForm((f) => ({ ...f, description: e.target.value }))
          }
          className="mt-1 w-full border border-border dark:border-border rounded-md px-2 py-1.5 text-sm bg-card dark:bg-card"
          rows={2}
        />
      </label>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="text-sm text-muted-foreground hover:underline"
        >
          Anuluj
        </button>
        <button
          type="submit"
          disabled={submitting}
          className="text-sm bg-primary hover:bg-primary/90 disabled:opacity-50 text-white rounded-md px-3 py-1.5"
        >
          {submitting ? "Zapisywanie…" : "Zapisz"}
        </button>
      </div>
    </form>
  );
}
