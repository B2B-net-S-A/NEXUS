"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { useToast } from "@/components/Toast";
import { formatCurrency } from "@/lib/utils";
import { formatIsoDatePl as formatDate } from "@/lib/date-pl";
import { Plus, Trash2, Check, Loader2, X } from "lucide-react";

interface Invoice {
  id: number;
  contract_id: number;
  direction: "to_client" | "from_contractor";
  invoice_number: string;
  period_month: number | null;
  period_year: number | null;
  issue_date: string;
  due_date: string | null;
  paid_date: string | null;
  amount: number;
  currency: string;
  status: "issued" | "sent" | "paid" | "overdue" | "cancelled";
  notes: string | null;
}

// Etykiety PL zamiast surowego `paid`/`overdue` (audyt 24.09, N9).
export const INVOICE_STATUS_LABELS: Record<string, string> = {
  issued: "Wystawiona",
  sent: "Wysłana",
  paid: "Zapłacona",
  overdue: "Przeterminowana",
  cancelled: "Anulowana",
};

const STATUS_COLOR: Record<string, string> = {
  issued: "bg-muted text-foreground",
  sent: "bg-primary/15 text-primary",
  paid: "bg-emerald-100 text-emerald-700",
  overdue: "bg-destructive/15 text-destructive",
  cancelled: "bg-muted text-muted-foreground line-through",
};

/** Dzisiejsza data kalendarzowa w strefie firmy (YYYY-MM-DD).
 *
 *  Liczona PRZY KAŻDYM wywołaniu, nigdy raz na moduł. Poprzednia wersja trzymała
 *  stałą na poziomie modułu komponentu `"use client"`, który wykonuje się raz na
 *  załadowanie dokumentu i nie jest przeliczany przy miękkich nawigacjach — karta
 *  ATS zostawiona otwarta przez kilka dni zamrażała datę płatności na dzień jej
 *  otwarcia. `toISOString()` był dodatkowo w UTC, więc między północą warszawską
 *  a północą UTC stemplował dzień wcześniejszy. Skutek był cichy: `paid_date`
 *  wcześniejszy niż `issue_date` wypada z `avg_dso_days` (`GET /api/invoices/dso`
 *  odrzuca takie wiersze), a we froncie nie ma żadnego pola do jego poprawienia.
 *  `sv-SE` wybrane, bo jako jedyne popularne locale formatuje wprost `YYYY-MM-DD`. */
function todayWarsawISO(): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/Warsaw" }).format(
    new Date(),
  );
}

function emptyForm() {
  return {
    direction: "to_client",
    invoice_number: "",
    issue_date: todayWarsawISO(),
    due_date: "",
    amount: "",
    currency: "PLN",
    notes: "",
  };
}

/**
 * Faktury kontraktu. Bramka jest JEDNA i przychodzi z góry (`readOnly`):
 * backend `/api/invoices` zapisuje z capability `manage_finance`. Do 24.09
 * (audyt, S10) w środku siedział dodatkowo `RequireRole admin/delivery_lead`,
 * a strona dawała `readOnly={!canManageFinance}` — Finanse były wpuszczane
 * z zewnątrz i wyrzucane w środku, DL odwrotnie, więc w praktyce pisał tylko
 * admin.
 */
