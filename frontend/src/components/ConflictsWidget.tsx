"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, Loader2, Plus, X } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { phase5Api, type ConflictRow, type ConflictType } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CONFLICT_STATE_BADGE,
  CONFLICT_STATE_LABELS,
  CONFLICT_TYPE_BADGE,
  CONFLICT_TYPE_LABELS,
  CONFLICT_TYPES,
  canSubmitDeactivation,
  conflictKeys,
  conflictState,
  conflictTypeLabel,
  expiresAtIso,
  formatConflictDate,
  formatExpiry,
  minExpiryDateInput,
  validateConflictForm,
  type ConflictFormErrors,
  type ConflictFormValues,
} from "@/lib/conflicts";
import { hasSectionAccess } from "@/lib/section-access";
import { cn } from "@/lib/utils";
import { hasRole, useAuthStore } from "@/store/auth";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";

interface Props {
  candidateId: number;
  /** When true and there are no conflicts (and the add-form is closed),
   *  collapse to a single compact "Dodaj konflikt" link instead of a full empty
   *  card — keeps the panel footer quiet while preserving the add affordance.
   *  A FAILED load never collapses: failure must not render as emptiness. */
  hideWhenEmpty?: boolean;
}

const EMPTY_FORM: ConflictFormValues = {
  client_id: "",
  type: "blacklist",
  reason: "",
  expires_on: "",
};

const FIELD_CLASS =
  "w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm text-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="mt-1 text-[13px] text-destructive">
      {message}
    </p>
  );
}

/**
 * Lustro bramki zapisu (`require_candidate_write` + `ManagerOrAdmin`): admin albo
 * Delivery Lead z zapisem w sekcji Sourcing lub Pipeline. Reszta ról widzi listę,
 * ale nie dostaje formularza, który kończyłby się 403.
 */
function canManageConflicts(
  user: Parameters<typeof hasRole>[0],
  isImpersonating: boolean,
): boolean {
  return (
    !isImpersonating &&
    hasRole(user, "admin", "delivery_lead") &&
    (hasSectionAccess(user, "sourcing", "write") ||
      hasSectionAccess(user, "pipeline", "write"))
  );
}

/**
 * Konflikty kandydata z klientami. Od 17.09.2026 konflikt jest OSTRZEŻENIEM
 * (kandydat widoczny i przypisywalny z plakietką), nie blokadą. Wygaśnięcie
 * NIE przełącza `active` — wiersz zostaje historią ze stanem „Wygasł".
 */
