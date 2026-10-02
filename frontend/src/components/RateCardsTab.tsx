"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api, { extractErrorMsg } from "@/lib/api";
import { hasAnalyticsCapability, useAuthStore } from "@/store/auth";
import { formatCurrency } from "@/lib/utils";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { ConfirmButton } from "@/components/ConfirmDialog";
import { resolveViewState } from "@/lib/view-state";
import { Plus, Trash2, Loader2, Pencil, X } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  CALM_AMOUNT,
  CALM_EMPTY,
  CALM_HEAD,
  CALM_ROW,
  CALM_UNIT,
} from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";

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
  const user = useAuthStore((s) => s.user);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [error, setError] = useState("");

  // Lustro backendu: GET = `FinanceReadUser` (VIEW_FINANCE), zapisy =
  // `FinanceManageUser` (MANAGE_FINANCE) — api/rate_cards.py. Ręczna lista
  // `["admin","delivery_lead"]` była pozostałością po erze `DeliveryLeadPlus`
  // sprzed cutoveru RBAC (#1031): jednocześnie ZA SZEROKA (DL nie ma
  // VIEW_FINANCE, więc każdy zapis kończył się 403) i ZA WĄSKA (finance, jedyna
  // nie-adminowa rola z tą capability, nie widziała żadnych kontrolek).
  const canRead = hasAnalyticsCapability(user, "view_finance");
  const canManage = hasAnalyticsCapability(user, "manage_finance");

  const { data, isLoading, isError, error: queryError, refetch } = useQuery<
    RateCard[]
  >({
    queryKey: ["rate-cards", clientId],
    queryFn: () =>
      api.get(`/api/rate-cards?client_id=${clientId}`).then((r) => r.data),
    // Bez VIEW_FINANCE backend i tak odpowie 403 — nie ma po co go pytać.
    enabled: canRead,
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
      setError(extractErrorMsg(err));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/rate-cards/${id}`),
    onSuccess: () => {
      setError("");
      queryClient.invalidateQueries({ queryKey: ["rate-cards", clientId] });
    },
    // Usuwanie było jedyną akcją bez żadnej ścieżki błędu — odrzucone 403
    // wyglądało dokładnie tak jak udane usunięcie, które „nie odświeżyło listy".
    onError: (err: unknown) => {
      setError(extractErrorMsg(err));
    },
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

  // Potwierdzenie w wierszu (`ConfirmButton`), nie natywny `window.confirm`,
  // który zamraża automatyzację przeglądarki (audyt S12).
  const handleDelete = (card: RateCard) => {
    deleteMutation.mutate(card.id);
  };

  const cards = data ?? [];

  // `enabled: canRead` sprawia, że przy braku uprawnień zapytanie stoi w stanie
  // „nie wystartowało" (isLoading=false, data=undefined) — czyli wpadłoby wprost
  // w gałąź pustą. Brak uprawnień musi mieć własną, jawną odpowiedź.
  if (!canRead) {
    return (
      <QueryStateNotice
        state="forbidden"
        description="Cennik klienta jest częścią danych finansowych. Twoja rola go nie widzi — to nie znaczy, że cennik jest pusty."
      />
    );
  }

  const viewState = resolveViewState({
    isLoading,
    isError,
    error: queryError,
    isEmpty: cards.length === 0,
  });
  const failed =
    viewState === "forbidden" ||
    viewState === "not_found" ||
    viewState === "error";

  return (
    <div className="space-y-3">
      {canManage && (
        <Button
          size="sm"
          variant="primary"
          onClick={() => {
            setEditingId(null);
            setForm(EMPTY);
            setShowForm(true);
            setError("");
          }}
        >
          <Plus className="h-3.5 w-3.5" aria-hidden="true" /> Dodaj wpis cennika
        </Button>
      )}

      {/* Błąd usuwania nie ma gdzie indziej wyjść — formularz bywa zamknięty. */}
      {error && !showForm && (
        <div className="text-sm text-destructive bg-destructive/10 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {showForm && (
        <form
          onSubmit={handleSave}
          className="space-y-3 rounded-lg border border-border bg-card p-4"
        >
          <h3 className="text-[13px] font-semibold">
            {editingId ? `Edytuj cennik #${editingId}` : "Nowy wpis cennika"}
          </h3>
          {error && (
            <div className="text-sm text-destructive bg-destructive/10 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <label className="block">
              <span className="block text-xs text-muted-foreground mb-1">Rola *</span>
              <input
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
                placeholder="Senior Java Dev"
                className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>
            <label className="block">
              <span className="block text-xs text-muted-foreground mb-1">Seniority</span>
              <select
                value={form.seniority}
                onChange={(e) => setForm({ ...form, seniority: e.target.value })}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-card dark:bg-muted"
              >
                {SENIORITIES.map((s) => (
                  <option key={s || "any"} value={s}>
                    {s || "— dowolna —"}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="block text-xs text-muted-foreground mb-1">Jednostka</span>
              <select
                value={form.rate_unit}
                onChange={(e) => setForm({ ...form, rate_unit: e.target.value })}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-card dark:bg-muted"
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
              <span className="block text-xs text-muted-foreground mb-1">Kandydat od</span>
              <input
                type="number"
                value={form.rate_candidate_min}
                onChange={(e) => setForm({ ...form, rate_candidate_min: e.target.value })}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>
            <label className="block">
              <span className="block text-xs text-muted-foreground mb-1">Kandydat do</span>
              <input
                type="number"
                value={form.rate_candidate_max}
                onChange={(e) => setForm({ ...form, rate_candidate_max: e.target.value })}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>
            <label className="block">
              <span className="block text-xs text-muted-foreground mb-1">Klient od</span>
              <input
                type="number"
                value={form.rate_client_min}
                onChange={(e) => setForm({ ...form, rate_client_min: e.target.value })}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>
            <label className="block">
              <span className="block text-xs text-muted-foreground mb-1">Klient do</span>
              <input
                type="number"
                value={form.rate_client_max}
                onChange={(e) => setForm({ ...form, rate_client_max: e.target.value })}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <label className="block">
              <span className="block text-xs text-muted-foreground mb-1">Waluta</span>
              <select
                value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value })}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-card dark:bg-muted"
              >
                <option>PLN</option>
                <option>EUR</option>
                <option>USD</option>
                <option>GBP</option>
              </select>
            </label>
            <label className="block">
              <span className="block text-xs text-muted-foreground mb-1">Ważny od</span>
              <input
                type="date"
                value={form.valid_from}
                onChange={(e) => setForm({ ...form, valid_from: e.target.value })}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>
            <label className="block">
              <span className="block text-xs text-muted-foreground mb-1">Ważny do</span>
              <input
                type="date"
                value={form.valid_to}
                onChange={(e) => setForm({ ...form, valid_to: e.target.value })}
                className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>
          </div>
          <label className="block">
            <span className="block text-xs text-muted-foreground mb-1">Notatki</span>
            <textarea
              rows={2}
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              className="w-full px-3 py-2 border border-border rounded-lg text-sm bg-card dark:bg-muted"
            />
          </label>
          <div className="flex justify-end gap-2">
            <Button type="button" size="sm" variant="ghost" onClick={handleCancel}>
              <X className="h-3.5 w-3.5" aria-hidden="true" /> Anuluj
            </Button>
            <Button
              type="submit"
              size="sm"
              variant="primary"
              disabled={saveMutation.isPending}
            >
              {saveMutation.isPending ? "Zapisywanie…" : "Zapisz"}
            </Button>
          </div>
        </form>
      )}

      {isLoading ? (
        <div className="text-sm text-muted-foreground flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Ładowanie cennika…
        </div>
      ) : failed ? (
        <QueryStateNotice
          state={viewState as "forbidden" | "not_found" | "error"}
          description={
            viewState === "forbidden"
              ? "Twoja rola nie ma dostępu do cennika tego klienta. Cennik NIE jest pusty — nie zakładaj wpisów od nowa."
              : undefined
          }
          onRetry={() => void refetch()}
        />
      ) : cards.length === 0 ? (
        <div className="text-sm text-muted-foreground italic">
          {canManage
            ? "Brak wpisów cennika — dodaj pierwszy, żeby móc korzystać z auto-suggest przy tworzeniu kontraktu."
            : "Brak wpisów cennika dla tego klienta."}
        </div>
      ) : (
        // `overflow-x-auto`, nie `overflow-hidden`: na telefonie sześć kolumn
        // się nie mieści, a ucięte kolumny (okres, akcje) były nieosiągalne.
        <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full min-w-[640px] text-[13px]">
            <thead>
              <tr className="border-b border-border">
                <th className={`sticky left-0 z-10 bg-card px-3 py-2 text-left ${CALM_HEAD}`}>
                  Rola
                </th>
                <th className={`px-3 py-2 text-left ${CALM_HEAD}`}>Seniority</th>
                <th className={`px-3 py-2 text-right ${CALM_HEAD}`}>Kandydat</th>
                <th className={`px-3 py-2 text-right ${CALM_HEAD}`}>Klient</th>
                <th className={`px-3 py-2 text-left ${CALM_HEAD}`}>Okres</th>
                <th className="px-3 py-2 text-right"></th>
              </tr>
            </thead>
            <tbody>
              {cards.map((c) => {
                const unit = RATE_UNITS.find((u) => u.value === c.rate_unit)?.label;
                return (
                  <tr key={c.id} className={`${CALM_ROW} last:border-b-0`}>
                    <td className="sticky left-0 z-10 bg-card px-3 py-2 font-semibold">
                      {c.role}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {c.seniority ?? <span className={CALM_EMPTY}>—</span>}
                    </td>
                    <td className={`px-3 py-2 ${CALM_AMOUNT}`}>
                      {range(c.rate_candidate_min, c.rate_candidate_max, c.currency)}
                      <span className={CALM_UNIT}>{unit}</span>
                    </td>
                    <td className={`px-3 py-2 ${CALM_AMOUNT}`}>
                      {range(c.rate_client_min, c.rate_client_max, c.currency)}
                      <span className={CALM_UNIT}>{unit}</span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-xs tabular-nums text-muted-foreground">
                      {c.valid_from ? formatIsoDatePl(c.valid_from) : "—"} →{" "}
                      {c.valid_to ? formatIsoDatePl(c.valid_to) : "∞"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {canManage && (
                        <div className="inline-flex items-center gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => startEdit(c)}
                            title="Edytuj"
                            aria-label="Edytuj"
                          >
                            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                          </Button>
                          <ConfirmButton
                            onConfirm={() => handleDelete(c)}
                            message={`Usunąć cennik „${c.role}”?`}
                            className={buttonVariants({ variant: "quiet", size: "sm" })}
                          >
                            <Trash2 className="h-3.5 w-3.5" aria-label="Usuń" />
                          </ConfirmButton>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
