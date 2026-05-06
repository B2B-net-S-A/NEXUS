"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { RequireRole } from "@/components/RequireRole";
import { formatCurrency } from "@/lib/utils";
import { Plus, Trash2, Loader2, Pencil, X } from "lucide-react";

const SENIORITIES = ["", "junior", "mid", "senior", "lead", "architect"];
const RATE_UNITS = [
  { value: "monthly", label: "/mies." },
  { value: "daily", label: "/dz." },
  { value: "hourly", label: "/h" },
];

interface RateCard {
  id: number;
  client_id: number;
  role: string;
  seniority: string | null;
  rate_candidate_min: number | null;
  rate_candidate_max: number | null;
  rate_client_min: number | null;
  rate_client_max: number | null;
  currency: string;
  rate_unit: "hourly" | "daily" | "monthly";
  valid_from: string | null;
  valid_to: string | null;
  notes: string | null;
}

interface FormState {
  role: string;
  seniority: string;
  rate_candidate_min: string;
  rate_candidate_max: string;
  rate_client_min: string;
  rate_client_max: string;
  currency: string;
  rate_unit: string;
  valid_from: string;
  valid_to: string;
  notes: string;
}

const EMPTY: FormState = {
  role: "",
  seniority: "",
  rate_candidate_min: "",
  rate_candidate_max: "",
  rate_client_min: "",
  rate_client_max: "",
  currency: "PLN",
  rate_unit: "monthly",
  valid_from: "",
  valid_to: "",
  notes: "",
};

function range(min: number | null, max: number | null, currency: string): string {
  if (min === null && max === null) return "—";
  if (min !== null && max !== null && min === max)
    return formatCurrency(min, currency);
  if (min === null) return `≤ ${formatCurrency(max, currency)}`;
  if (max === null) return `≥ ${formatCurrency(min, currency)}`;
  return `${formatCurrency(min, currency)} – ${formatCurrency(max, currency)}`;
}

