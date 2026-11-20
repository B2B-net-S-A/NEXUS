"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { formatIsoDatePl as formatDate } from "@/lib/date-pl";
import { apiErrorMessage } from "@/lib/api-error";
import { useToast } from "@/components/Toast";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { resolveViewState } from "@/lib/view-state";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";
import { Loader2, Plus, Trash2, X } from "lucide-react";

interface OnboardingItem {
  id: number;
  contract_id: number;
  label: string;
  status: "pending" | "done" | "na";
  assigned_to: number | null;
  due_date: string | null;
  notes: string | null;
  order: number;
  created_at: string;
  updated_at: string;
}

// Etykiety PL zamiast surowego `pending` w podpowiedzi (audyt 24.09, N9).
export const ONBOARDING_STATUS_LABELS: Record<string, string> = {
  pending: "do zrobienia",
  done: "zrobione",
  na: "nie dotyczy",
};

/** Pozycje bez terminów i notatek układamy w dwie kolumny — tabela byłaby samymi kreskami. */
export function onboardingDetailed(items: readonly Pick<OnboardingItem, "due_date" | "notes">[]): boolean {
  return items.some((item) => item.due_date != null || Boolean(item.notes));
}

/**
 * Stara lista startowa kontraktu (lista onboardingu sprzed modułu „Wejście
 * i odejście”) jako checklista zakładki „Start i sprzęt” (wariant A,
 * 20.11.2026): pole wyboru odhacza pozycję, „Nie dotyczy” wyjmuje ją
 * z kroków, kosz usuwa po potwierdzeniu w wierszu. Postęp liczy nagłówek
 * zakładki. Bramka zapisu jest JEDNA i przychodzi z góry (`readOnly` = brak
 * uprawnienia „Kontrakty i zamówienia: tworzenie i edycja” albo tryb
 * podglądu) — bez drugiej, zagnieżdżonej bramki po roli.
 */
