"use client";

import { useState } from "react";
import Link from "next/link";
import { apiErrorMessage } from "@/lib/api-error";
import { documentsHref } from "@/lib/b2b-documents";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { RequireRole } from "@/components/RequireRole";
import { formatDate } from "@/lib/utils";
import { B2B_EXTENSION_HINT } from "@/lib/contract-end-date";
import { warsawToday } from "@/lib/warsaw-date";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { resolveViewState } from "@/lib/view-state";
import {
  canManageCandidateFinance,
  canViewClientFinance,
  useAuthStore,
} from "@/store/auth";
import {
  CalendarPlus,
  Banknote,
  LayoutGrid,
  X as StopIcon,
  Loader2,
  AlertCircle,
  FilePlus2,
} from "lucide-react";

const TYPE_LABELS: Record<string, string> = {
  extension: "Przedłużenie",
  rate_change: "Zmiana stawki",
  scope_change: "Zmiana zakresu",
  early_termination: "Wcześniejsze zakończenie",
};

const TYPE_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  extension: CalendarPlus,
  rate_change: Banknote,
  scope_change: LayoutGrid,
  early_termination: StopIcon,
};

interface Amendment {
  id: number;
  contract_id: number;
  amendment_type: "extension" | "rate_change" | "scope_change" | "early_termination";
  old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null;
  effective_date: string;
  reason: string | null;
  document_id: number | null;
  created_by: number | null;
  created_by_email: string | null;
  created_at: string;
}

type AmendmentType = Amendment["amendment_type"];

interface FormState {
  amendment_type: AmendmentType;
  effective_date: string;
  reason: string;
  new_end_date: string;
  new_rate_candidate: string;
  new_rate_client: string;
  new_project_name: string;
  new_team_name: string;
}

/**
 * Pusty formularz aneksu — liczony przy KAŻDYM otwarciu, nie raz przy
 * załadowaniu modułu. Stała `TODAY` z czasu importu zamrażała datę: karta
 * otwarta wczoraj podpowiadała wczorajszą datę wejścia w życie, a wyliczenie
 * z `toISOString()` dawało datę UTC, czyli między północą w Warszawie
 * a północą UTC — wczoraj (audyt FE-07).
 */
export function emptyAmendmentForm(
  amendmentType: AmendmentType = "extension",
  today: string = warsawToday(),
): FormState {
  return {
    amendment_type: amendmentType,
    effective_date: today,
    reason: "",
    new_end_date: "",
    new_rate_candidate: "",
    new_rate_client: "",
    new_project_name: "",
    new_team_name: "",
  };
}