export function RateCardsTab({ clientId }: { clientId: number }) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [error, setError] = useState("");

  const { data, isLoading } = useQuery<RateCard[]>({
    queryKey: ["rate-cards", clientId],
    queryFn: () =>
      api.get(`/api/rate-cards?client_id=${clientId}`).then((r) => r.data),
  });

  const saveMutation = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      if (editingId) {
        return api.patch(`/api/rate-cards/${editingId}`, payload);
      }
      return api.post("/api/rate-cards", { ...payload, client_id: clientId });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rate-cards", clientId] });
      setShowForm(false);
      setEditingId(null);
      setForm(EMPTY);
      setError("");
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : "Błąd zapisu cennika";
      setError(message);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/rate-cards/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["rate-cards", clientId] }),
  });

  const startEdit = (card: RateCard) => {
    setEditingId(card.id);
    setForm({
      role: card.role,
      seniority: card.seniority ?? "",
      rate_candidate_min: card.rate_candidate_min?.toString() ?? "",
      rate_candidate_max: card.rate_candidate_max?.toString() ?? "",
      rate_client_min: card.rate_client_min?.toString() ?? "",
      rate_client_max: card.rate_client_max?.toString() ?? "",
      currency: card.currency,
      rate_unit: card.rate_unit,
      valid_from: card.valid_from ?? "",
      valid_to: card.valid_to ?? "",
      notes: card.notes ?? "",
    });
    setShowForm(true);
  };

  const handleCancel = () => {
    setShowForm(false);
    setEditingId(null);
    setForm(EMPTY);
    setError("");
  };

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.role.trim()) {
      setError("Rola jest wymagana");
      return;
    }
    const payload = {
      role: form.role.trim(),
      seniority: form.seniority || null,
      rate_candidate_min: form.rate_candidate_min ? Number(form.rate_candidate_min) : null,
      rate_candidate_max: form.rate_candidate_max ? Number(form.rate_candidate_max) : null,
      rate_client_min: form.rate_client_min ? Number(form.rate_client_min) : null,
      rate_client_max: form.rate_client_max ? Number(form.rate_client_max) : null,
      currency: form.currency,
      rate_unit: form.rate_unit,
      valid_from: form.valid_from || null,
      valid_to: form.valid_to || null,
      notes: form.notes || null,
    };
    saveMutation.mutate(payload);
  };

  const handleDelete = (card: RateCard) => {
    if (window.confirm(`Usunąć cennik dla "${card.role}"?`)) {
      deleteMutation.mutate(card.id);
    }
  };

  const cards = data ?? [];

  return (
    <div className="space-y-4">
      <RequireRole roles={["admin", "delivery_lead"]}>
        <button
          onClick={() => {
            setEditingId(null);
            setForm(EMPTY);
            setShowForm(true);
            setError("");
          }}
          className="flex items-center gap-2 bg-purple-600 hover:bg-purple-700 text-white px-4 py-2 rounded-lg text-sm font-medium"
        >
          <Plus className="w-4 h-4" /> Dodaj wpis cennika
        </button>
      </RequireRole>

      {showForm && (
        <form
          onSubmit={handleSave}
          className="bg-card dark:bg-muted rounded-2xl shadow-sm p-4 space-y-3 border border-purple-200 dark:border-purple-900"
        >
          <h3 className="text-sm font-semibold">
            {editingId ? `Edytuj cennik #${editingId}` : "Nowy wpis cennika"}
          </h3>
          {error && (
            <div className="text-sm text-destructive bg-destructive/10 dark:bg-red-900/30 dark:text-red-300 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <label className="block">
              <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">Rola *</span>
              <input
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
                placeholder="Senior Java Dev"
                className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>
            <label className="block">
              <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">Seniority</span>
              <select
                value={form.seniority}
                onChange={(e) => setForm({ ...form, seniority: e.target.value })}
                className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
              >
                {SENIORITIES.map((s) => (
                  <option key={s || "any"} value={s}>
                    {s || "— dowolna —"}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">Jednostka</span>
              <select
                value={form.rate_unit}
                onChange={(e) => setForm({ ...form, rate_unit: e.target.value })}
                className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
              >
                {RATE_UNITS.map((u) => (
                  <option key={u.value} value={u.value}>
                    {u.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <label className="block">
              <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">Kandydat od</span>
              <input
                type="number"
                value={form.rate_candidate_min}
                onChange={(e) => setForm({ ...form, rate_candidate_min: e.target.value })}
                className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>
            <label className="block">
              <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">Kandydat do</span>
              <input
                type="number"
                value={form.rate_candidate_max}
                onChange={(e) => setForm({ ...form, rate_candidate_max: e.target.value })}
                className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>
            <label className="block">
              <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">Klient od</span>
              <input
                type="number"
                value={form.rate_client_min}
                onChange={(e) => setForm({ ...form, rate_client_min: e.target.value })}
                className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>
            <label className="block">
              <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">Klient do</span>
              <input
                type="number"
                value={form.rate_client_max}
                onChange={(e) => setForm({ ...form, rate_client_max: e.target.value })}
                className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <label className="block">
              <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">Waluta</span>
              <select
                value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value })}
                className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
              >
                <option>PLN</option>
                <option>EUR</option>
                <option>USD</option>
                <option>GBP</option>
              </select>
            </label>
            <label className="block">
              <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">Ważny od</span>
              <input
                type="date"
                value={form.valid_from}
                onChange={(e) => setForm({ ...form, valid_from: e.target.value })}
                className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>
            <label className="block">
              <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">Ważny do</span>
              <input
                type="date"
                value={form.valid_to}
                onChange={(e) => setForm({ ...form, valid_to: e.target.value })}
                className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>
          </div>
          <label className="block">
            <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">Notatki</span>
            <textarea
              rows={2}
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
            />
          </label>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={handleCancel}
              className="flex items-center gap-2 px-3 py-2 text-sm text-foreground hover:bg-muted dark:text-muted-foreground dark:hover:bg-muted rounded-lg"
            >
              <X className="w-4 h-4" /> Anuluj
            </button>
            <button
              type="submit"
              disabled={saveMutation.isPending}
              className="bg-purple-600 hover:bg-purple-700 disabled:opacity-60 text-white px-4 py-2 rounded-lg text-sm font-medium"
            >
              {saveMutation.isPending ? "Zapisywanie…" : "Zapisz"}
            </button>
          </div>
        </form>
      )}

      {isLoading ? (
        <div className="text-sm text-muted-foreground flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Ładowanie cennika…
        </div>
      ) : cards.length === 0 ? (
        <div className="text-sm text-muted-foreground italic">
          Brak wpisów cennika — dodaj pierwszy, żeby móc korzystać z auto-suggest przy tworzeniu kontraktu.
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border dark:border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted dark:bg-muted/40 text-xs uppercase text-muted-foreground dark:text-muted-foreground">
              <tr>
                <th className="text-left px-3 py-2">Rola</th>
                <th className="text-left px-3 py-2">Seniority</th>
                <th className="text-left px-3 py-2">Kandydat</th>
                <th className="text-left px-3 py-2">Klient</th>
                <th className="text-left px-3 py-2">Okres</th>
                <th className="text-right px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {cards.map((c) => (
                <tr key={c.id} className="border-t border-border dark:border-border">
                  <td className="px-3 py-2 font-medium">{c.role}</td>
                  <td className="px-3 py-2 text-muted-foreground dark:text-muted-foreground">
                    {c.seniority ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    {range(c.rate_candidate_min, c.rate_candidate_max, c.currency)}
                    <span className="text-xs opacity-70">
                      {RATE_UNITS.find((u) => u.value === c.rate_unit)?.label}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {range(c.rate_client_min, c.rate_client_max, c.currency)}
                    <span className="text-xs opacity-70">
                      {RATE_UNITS.find((u) => u.value === c.rate_unit)?.label}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-muted-foreground dark:text-muted-foreground">
                    {c.valid_from || "—"} → {c.valid_to || "∞"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <RequireRole roles={["admin", "delivery_lead"]}>
                      <div className="inline-flex gap-1">
                        <button
                          onClick={() => startEdit(c)}
                          className="p-1.5 rounded hover:bg-muted dark:hover:bg-muted text-muted-foreground"
                          title="Edytuj"
                        >
                          <Pencil className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDelete(c)}
                          disabled={deleteMutation.isPending}
                          className="p-1.5 rounded hover:bg-destructive/10 dark:hover:bg-red-900/20 text-destructive disabled:opacity-50"
                          title="Usuń"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </RequireRole>
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