export function ContractOnboardingTab({
  contractId,
  readOnly = false,
}: {
  contractId: number;
  readOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const [newLabel, setNewLabel] = useState("");
  // Potwierdzenie usunięcia w wierszu zamiast `window.confirm` (N7).
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const { showToast } = useToast();
  const onMutationError = (fallback: string) => (err: unknown) =>
    showToast(apiErrorMessage(err, fallback), "error");

  const onboardingQuery = useQuery<OnboardingItem[]>({
    queryKey: ["contract-onboarding", contractId],
    queryFn: () =>
      api.get(`/api/contracts/${contractId}/onboarding`).then((r) => r.data),
  });

  // Jedno żądanie, lista domyślna po stronie serwera, blokada wiersza
  // kontraktu (audyt FE-04). Dawniej osiem osobnych POST-ów: podwójne
  // kliknięcie dublowało listę, a awaria w środku zostawiała jej połowę.
  const seedMutation = useMutation({
    mutationFn: () =>
      api
        .post<OnboardingItem[]>(`/api/contracts/${contractId}/onboarding/seed`)
        .then((r) => r.data),
    onSuccess: (items) => {
      queryClient.setQueryData(["contract-onboarding", contractId], items);
      queryClient.invalidateQueries({ queryKey: ["contract-onboarding", contractId] });
    },
    onError: onMutationError("Nie udało się wygenerować listy startowej."),
  });

  const createMutation = useMutation({
    mutationFn: (payload: { label: string; order?: number }) =>
      api.post(`/api/contracts/${contractId}/onboarding`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contract-onboarding", contractId] });
      setNewLabel("");
    },
    onError: onMutationError("Nie udało się dodać pozycji."),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: number;
      payload: Record<string, unknown>;
    }) => api.patch(`/api/contracts/${contractId}/onboarding/${id}`, payload),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["contract-onboarding", contractId] }),
    onError: onMutationError("Nie udało się zmienić statusu pozycji."),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) =>
      api.delete(`/api/contracts/${contractId}/onboarding/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["contract-onboarding", contractId] }),
    onError: onMutationError("Nie udało się usunąć pozycji."),
  });

  // Blokada synchroniczna: dwa kliknięcia w tej samej klatce (zanim React
  // zdąży wyrenderować `disabled`) nie mogą wysłać dwóch żądań.
  const seedingRef = useRef(false);
  const handleSeed = () => {
    if (seedingRef.current) return;
    seedingRef.current = true;
    seedMutation.mutate(undefined, {
      onSettled: () => {
        seedingRef.current = false;
      },
    });
  };

  const items = [...(onboardingQuery.data ?? [])].sort((a, b) => a.order - b.order);
  const viewState = resolveViewState({
    isLoading: onboardingQuery.isLoading,
    error: onboardingQuery.error,
    isSuccess: onboardingQuery.isSuccess,
    isEmpty: items.length === 0,
  });
  const isBlocked =
    viewState === "forbidden" ||
    viewState === "not_found" ||
    viewState === "error";

  const setStatus = (item: OnboardingItem, status: OnboardingItem["status"]) =>
    updateMutation.mutate({ id: item.id, payload: { status } });

  const row = (item: OnboardingItem) => {
    const done = item.status === "done";
    const na = item.status === "na";
    const late = !done && !na && item.due_date != null && item.due_date.slice(0, 10) < warsawToday();
    return (
      <li key={item.id} className="group flex min-h-10 items-center gap-3 py-1.5">
        <Checkbox
          checked={done}
          disabled={readOnly || na || updateMutation.isPending}
          onCheckedChange={(value) => setStatus(item, value === true ? "done" : "pending")}
          aria-label={`${item.label} — ${ONBOARDING_STATUS_LABELS[item.status] ?? item.status}`}
        />
        <span className="min-w-0 flex-1">
          <span className={cn("block text-[13px] text-foreground", (done || na) && "text-muted-foreground line-through")}>
            {item.label}
          </span>
          {item.notes || item.due_date ? (
            <span className="block text-[11.5px] leading-4 text-muted-foreground">
              {[item.due_date ? `termin ${formatDate(item.due_date)}` : null, item.notes].filter(Boolean).join(" · ")}
              {late ? <span className="font-medium text-destructive"> · po terminie</span> : null}
            </span>
          ) : null}
        </span>
        {na ? <span className="text-[12px] text-muted-foreground">nie dotyczy</span> : null}
        {!readOnly ? (
          <span className="flex shrink-0 items-center gap-1 pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100 focus-within:opacity-100">
            {confirmDeleteId === item.id ? (
              <span className="inline-flex items-center gap-1 text-xs">
                <span className="text-muted-foreground">Usunąć?</span>
                <button
                  type="button"
                  onClick={() =>
                    deleteMutation.mutate(item.id, {
                      onSettled: () => setConfirmDeleteId(null),
                    })
                  }
                  disabled={deleteMutation.isPending}
                  aria-label={`Potwierdź usunięcie pozycji ${item.label}`}
                  className="rounded px-2 py-1 font-medium text-destructive hover:bg-destructive/10 disabled:opacity-60"
                >
                  Usuń
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmDeleteId(null)}
                  aria-label="Anuluj usuwanie"
                  className="hit-area rounded p-1 hover:bg-muted"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </span>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => setStatus(item, na ? "pending" : "na")}
                  disabled={updateMutation.isPending}
                  aria-label={na ? `Przywróć pozycję ${item.label}` : `Nie dotyczy: ${item.label}`}
                  className="rounded px-1.5 py-0.5 text-[12px] text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  {na ? "Przywróć" : "Nie dotyczy"}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmDeleteId(item.id)}
                  className="hit-area rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                  title="Usuń"
                  aria-label={`Usuń pozycję ${item.label}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </>
            )}
          </span>
        ) : null}
      </li>
    );
  };

  // Krótka lista bez terminów: dwie kolumny (1–4 po lewej, 5–8 po prawej) mieszczą się w oknie.
  const twoColumns = !onboardingDetailed(items) && items.length > 3;
  const half = Math.ceil(items.length / 2);

  return (
    <div className="space-y-3">
      {(viewState === "forbidden" ||
        viewState === "not_found" ||
        viewState === "error") && (
        <QueryStateNotice
          state={viewState}
          onRetry={() => void onboardingQuery.refetch()}
        />
      )}

      {viewState === "empty" && !readOnly && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-muted/50 px-3 py-2.5">
          <p className="text-[13px] text-muted-foreground">
            Listy startowej jeszcze nie ma. Szablon to BHP, sprzęt, dostępy, VPN, Slack klienta, e-mail i repozytorium — potem go dopasujesz.
          </p>
          <Button type="button" size="sm" variant="outline" onClick={handleSeed} disabled={seedMutation.isPending}>
            {seedMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
            Wygeneruj z szablonu
          </Button>
        </div>
      )}

      {viewState === "empty" && readOnly && (
        <p className="text-[13px] text-muted-foreground">Listy startowej nie założono.</p>
      )}

      {viewState === "loading" ? (
        <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Wczytywanie listy…
        </p>
      ) : items.length === 0 ? null : twoColumns ? (
        <div className="grid gap-x-8 sm:grid-cols-2">
          {[items.slice(0, half), items.slice(half)].map((column, index) => (
            <ul key={index} className="divide-y divide-border/60 border-y border-border/60" aria-label="Lista startowa">
              {column.map(row)}
            </ul>
          ))}
        </div>
      ) : (
        <ul className="divide-y divide-border/60 border-y border-border/60" aria-label="Lista startowa">
          {items.map(row)}
        </ul>
      )}

      {!readOnly && !isBlocked && viewState !== "loading" && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const label = newLabel.trim();
            if (label) {
              createMutation.mutate({ label, order: items.length });
            }
          }}
          className="flex gap-2"
        >
          <label htmlFor={`onboarding-new-${contractId}`} className="sr-only">
            Nowa pozycja listy startowej
          </label>
          <input
            id={`onboarding-new-${contractId}`}
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            placeholder="Dodaj pozycję (np. „Karta dostępu do biura”)"
            className="h-8 w-0 flex-1 rounded-md border border-border bg-card px-2.5 text-[13px] placeholder:text-muted-foreground focus:border-primary focus:outline-hidden"
          />
          <Button type="submit" size="sm" variant="ghost" disabled={createMutation.isPending || !newLabel.trim()}>
            <Plus className="h-3.5 w-3.5" aria-hidden /> Dodaj
          </Button>
        </form>
      )}
    </div>
  );
}