export function ContractAmendmentsTab({
  contractId,
  clientId,
  readOnly = false,
  extensionLocked = false,
  onRequestTermination,
}: {
  contractId: number;
  clientId: number;
  readOnly?: boolean;
  /** Umowa B2B bez ręcznego zakończenia — aneks przedłużający jest odrzucany
   *  przez backend, więc przycisk go nie oferuje (`b2bExtensionLocked`). */
  extensionLocked?: boolean;
  /** „Zakończ wcześniej" otwiera okno „Zakończ współpracę" (ticket 09.2026) —
   *  zakończenie kontraktu ma jedno wejście, które zapisuje powód, datę końca
   *  projektu i rozwiązanie umowy. Bez callbacku przycisku nie ma. */
  onRequestTermination?: () => void;
}) {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const canManageFinance = canManageCandidateFinance(user);
  const canViewFinance = canViewClientFinance(user, clientId);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(() => emptyAmendmentForm());
  const [error, setError] = useState("");

  const amendmentsQuery = useQuery<Amendment[]>({
    queryKey: ["contract-amendments", contractId],
    queryFn: () =>
      api.get(`/api/contracts/${contractId}/amendments`).then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post(`/api/contracts/${contractId}/amendments`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contract-amendments", contractId] });
      queryClient.invalidateQueries({ queryKey: ["contract", contractId] });
      queryClient.invalidateQueries({ queryKey: ["contract-activities", contractId] });
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
      // Aneks zmienia status, datę końca i stawki — lista kontraktów, lista
      // „kończących się" i historia stawek muszą to zobaczyć bez przeładowania
      // strony (audyt FE-02). Klucze: `ContractsListV2`, `contracts/[id]`.
      queryClient.invalidateQueries({ queryKey: ["contracts-v2"] });
      queryClient.invalidateQueries({ queryKey: ["contracts-expiring-v2"] });
      queryClient.invalidateQueries({ queryKey: ["contract-rate-history", contractId] });
      setShowForm(false);
      setForm(emptyAmendmentForm());
      setError("");
    },
    onError: (err: unknown) => {
      setError(apiErrorMessage(err, err instanceof Error ? err.message : "Błąd"));
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (form.amendment_type === "rate_change" && !canManageFinance) {
      setShowForm(false);
      setForm(emptyAmendmentForm());
      setError("");
      return;
    }
    const payload: Record<string, unknown> = {
      amendment_type: form.amendment_type,
      effective_date: form.effective_date,
      reason: form.reason || null,
    };
    if (form.amendment_type === "extension" && form.new_end_date) {
      payload.new_end_date = form.new_end_date;
    }
    if (form.amendment_type === "rate_change" && canManageFinance) {
      if (form.new_rate_candidate) payload.new_rate_candidate = Number(form.new_rate_candidate);
      if (form.new_rate_client) payload.new_rate_client = Number(form.new_rate_client);
    }
    if (form.amendment_type === "scope_change") {
      if (form.new_project_name) payload.new_project_name = form.new_project_name;
      if (form.new_team_name) payload.new_team_name = form.new_team_name;
    }
    if (form.amendment_type === "early_termination" && form.new_end_date) {
      payload.new_end_date = form.new_end_date;
    }
    createMutation.mutate(payload);
  };

  const amendments = (amendmentsQuery.data ?? []).filter(
    (amendment) =>
      canViewFinance || amendment.amendment_type !== "rate_change",
  );

  const viewState = resolveViewState({
    isLoading: amendmentsQuery.isLoading,
    error: amendmentsQuery.error,
    isSuccess: amendmentsQuery.isSuccess,
    isEmpty: amendments.length === 0,
  });

  return (
    <div className="space-y-4">
      {!readOnly && (
        <RequireRole roles={["admin", "delivery_lead"]}>
          {!showForm && (
            <div className="flex flex-wrap gap-2">
            <button
              onClick={() => {
                setForm(emptyAmendmentForm("extension"));
                setShowForm(true);
              }}
              disabled={extensionLocked}
              title={extensionLocked ? B2B_EXTENSION_HINT : undefined}
              className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 disabled:hover:bg-emerald-600 text-white px-3 py-2 rounded-lg text-sm font-medium"
            >
              <CalendarPlus className="w-4 h-4" /> Przedłuż
            </button>
            {canManageFinance && (
              <button
                onClick={() => {
                  setForm(emptyAmendmentForm("rate_change"));
                  setShowForm(true);
                }}
                className="flex items-center gap-2 bg-primary hover:bg-primary/90 text-white px-3 py-2 rounded-lg text-sm font-medium"
              >
                <Banknote className="w-4 h-4" /> Zmień stawkę
              </button>
            )}
            <button
              onClick={() => {
                setForm(emptyAmendmentForm("scope_change"));
                setShowForm(true);
              }}
              className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white px-3 py-2 rounded-lg text-sm font-medium"
            >
              <LayoutGrid className="w-4 h-4" /> Zmień zakres
            </button>
            {onRequestTermination && (
              <button
                type="button"
                onClick={onRequestTermination}
                className="flex items-center gap-2 bg-red-600 hover:bg-red-700 text-white px-3 py-2 rounded-lg text-sm font-medium"
              >
                <StopIcon className="w-4 h-4" /> Zakończ wcześniej
              </button>
            )}
            {/* Dokument aneksu do podpisu (DOCX) — generator dokumentów
                w module Generator Umów B2B, umowa bazowa po tym kontrakcie. */}
            <Link
              href={documentsHref({ newType: "annex_rate_change", contractId })}
              className="flex items-center gap-2 border border-border hover:bg-muted text-foreground px-3 py-2 rounded-lg text-sm font-medium"
            >
              <FilePlus2 className="w-4 h-4" /> Wygeneruj dokument aneksu
            </Link>
            {extensionLocked && (
              <p className="basis-full text-xs text-muted-foreground">
                {B2B_EXTENSION_HINT}
              </p>
            )}
            </div>
          )}
        </RequireRole>
      )}

      {!readOnly && showForm && (
        <form
          onSubmit={handleSubmit}
          className="bg-card dark:bg-muted rounded-2xl shadow-xs p-4 space-y-3 border border-primary/20 dark:border-primary/10"
        >
          <h3 className="text-sm font-semibold">
            {TYPE_LABELS[form.amendment_type]}
          </h3>
          {error && (
            <div className="flex items-center gap-2 text-sm text-destructive bg-destructive/10 dark:bg-red-900/30 dark:text-red-300 rounded-lg px-3 py-2">
              <AlertCircle className="w-4 h-4" /> {error}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">
                Data wejścia w życie
              </span>
              <input
                type="date"
                value={form.effective_date}
                onChange={(e) => setForm({ ...form, effective_date: e.target.value })}
                className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
              />
            </label>

            {(form.amendment_type === "extension" ||
              form.amendment_type === "early_termination") && (
              <label className="block">
                <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">
                  {form.amendment_type === "extension"
                    ? "Nowa data zakończenia"
                    : "Data faktycznego zakończenia"}
                </span>
                <input
                  type="date"
                  value={form.new_end_date}
                  onChange={(e) =>
                    setForm({ ...form, new_end_date: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                />
              </label>
            )}
          </div>

          {form.amendment_type === "rate_change" && canManageFinance && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">
                  Nowa stawka kandydata
                </span>
                <input
                  type="number"
                  step="0.001"
                  value={form.new_rate_candidate}
                  onChange={(e) =>
                    setForm({ ...form, new_rate_candidate: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                />
              </label>
              <label className="block">
                <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">
                  Nowa stawka klienta
                </span>
                <input
                  type="number"
                  step="0.001"
                  value={form.new_rate_client}
                  onChange={(e) =>
                    setForm({ ...form, new_rate_client: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                />
              </label>
            </div>
          )}

          {form.amendment_type === "scope_change" && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="block">
                <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">
                  Nowy projekt
                </span>
                <input
                  type="text"
                  value={form.new_project_name}
                  onChange={(e) =>
                    setForm({ ...form, new_project_name: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                />
              </label>
              <label className="block">
                <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">
                  Nowy zespół
                </span>
                <input
                  type="text"
                  value={form.new_team_name}
                  onChange={(e) =>
                    setForm({ ...form, new_team_name: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
                />
              </label>
            </div>
          )}

          <label className="block">
            <span className="block text-xs text-muted-foreground dark:text-muted-foreground mb-1">
              Powód / uwagi
            </span>
            <textarea
              rows={2}
              value={form.reason}
              onChange={(e) => setForm({ ...form, reason: e.target.value })}
              className="w-full px-3 py-2 border border-border dark:border-border rounded-lg text-sm bg-card dark:bg-muted"
            />
          </label>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setShowForm(false);
                setForm(emptyAmendmentForm());
                setError("");
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
              {createMutation.isPending ? "Zapisywanie…" : "Zapisz aneks"}
            </button>
          </div>
        </form>
      )}

      {viewState === "loading" ? (
        <div className="text-sm text-muted-foreground flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Ładowanie aneksów…
        </div>
      ) : viewState === "forbidden" ||
        viewState === "not_found" ||
        viewState === "error" ? (
        <QueryStateNotice
          state={viewState}
          onRetry={() => void amendmentsQuery.refetch()}
        />
      ) : amendments.length === 0 ? (
        <div className="text-sm text-muted-foreground italic bg-card dark:bg-muted rounded-2xl p-8 text-center shadow-xs">
          {readOnly ? (
            "Brak aneksów."
          ) : (
            <>
              Brak aneksów — użyj przycisków powyżej, żeby przedłużyć,
              {canManageFinance ? " zmienić stawkę," : ""} zmienić zakres lub
              zakończyć kontrakt wcześniej.
            </>
          )}
        </div>
      ) : (
        <ol className="space-y-3">
          {amendments.map((a) => {
            const Icon = TYPE_ICON[a.amendment_type] ?? CalendarPlus;
            return (
              <li
                key={a.id}
                className="bg-card dark:bg-muted rounded-2xl shadow-xs p-4"
              >
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-full bg-primary/10 dark:bg-primary/10 flex items-center justify-center text-primary shrink-0">
                    <Icon className="w-4 h-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="font-medium">{TYPE_LABELS[a.amendment_type]}</span>
                      <span className="text-xs text-muted-foreground dark:text-muted-foreground">
                        Wchodzi w życie {formatDate(a.effective_date)}
                      </span>
                    </div>
                    {a.reason && (
                      <p className="text-sm text-muted-foreground dark:text-muted-foreground mt-1">
                        {a.reason}
                      </p>
                    )}
                    <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs [&>*]:min-w-0">
                      {a.old_values && (
                        <div>
                          <div className="text-muted-foreground uppercase tracking-wide">Przed</div>
                          <pre className="mt-1 bg-muted dark:bg-card/50 rounded p-2 overflow-x-auto">
                            {JSON.stringify(a.old_values, null, 2)}
                          </pre>
                        </div>
                      )}
                      {a.new_values && (
                        <div>
                          <div className="text-muted-foreground uppercase tracking-wide">Po</div>
                          <pre className="mt-1 bg-emerald-50 dark:bg-emerald-900/20 rounded p-2 overflow-x-auto">
                            {JSON.stringify(a.new_values, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground mt-2">
                      {formatDate(a.created_at)}
                      {a.created_by_email && ` · ${a.created_by_email}`}
                    </div>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