export function ConflictsWidget({ candidateId, hideWhenEmpty = false }: Props) {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const isImpersonating = useAuthStore((state) => state.realUser !== null);
  const canManage = canManageConflicts(user, isImpersonating);
  const [showForm, setShowForm] = useState(false);
  const [showInactive, setShowInactive] = useState(false);
  const [form, setForm] = useState<ConflictFormValues>(EMPTY_FORM);
  const [formErrors, setFormErrors] = useState<ConflictFormErrors>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [deactivatingId, setDeactivatingId] = useState<number | null>(null);
  const [deactivationReason, setDeactivationReason] = useState("");
  const [deactivationError, setDeactivationError] = useState<string | null>(null);

  const conflictsQuery = useQuery({
    queryKey: conflictKeys.candidate(candidateId, showInactive),
    queryFn: () =>
      phase5Api.conflicts.list(candidateId, !showInactive).then((r) => r.data),
  });

  const clientsQuery = useQuery({
    queryKey: ["clients-lookup"],
    queryFn: () => phase5Api.clientsLookup().then((r) => r.data),
    enabled: showForm,
    staleTime: 5 * 60_000,
  });

  const rows: ConflictRow[] = conflictsQuery.data ?? [];
  const viewState = resolveViewState({
    isLoading: conflictsQuery.isPending,
    isError: conflictsQuery.isError,
    error: conflictsQuery.error,
    isEmpty: rows.length === 0,
    isSuccess: conflictsQuery.isSuccess,
  });

  const createMutation = useMutation({
    mutationFn: (values: ConflictFormValues) =>
      phase5Api.conflicts.create(candidateId, {
        client_id: Number(values.client_id),
        type: values.type,
        reason: values.reason.trim() || undefined,
        expires_at: expiresAtIso(values.expires_on),
      }),
    onSuccess: async () => {
      setForm(EMPTY_FORM);
      setFormErrors({});
      setServerError(null);
      setShowForm(false);
      await queryClient.invalidateQueries({ queryKey: conflictKeys.all });
    },
    onError: (error: unknown) => {
      setServerError(apiErrorMessage(error, "Nie udało się zapisać konfliktu."));
    },
  });

  const deactivateMutation = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      phase5Api.conflicts.deactivate(id, { reason }),
    onSuccess: async () => {
      setDeactivatingId(null);
      setDeactivationReason("");
      setDeactivationError(null);
      await queryClient.invalidateQueries({ queryKey: conflictKeys.all });
    },
    onError: (error: unknown) => {
      setDeactivationError(
        apiErrorMessage(error, "Nie udało się dezaktywować konfliktu."),
      );
    },
  });

  const updateForm = <K extends keyof ConflictFormValues>(
    key: K,
    value: ConflictFormValues[K],
  ) => {
    setForm((f) => ({ ...f, [key]: value }));
    setFormErrors((e) => ({ ...e, [key]: undefined }));
    setServerError(null);
  };

  const handleCreate = () => {
    const errors = validateConflictForm(form);
    setFormErrors(errors);
    setServerError(null);
    if (Object.values(errors).some(Boolean)) return;
    createMutation.mutate(form);
  };

  const toggleForm = () => {
    setShowForm((v) => !v);
    setFormErrors({});
    setServerError(null);
  };

  const startDeactivation = (id: number) => {
    setDeactivatingId(id);
    setDeactivationReason("");
    setDeactivationError(null);
  };

  const cancelDeactivation = () => {
    setDeactivatingId(null);
    setDeactivationReason("");
    setDeactivationError(null);
  };

  // Collapsed empty state for the candidate-panel footer — ONLY on a real,
  // successful empty result. Loading renders nothing; an error renders the card.
  if (hideWhenEmpty && !showForm && !showInactive) {
    if (viewState === "loading") return null;
    if (viewState === "empty") {
      if (!canManage) return null;
      return (
        <button
          type="button"
          onClick={() => setShowForm(true)}
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-primary"
        >
          <Plus className="h-3.5 w-3.5" />
          Dodaj konflikt
        </button>
      );
    }
  }

  const activeCount = rows.filter((r) => conflictState(r) === "active").length;
  const clients = clientsQuery.data ?? [];
  const minDate = minExpiryDateInput();

  return (
    <div className="rounded-lg border border-border bg-card p-4 dark:bg-muted">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 font-medium text-foreground">
          <AlertOctagon className="h-4 w-4 text-warning" />
          Konflikty z klientami ({activeCount})
        </h3>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowInactive((v) => !v)}
            aria-pressed={showInactive}
            className="text-xs text-muted-foreground hover:text-foreground hover:underline"
          >
            {showInactive ? "Ukryj nieaktywne" : "Pokaż nieaktywne"}
          </button>
          {canManage && (
            <button
              type="button"
              onClick={toggleForm}
              className="flex items-center gap-1 text-xs text-primary hover:underline"
              data-testid="conflict-add-toggle"
            >
              <Plus className="h-3 w-3" />
              {showForm ? "Anuluj" : "Dodaj konflikt"}
            </button>
          )}
        </div>
      </div>

      <p className="mb-3 text-xs text-muted-foreground">
        Konflikt jest ostrzeżeniem — kandydata nadal można zaproponować klientowi,
        ale rekruter zobaczy plakietkę z powodem.
      </p>

      {canManage && showForm && (
        <div className="mb-3 space-y-2 rounded-md bg-muted p-3 dark:bg-card/40">
          <div className="grid grid-cols-1 gap-2 md:grid-cols-5">
            <div>
              <label htmlFor={`conflict-client-${candidateId}`} className="sr-only">
                Klient
              </label>
              <select
                id={`conflict-client-${candidateId}`}
                value={form.client_id}
                onChange={(e) => updateForm("client_id", e.target.value)}
                aria-invalid={Boolean(formErrors.client_id)}
                aria-describedby={
                  formErrors.client_id ? `conflict-client-error-${candidateId}` : undefined
                }
                className={FIELD_CLASS}
              >
                <option value="">
                  {clientsQuery.isPending ? "Wczytywanie klientów…" : "-- klient --"}
                </option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              {clientsQuery.isError && (
                <p role="alert" className="mt-1 text-[13px] text-destructive">
                  {apiErrorMessage(clientsQuery.error, "Nie udało się wczytać listy klientów.")}
                </p>
              )}
              <FieldError
                id={`conflict-client-error-${candidateId}`}
                message={formErrors.client_id}
              />
            </div>
            <div>
              <label htmlFor={`conflict-type-${candidateId}`} className="sr-only">
                Typ konfliktu
              </label>
              <select
                id={`conflict-type-${candidateId}`}
                value={form.type}
                onChange={(e) => updateForm("type", e.target.value as ConflictType)}
                className={FIELD_CLASS}
              >
                {CONFLICT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {CONFLICT_TYPE_LABELS[t]}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor={`conflict-reason-${candidateId}`} className="sr-only">
                Powód
              </label>
              <input
                id={`conflict-reason-${candidateId}`}
                placeholder="Powód (opcjonalnie)"
                value={form.reason}
                onChange={(e) => updateForm("reason", e.target.value)}
                className={FIELD_CLASS}
              />
            </div>
            <div>
              <label htmlFor={`conflict-expires-${candidateId}`} className="sr-only">
                {form.type === "nda"
                  ? "Data wygaśnięcia (wymagana dla NDA)"
                  : "Data wygaśnięcia (opcjonalnie)"}
              </label>
              <input
                id={`conflict-expires-${candidateId}`}
                type="date"
                min={minDate}
                required={form.type === "nda"}
                value={form.expires_on}
                onChange={(e) => updateForm("expires_on", e.target.value)}
                aria-invalid={Boolean(formErrors.expires_on)}
                aria-describedby={
                  formErrors.expires_on ? `conflict-expires-error-${candidateId}` : undefined
                }
                title={form.type === "nda" ? "Wygasa (wymagane dla NDA)" : "Wygasa (opcjonalnie)"}
                className={FIELD_CLASS}
              />
              <FieldError
                id={`conflict-expires-error-${candidateId}`}
                message={formErrors.expires_on}
              />
            </div>
            <Button
              type="button"
              size="sm"
              onClick={handleCreate}
              disabled={createMutation.isPending}
              data-testid="conflict-save"
              className="h-auto self-start py-1.5"
            >
              {createMutation.isPending ? "Zapisuję…" : "Zapisz"}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            {form.type === "nda"
              ? "NDA wymaga daty wygaśnięcia — konflikt obowiązuje do końca tego dnia."
              : "Data wygaśnięcia jest opcjonalna; bez niej konflikt obowiązuje do dezaktywacji."}
          </p>
          {serverError && (
            <p role="alert" className="text-[13px] text-destructive">
              {serverError}
            </p>
          )}
        </div>
      )}

      {viewState === "loading" ? (
        <div className="flex justify-center py-4">
          <Loader2
            className="h-4 w-4 animate-spin text-muted-foreground"
            aria-label="Wczytywanie konfliktów"
          />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <QueryStateNotice
          state={viewState as "forbidden" | "not_found" | "error"}
          description={
            viewState === "error"
              ? "Nie udało się wczytać konfliktów. Kandydat może je mieć — spróbuj ponownie."
              : undefined
          }
          onRetry={() => void conflictsQuery.refetch()}
          className="py-6"
        />
      ) : viewState === "empty" ? (
        <p className="text-sm text-muted-foreground">
          {showInactive ? "Brak konfliktów." : "Brak aktywnych konfliktów."}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {rows.map((c) => {
            const state = conflictState(c);
            const expiry = formatExpiry(c.expires_at);
            const isDeactivating = deactivatingId === c.id;
            return (
              <li
                key={c.id}
                className={cn(
                  "rounded-md border border-border px-3 py-2 text-sm",
                  // Wygasłe i nieaktywne (widoczne po „Pokaż nieaktywne") są
                  // wyszarzone — obowiązuje tylko stan `active`.
                  state !== "active" && "bg-muted/40 opacity-75",
                )}
                data-testid={`conflict-row-${c.id}`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={cn(
                      "rounded-full border px-2 py-0.5 text-xs",
                      CONFLICT_TYPE_BADGE[c.type] ?? "border-border bg-muted text-muted-foreground",
                    )}
                  >
                    {conflictTypeLabel(c)}
                  </span>
                  <span className="font-medium text-foreground">
                    {c.client_name ?? `Klient #${c.client_id}`}
                  </span>
                  {state !== "active" && (
                    <span
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-xs",
                        CONFLICT_STATE_BADGE[state],
                      )}
                    >
                      {CONFLICT_STATE_LABELS[state]}
                    </span>
                  )}
                  {expiry && state !== "inactive" && (
                    <span className="text-xs text-muted-foreground">{expiry}</span>
                  )}
                  {c.reason && (
                    <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={c.reason}>
                      {c.reason}
                    </span>
                  )}
                  {canManage && c.active && !isDeactivating && (
                    <button
                      type="button"
                      onClick={() => startDeactivation(c.id)}
                      className="ml-auto text-muted-foreground hover:text-destructive"
                      aria-label="Dezaktywuj"
                      title="Dezaktywuj konflikt"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </div>

                {(c.created_by_name || c.created_at) && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Dodano
                    {c.created_at ? ` ${formatConflictDate(c.created_at)}` : ""}
                    {c.created_by_name ? ` przez ${c.created_by_name}` : ""}
                  </p>
                )}

                {state === "inactive" && (c.deactivated_at || c.deactivation_reason) && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Dezaktywowano
                    {c.deactivated_at ? ` ${formatConflictDate(c.deactivated_at)}` : ""}
                    {c.deactivated_by_name ? ` przez ${c.deactivated_by_name}` : ""}
                    {c.deactivation_reason ? ` — ${c.deactivation_reason}` : ""}
                  </p>
                )}

                {isDeactivating && (
                  <div className="mt-2 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <label htmlFor={`conflict-deactivate-reason-${c.id}`} className="sr-only">
                        Powód dezaktywacji
                      </label>
                      <input
                        id={`conflict-deactivate-reason-${c.id}`}
                        autoFocus
                        placeholder="Powód dezaktywacji (min. 3 znaki)"
                        value={deactivationReason}
                        onChange={(e) => {
                          setDeactivationReason(e.target.value);
                          setDeactivationError(null);
                        }}
                        className={cn(FIELD_CLASS, "min-w-0 flex-1")}
                      />
                      <Button
                        type="button"
                        size="sm"
                        variant="destructive"
                        disabled={
                          !canSubmitDeactivation(deactivationReason) ||
                          deactivateMutation.isPending
                        }
                        onClick={() =>
                          deactivateMutation.mutate({
                            id: c.id,
                            reason: deactivationReason.trim(),
                          })
                        }
                      >
                        {deactivateMutation.isPending ? "Dezaktywuję…" : "Dezaktywuj"}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={cancelDeactivation}
                        disabled={deactivateMutation.isPending}
                      >
                        Anuluj
                      </Button>
                    </div>
                    {deactivationError && (
                      <p role="alert" className="text-[13px] text-destructive">
                        {deactivationError}
                      </p>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