export function ContractInvoicesTab({
  contractId,
  readOnly = false,
}: {
  contractId: number;
  readOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  // Potwierdzenie usunięcia w wierszu zamiast `window.confirm` (N7).
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const { data, isLoading, isError, refetch } = useQuery<Invoice[]>({
    queryKey: ["contract-invoices", contractId],
    queryFn: () =>
      api.get(`/api/invoices?contract_id=${contractId}`).then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post(`/api/invoices`, { ...payload, contract_id: contractId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contract-invoices", contractId] });
      setShowForm(false);
      setForm(emptyForm());
    },
    // Odmowa nie może kończyć się ciszą (audyt 24.09, N10).
    onError: (err: unknown) =>
      showError(apiErrorMessage(err, "Nie udało się zapisać faktury.")),
  });

  const markPaidMutation = useMutation({
    mutationFn: (id: number) =>
      api.patch(`/api/invoices/${id}`, {
        status: "paid",
        paid_date: todayWarsawISO(),
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["contract-invoices", contractId] }),
    onError: (err: unknown) =>
      showError(
        apiErrorMessage(err, "Nie udało się oznaczyć faktury jako zapłaconej."),
      ),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/invoices/${id}`),
    onSuccess: () => {
      setConfirmDeleteId(null);
      queryClient.invalidateQueries({ queryKey: ["contract-invoices", contractId] });
    },
    onError: (err: unknown) =>
      showError(apiErrorMessage(err, "Nie udało się usunąć faktury.")),
  });

  const invoices = data ?? [];

  return (
    <div className="space-y-4">
      {!readOnly && (
        <>
          {!showForm ? (
            <button
              onClick={() => {
                // Data wystawienia liczona przy OTWARCIU formularza, nie przy
                // montażu karty — inaczej długo otwarta zakładka podpowiada dzień
                // swojego otwarcia (ten sam defekt co zamrożone `paid_date`).
                setForm(emptyForm());
                setShowForm(true);
              }}
              className="flex items-center gap-2 bg-primary hover:bg-primary/90 text-white px-3 py-2 rounded-lg text-sm font-medium"
            >
              <Plus className="w-4 h-4" /> Dodaj fakturę
            </button>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                createMutation.mutate({
                  ...form,
                  amount: Number(form.amount) || 0,
                  due_date: form.due_date || null,
                });
              }}
              className="bg-card dark:bg-muted rounded-2xl shadow-xs p-4 space-y-3"
            >
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <label className="block">
                  <span className="block text-xs text-muted-foreground mb-1">Kierunek</span>
                  <select
                    value={form.direction}
                    onChange={(e) => setForm({ ...form, direction: e.target.value })}
                    className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                  >
                    <option value="to_client">Do klienta</option>
                    <option value="from_contractor">Od kontraktora</option>
                  </select>
                </label>
                <label className="block">
                  <span className="block text-xs text-muted-foreground mb-1">Numer</span>
                  <input
                    value={form.invoice_number}
                    onChange={(e) => setForm({ ...form, invoice_number: e.target.value })}
                    className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                    placeholder="FV/2026/04/001"
                  />
                </label>
                <label className="block">
                  <span className="block text-xs text-muted-foreground mb-1">Kwota</span>
                  <input
                    type="number"
                    value={form.amount}
                    onChange={(e) => setForm({ ...form, amount: e.target.value })}
                    className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                  />
                </label>
                <label className="block">
                  <span className="block text-xs text-muted-foreground mb-1">Waluta</span>
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
                  <span className="block text-xs text-muted-foreground mb-1">Data wystawienia</span>
                  <input
                    type="date"
                    value={form.issue_date}
                    onChange={(e) => setForm({ ...form, issue_date: e.target.value })}
                    className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                  />
                </label>
                <label className="block">
                  <span className="block text-xs text-muted-foreground mb-1">Termin płatności</span>
                  <input
                    type="date"
                    value={form.due_date}
                    onChange={(e) => setForm({ ...form, due_date: e.target.value })}
                    className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                  />
                </label>
              </div>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setShowForm(false);
                    setForm(emptyForm());
                  }}
                  className="px-3 py-2 text-sm text-foreground hover:bg-muted dark:text-muted-foreground dark:hover:bg-muted rounded-lg"
                >
                  Anuluj
                </button>
                <button
                  type="submit"
                  disabled={createMutation.isPending}
                  className="bg-primary hover:bg-primary/90 disabled:opacity-60 text-white px-4 py-2 rounded-lg text-sm font-medium"
                >
                  {createMutation.isPending ? "Zapisywanie…" : "Zapisz"}
                </button>
              </div>
            </form>
          )}
        </>
      )}

      {isLoading ? (
        <div className="text-sm text-muted-foreground flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Ładowanie faktur…
        </div>
      ) : isError ? (
        <div
          role="alert"
          className="text-sm text-destructive bg-destructive/10 rounded-2xl p-6 text-center"
        >
          Nie udało się wczytać faktur.{" "}
          <button
            type="button"
            onClick={() => void refetch()}
            className="font-medium underline hover:no-underline"
          >
            Ponów
          </button>
        </div>
      ) : invoices.length === 0 ? (
        <div className="text-sm text-muted-foreground italic bg-card dark:bg-muted rounded-2xl p-6 text-center shadow-xs">
          Brak faktur. Dodaj pierwszą, żeby mieć historię rozliczeń z kontraktorem.
        </div>
      ) : (
        <div className="bg-card dark:bg-muted rounded-2xl shadow-xs overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead className="bg-muted dark:bg-muted/40 text-xs uppercase text-muted-foreground dark:text-muted-foreground">
              <tr>
                <th className="sticky left-0 z-10 bg-muted text-left px-3 py-2">Numer</th>
                <th className="text-left px-3 py-2">Kierunek</th>
                <th className="text-left px-3 py-2">Wystawiona</th>
                <th className="text-left px-3 py-2">Termin</th>
                <th className="text-right px-3 py-2">Kwota</th>
                <th className="text-left px-3 py-2">Status</th>
                {!readOnly && <th className="text-right px-3 py-2"></th>}
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => {
                // Porównanie dat ISO w strefie firmy — `new Date(due)` to
                // północ UTC, czyli 1–2 h przesunięcia (N8).
                const overdue =
                  inv.due_date &&
                  inv.status !== "paid" &&
                  inv.status !== "cancelled" &&
                  inv.due_date < todayWarsawISO();
                return (
                  <tr key={inv.id} className="border-t border-border dark:border-border">
                    <td className="sticky left-0 z-10 bg-card dark:bg-muted px-3 py-2 font-medium">{inv.invoice_number}</td>
                    <td className="px-3 py-2 text-muted-foreground dark:text-muted-foreground text-xs">
                      {inv.direction === "to_client" ? "→ klient" : "← kontraktor"}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">{formatDate(inv.issue_date)}</td>
                    <td
                      className={`px-3 py-2 ${overdue ? "text-destructive font-semibold" : ""}`}
                    >
                      {inv.due_date ? formatDate(inv.due_date) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      {formatCurrency(inv.amount, inv.currency)}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLOR[inv.status] ?? ""}`}
                      >
                        {INVOICE_STATUS_LABELS[inv.status] ?? inv.status}
                      </span>
                    </td>
                    {!readOnly && (
                      <td className="px-3 py-2 text-right">
                        {confirmDeleteId === inv.id ? (
                          <div className="inline-flex items-center gap-1 text-xs">
                            <span className="text-muted-foreground">Usunąć?</span>
                            <button
                              type="button"
                              onClick={() => deleteMutation.mutate(inv.id)}
                              disabled={deleteMutation.isPending}
                              aria-label={`Potwierdź usunięcie faktury ${inv.invoice_number}`}
                              className="rounded px-2 py-1 font-medium text-destructive hover:bg-destructive/10 disabled:opacity-60"
                            >
                              Usuń
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmDeleteId(null)}
                              aria-label="Anuluj usuwanie"
                              className="rounded p-1 hover:bg-muted"
                            >
                              <X className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        ) : (
                          <div className="inline-flex gap-1">
                            {inv.status !== "paid" && (
                              <button
                                onClick={() => markPaidMutation.mutate(inv.id)}
                                disabled={markPaidMutation.isPending}
                                title="Oznacz jako zapłacone"
                                aria-label={`Oznacz fakturę ${inv.invoice_number} jako zapłaconą`}
                                className="p-1.5 pointer-coarse:p-2.5 rounded hover:bg-emerald-50 text-emerald-600"
                              >
                                <Check className="w-4 h-4" />
                              </button>
                            )}
                            <button
                              onClick={() => setConfirmDeleteId(inv.id)}
                              title="Usuń fakturę"
                              aria-label={`Usuń fakturę ${inv.invoice_number}`}
                              className="p-1.5 pointer-coarse:p-2.5 rounded hover:bg-destructive/10 text-destructive"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        )}
                      </td>
                    )}
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
