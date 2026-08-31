"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { RequireRole } from "@/components/RequireRole";
import { formatDate } from "@/lib/utils";
import {
  canManageCandidateFinance,
  canViewCandidateFinance,
  useAuthStore,
} from "@/store/auth";
import {
  CalendarPlus,
  Banknote,
  LayoutGrid,
  X as StopIcon,
  Loader2,
  AlertCircle,
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

const TODAY = new Date().toISOString().slice(0, 10);

const EMPTY: FormState = {
  amendment_type: "extension",
  effective_date: TODAY,
  reason: "",
  new_end_date: "",
  new_rate_candidate: "",
  new_rate_client: "",
  new_project_name: "",
  new_team_name: "",
};

export function ContractAmendmentsTab({ contractId }: { contractId: number }) {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const canManageFinance = canManageCandidateFinance(user);
  const canViewFinance = canViewCandidateFinance(user);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [error, setError] = useState("");

  const { data, isLoading } = useQuery<Amendment[]>({
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
      setShowForm(false);
      setForm(EMPTY);
      setError("");
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? (err instanceof Error ? err.message : "Błąd"));
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (form.amendment_type === "rate_change" && !canManageFinance) {
      setShowForm(false);
      setForm(EMPTY);
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

  const amendments = (data ?? []).filter(
    (amendment) =>
      canViewFinance || amendment.amendment_type !== "rate_change",
  );

  return (
    <div className="space-y-4">
      <RequireRole roles={["admin", "delivery_lead", "tac"]}>
        {!showForm && (
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => {
                setForm({ ...EMPTY, amendment_type: "extension" });
                setShowForm(true);
              }}
              className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-2 rounded-lg text-sm font-medium"
            >
              <CalendarPlus className="w-4 h-4" /> Przedłuż
            </button>
            {canManageFinance && (
              <button
                onClick={() => {
                  setForm({ ...EMPTY, amendment_type: "rate_change" });
                  setShowForm(true);
                }}
                className="flex items-center gap-2 bg-primary hover:bg-primary/90 text-white px-3 py-2 rounded-lg text-sm font-medium"
              >
                <Banknote className="w-4 h-4" /> Zmień stawkę
              </button>
            )}
            <button
              onClick={() => {
                setForm({ ...EMPTY, amendment_type: "scope_change" });
                setShowForm(true);
              }}
              className="flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white px-3 py-2 rounded-lg text-sm font-medium"
            >
              <LayoutGrid className="w-4 h-4" /> Zmień zakres
            </button>
            <button
              onClick={() => {
                setForm({ ...EMPTY, amendment_type: "early_termination" });
                setShowForm(true);
              }}
              className="flex items-center gap-2 bg-red-600 hover:bg-red-700 text-white px-3 py-2 rounded-lg text-sm font-medium"
            >
              <StopIcon className="w-4 h-4" /> Zakończ wcześniej
            </button>
          </div>
        )}
      </RequireRole>

      {showForm && (
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
            <div className="grid grid-cols-2 gap-3">
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
                setForm(EMPTY);
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

      {isLoading ? (
        <div className="text-sm text-muted-foreground flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Ładowanie aneksów…
        </div>
      ) : amendments.length === 0 ? (
        <div className="text-sm text-muted-foreground italic bg-card dark:bg-muted rounded-2xl p-8 text-center shadow-xs">
          Brak aneksów — użyj przycisków powyżej, żeby przedłużyć,
          {canManageFinance ? " zmienić stawkę," : ""} zmienić zakres lub
          zakończyć kontrakt wcześniej.
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
                  <div className="flex-1">
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
                    <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
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
