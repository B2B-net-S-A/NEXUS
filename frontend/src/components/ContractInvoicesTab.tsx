"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { RequireRole } from "@/components/RequireRole";
import { formatCurrency, formatDate } from "@/lib/utils";
import { Plus, Trash2, Check, Loader2 } from "lucide-react";

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

export function ContractInvoicesTab({
  contractId,
  readOnly = false,
}: {
  contractId: number;
  readOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);

  const { data, isLoading } = useQuery<Invoice[]>({
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
  });

  const markPaidMutation = useMutation({
    mutationFn: (id: number) =>
      api.patch(`/api/invoices/${id}`, {
        status: "paid",
        paid_date: todayWarsawISO(),
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["contract-invoices", contractId] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/invoices/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["contract-invoices", contractId] }),
  });

  const invoices = data ?? [];

  return (
    <div className="space-y-4">
      {!readOnly && (
        <RequireRole roles={["admin", "delivery_lead"]}>
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
        </RequireRole>
      )}

      {isLoading ? (
        <div className="text-sm text-muted-foreground flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Ładowanie faktur…
        </div>
      ) : invoices.length === 0 ? (
        <div className="text-sm text-muted-foreground italic bg-card dark:bg-muted rounded-2xl p-6 text-center shadow-xs">
          Brak faktur. Dodaj pierwszą, żeby mieć historię rozliczeń z kontraktorem.
        </div>
      ) : (
        <div className="bg-card dark:bg-muted rounded-2xl shadow-xs overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted dark:bg-muted/40 text-xs uppercase text-muted-foreground dark:text-muted-foreground">
              <tr>
                <th className="text-left px-3 py-2">Numer</th>
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
                const overdue =
                  inv.due_date &&
                  inv.status !== "paid" &&
                  new Date(inv.due_date).getTime() < Date.now();
                return (
                  <tr key={inv.id} className="border-t border-border dark:border-border">
                    <td className="px-3 py-2 font-medium">{inv.invoice_number}</td>
                    <td className="px-3 py-2 text-muted-foreground dark:text-muted-foreground text-xs">
                      {inv.direction === "to_client" ? "→ klient" : "← kontraktor"}
                    </td>
                    <td className="px-3 py-2">{formatDate(inv.issue_date)}</td>
                    <td
                      className={`px-3 py-2 ${overdue ? "text-destructive font-semibold" : ""}`}
                    >
                      {inv.due_date ? formatDate(inv.due_date) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {formatCurrency(inv.amount, inv.currency)}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLOR[inv.status] ?? ""}`}
                      >
                        {inv.status}
                      </span>
                    </td>
                    {!readOnly && (
                      <td className="px-3 py-2 text-right">
                        <RequireRole roles={["admin", "delivery_lead"]}>
                          <div className="inline-flex gap-1">
                            {inv.status !== "paid" && (
                              <button
                                onClick={() => markPaidMutation.mutate(inv.id)}
                                disabled={markPaidMutation.isPending}
                                title="Oznacz jako zapłacone"
                                className="p-1.5 rounded hover:bg-emerald-50 text-emerald-600"
                              >
                                <Check className="w-4 h-4" />
                              </button>
                            )}
                            <button
                              onClick={() => {
                                if (window.confirm(`Usunąć fakturę ${inv.invoice_number}?`)) {
                                  deleteMutation.mutate(inv.id);
                                }
                              }}
                              className="p-1.5 rounded hover:bg-destructive/10 text-destructive"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </RequireRole>
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
