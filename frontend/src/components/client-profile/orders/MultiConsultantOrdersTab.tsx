"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { EmptyState, QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import {
  orderGroupsApi,
  type OrderGroupExtendInput,
  type OrderGroupInput,
  type OrderGroupRead,
  type OrderGroupStatus,
  type OrderLineRead,
  type SwapConsultantInput,
} from "@/lib/api/orderGroups";
import { countPl } from "@/lib/plural-pl";
import {
  canManageMultiConsultantOrders,
  canManageOrderLifecycle,
  useAuthStore,
} from "@/store/auth";

import { ConsultantLineModal, type LineFormValues } from "./ConsultantLineModal";
import { EndOrderGroupModal } from "./EndOrderGroupModal";
import { ExtendOrderGroupModal } from "./ExtendOrderGroupModal";
import { OrderGroupCard } from "./OrderGroupCard";
import { OrderGroupFormModal } from "./OrderGroupFormModal";
import { SwapConsultantModal } from "./SwapConsultantModal";

/** Wyciąga czytelny komunikat z odpowiedzi API (detail bywa stringiem lub obiektem). */
function apiError(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data
    ?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "code" in detail) {
    const code = (detail as { code?: string }).code;
    if (code === "finance_fields_forbidden") {
      return (
        "Stawki linii może ustawiać administrator albo Delivery Lead " +
        "przypisany do tego klienta."
      );
    }
  }
  return fallback;
}

type MainOrderGroupStatus = Exclude<OrderGroupStatus, "scheduled">;
type PillKey = "all" | MainOrderGroupStatus;

const PILLS: Array<{ key: PillKey; label: string }> = [
  { key: "all", label: "Wszystkie" },
  { key: "active", label: "Aktywne" },
  { key: "completed", label: "Zakończeni" },
  { key: "exhausted", label: "Wyczerpane" },
];

interface Props {
  clientId: number;
  /** Czy u tego klienta wolno zakładać zamówienia KOSZTOWE.
   *
   *  Flagę liczy SERWER (env `COST_ORDER_CLIENT_IDS`) i przekazuje ją profil
   *  klienta, który i tak ma już pobrany rekord. Front nie trzyma kopii listy
   *  klientów — byłaby nieaktualna od pierwszej zmiany w Coolify — ani nie
   *  robi drugiego zapytania o ten sam obiekt. */
  costOrdersEnabled?: boolean;
}

/**
 * Zakładka „Zamówienia" dla klientów rozliczanych w T&M na MD
 * (BIK / Polkomtel / BNP). Pozostali klienci renderują niezmieniony
 * `OrdersAndContractsTab` — wybór następuje w `app/clients/[id]/page.tsx`
 * na podstawie flagi z API, nie na podstawie kopii listy klientów we froncie.
 */
export function MultiConsultantOrdersTab({
  clientId,
  costOrdersEnabled = false,
}: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const user = useAuthStore((s) => s.user);
  const canManage = canManageMultiConsultantOrders(user);
  const canLifecycle = canManageOrderLifecycle(user);

  const [pill, setPill] = useState<PillKey>("all");
  const [groupModal, setGroupModal] = useState<{ open: boolean; group: OrderGroupRead | null }>(
    { open: false, group: null },
  );
  const [lineModal, setLineModal] = useState<{
    open: boolean;
    group: OrderGroupRead | null;
    line: OrderLineRead | null;
  }>({ open: false, group: null, line: null });
  const [swapModal, setSwapModal] = useState<{
    open: boolean;
    group: OrderGroupRead | null;
    line: OrderLineRead | null;
  }>({ open: false, group: null, line: null });
  const [endModal, setEndModal] = useState<{ open: boolean; group: OrderGroupRead | null }>({
    open: false,
    group: null,
  });
  const [extendModal, setExtendModal] = useState<{
    open: boolean;
    group: OrderGroupRead | null;
  }>({ open: false, group: null });
  const [formError, setFormError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["client-order-groups", clientId],
    queryFn: async () => (await orderGroupsApi.list(clientId)).data,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["client-order-groups", clientId] });
    queryClient.invalidateQueries({ queryKey: ["order-group-events", clientId] });
    queryClient.invalidateQueries({ queryKey: ["contract-documents"] });
  };

  const saveGroup = useMutation({
    mutationFn: async ({
      values,
      file,
    }: {
      values: OrderGroupInput;
      file: File | null;
    }) => {
      let saved: OrderGroupRead;
      if (groupModal.group) {
        saved = (
          await orderGroupsApi.update(clientId, groupModal.group.id, {
            order_number: values.order_number,
            start_date: values.start_date,
            end_date: values.end_date,
            notes: values.notes,
            ...(values.budget_amount != null
              ? { budget_amount: values.budget_amount }
              : {}),
          })
        ).data;
      } else {
        saved = (await orderGroupsApi.create(clientId, values)).data;
      }
      if (file) {
        saved = (await orderGroupsApi.replaceFile(clientId, saved.id, file)).data;
      }
      return saved;
    },
    onSuccess: () => {
      setGroupModal({ open: false, group: null });
      setFormError(null);
      invalidate();
      showToast("Zapisano zamówienie", "success");
    },
    onError: (err) => setFormError(apiError(err, "Nie udało się zapisać zamówienia.")),
  });

  const saveLine = useMutation({
    mutationFn: async (values: LineFormValues) => {
      const group = lineModal.group;
      if (!group) throw new Error("Brak zamówienia");
      if (lineModal.line) {
        return (
          await orderGroupsApi.updateLine(clientId, group.id, lineModal.line.id, {
            rate_cost: values.rate_cost,
            rate_revenue: values.rate_revenue,
            ...(values.input_mode ? { input_mode: values.input_mode } : {}),
            ...(values.input_value != null
              ? { input_value: values.input_value }
              : {}),
            end_date: values.end_date,
          })
        ).data;
      }
      return (await orderGroupsApi.addLine(clientId, group.id, values)).data;
    },
    onSuccess: () => {
      setLineModal({ open: false, group: null, line: null });
      setFormError(null);
      invalidate();
      showToast("Zapisano linię konsultanta", "success");
    },
    onError: (err) => setFormError(apiError(err, "Nie udało się zapisać linii.")),
  });

  const adjustRemaining = useMutation({
    mutationFn: async (mdRemaining: number) => {
      const group = lineModal.group;
      const line = lineModal.line;
      if (!group || !line) throw new Error("Brak linii");
      return (
        await orderGroupsApi.updateLine(clientId, group.id, line.id, {
          md_remaining: mdRemaining,
        })
      ).data;
    },
    onSuccess: () => {
      setLineModal({ open: false, group: null, line: null });
      setFormError(null);
      invalidate();
      showToast("Skorygowano pozostałe MD", "success");
    },
    onError: (err) => setFormError(apiError(err, "Nie udało się skorygować MD.")),
  });

  const swap = useMutation({
    mutationFn: async (values: SwapConsultantInput) => {
      const group = swapModal.group;
      const line = swapModal.line;
      if (!group || !line) throw new Error("Brak linii");
      return (await orderGroupsApi.swapLine(clientId, group.id, line.id, values)).data;
    },
    onSuccess: () => {
      setSwapModal({ open: false, group: null, line: null });
      setFormError(null);
      invalidate();
      showToast("Zamieniono kontraktora", "success");
    },
    onError: (err) => setFormError(apiError(err, "Nie udało się zamienić kontraktora.")),
  });

  // ── Cykl życia ────────────────────────────────────────────────────────────

  const removeLine = useMutation({
    mutationFn: ({ groupId, lineId }: { groupId: number; lineId: number }) =>
      orderGroupsApi.removeLine(clientId, groupId, lineId),
    onSuccess: () => {
      invalidate();
      showToast("Usunięto konsultanta z zamówienia", "success");
    },
    onError: (err) =>
      showToast(apiError(err, "Nie udało się usunąć konsultanta."), "error"),
  });

  const removeGroup = useMutation({
    mutationFn: (groupId: number) => orderGroupsApi.remove(clientId, groupId),
    onSuccess: () => {
      invalidate();
      showToast("Usunięto zamówienie", "success");
    },
    onError: (err) =>
      showToast(apiError(err, "Nie udało się usunąć zamówienia."), "error"),
  });

  const closeGroup = useMutation({
    mutationFn: (values: { closure_date: string; closure_reason: string | null }) => {
      const group = endModal.group;
      if (!group) throw new Error("Brak zamówienia");
      return orderGroupsApi.close(clientId, group.id, values);
    },
    onSuccess: () => {
      setEndModal({ open: false, group: null });
      setFormError(null);
      invalidate();
      showToast("Zamówienie zakończone", "success");
    },
    onError: (err) => setFormError(apiError(err, "Nie udało się zakończyć zamówienia.")),
  });

  const reopenGroup = useMutation({
    mutationFn: (groupId: number) => orderGroupsApi.reopen(clientId, groupId),
    onSuccess: () => {
      invalidate();
      showToast("Zamówienie przywrócone", "success");
    },
    onError: (err) =>
      showToast(apiError(err, "Nie udało się przywrócić zamówienia."), "error"),
  });

  const extendGroup = useMutation({
    mutationFn: async ({
      values,
      file,
    }: {
      values: OrderGroupExtendInput;
      file: File | null;
    }) => {
      const group = extendModal.group;
      if (!group) throw new Error("Brak zamówienia");
      const created = (await orderGroupsApi.extend(clientId, group.id, values)).data;
      if (file) {
        return (await orderGroupsApi.replaceFile(clientId, created.id, file)).data;
      }
      return created;
    },
    onSuccess: () => {
      setExtendModal({ open: false, group: null });
      setFormError(null);
      invalidate();
      showToast("Utworzono przedłużenie", "success");
    },
    onError: (err) => setFormError(apiError(err, "Nie udało się utworzyć przedłużenia.")),
  });

  const groups = useMemo(() => query.data?.groups ?? [], [query.data]);
  const counts = useMemo(() => {
    const byStatus: Record<PillKey, number> = {
      all: groups.length,
      active: 0,
      completed: 0,
      exhausted: 0,
    };
    for (const group of groups) {
      if (group.status !== "scheduled") byStatus[group.status] += 1;
    }
    return byStatus;
  }, [groups]);
  const visible = useMemo(
    () => (pill === "all" ? groups : groups.filter((g) => g.status === pill)),
    [groups, pill],
  );

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-foreground">
            Zamówienia klienta
          </h2>
          <p className="text-xs text-muted-foreground">
            Jedno zamówienie może obejmować wielu konsultantów, każdego z własnym
            budżetem MD.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* `isSuccess`, nie `!isLoading && !isError` — w przerwie między
              ponowieniami dane są puste, a licznik pokazywałby „0 zamówienia",
              czyli tę samą nieprawdę co pusty stan pod spodem. */}
          {query.isSuccess ? (
            <p className="text-xs text-muted-foreground">
              {countPl(
                query.data.total_groups,
                "zamówienie",
                "zamówienia",
                "zamówień",
              )}{" "}
              ·{" "}
              {countPl(
                query.data.total_consultants,
                "konsultant",
                "konsultanci",
                "konsultantów",
              )}
            </p>
          ) : null}
          {canManage ? (
            <button
              type="button"
              onClick={() => {
                setFormError(null);
                setGroupModal({ open: true, group: null });
              }}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
            >
              <Plus className="h-4 w-4" aria-hidden="true" /> Nowe zamówienie
            </button>
          ) : null}
        </div>
      </header>

      {/* Liczniki liczone z POBRANEJ listy, nie z osobnego zapytania — kafel
          będący sumą innych liczb niż widoczne pod nim jest niemożliwy do
          zweryfikowania wzrokiem. Renderujemy je dopiero przy `isSuccess`,
          żeby „(0)" nie udawało wyniku, zanim cokolwiek wiadomo. */}
      {query.isSuccess ? (
        <div className="flex flex-wrap gap-2">
          {PILLS.map((entry) => (
            <button
              key={entry.key}
              type="button"
              onClick={() => setPill(entry.key)}
              aria-pressed={pill === entry.key}
              className={
                "rounded-full border px-3 py-1.5 text-sm transition-colors " +
                (pill === entry.key
                  ? "border-primary/40 bg-primary/10 text-primary"
                  : "border-border bg-card text-muted-foreground hover:text-foreground")
              }
            >
              {entry.label} ({counts[entry.key]})
            </button>
          ))}
        </div>
      ) : null}

      {query.isError ? (
        /* Awaria pobrania MUSI mieć własną gałąź — pusty stan czytałby się jak
           „klient nie ma zamówień", czyli jak utrata danych. */
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać zamówień tego klienta."
          onRetry={() => query.refetch()}
        />
      ) : !query.isSuccess ? (
        /* Warunek na `isSuccess`, a NIE `isLoading`: w przerwie między
           ponowieniami react-query ma `isLoading === false` i `isError ===
           false` przy pustym `data`, więc pusty stan wygrywał i ekran mówił
           „brak zamówień", zanim wiadomo było cokolwiek. */
        <p className="py-10 text-center text-sm text-muted-foreground">
          Wczytywanie zamówień…
        </p>
      ) : visible.length === 0 ? (
        <EmptyState
          title={pill === "all" ? "Brak zamówień" : "Brak wyników dla tego filtra"}
          description={
            pill === "all"
              ? "Ten klient nie ma jeszcze zamówień wielo-konsultantowych."
              : "Zmień filtr, żeby zobaczyć pozostałe zamówienia."
          }
        />
      ) : (
        <div className="flex flex-col gap-4">
          {visible.map((group) => (
            <OrderGroupCard
              key={group.id}
              clientId={clientId}
              group={group}
              canManage={canManage}
              canManageLifecycle={canLifecycle}
              onAddConsultant={(g) => {
                setFormError(null);
                setLineModal({ open: true, group: g, line: null });
              }}
              onEditGroup={(g) => {
                setFormError(null);
                setGroupModal({ open: true, group: g });
              }}
              onEditLine={(g, line) => {
                setFormError(null);
                setLineModal({ open: true, group: g, line });
              }}
              onSwapLine={(g, line) => {
                setFormError(null);
                setSwapModal({ open: true, group: g, line });
              }}
              onDeleteLine={(g, line) => {
                if (
                  !window.confirm(
                    `Czy na pewno chcesz usunąć konsultanta ${line.consultant_name} ` +
                      `z zamówienia nr ${g.order_number}? Tej operacji nie można cofnąć.`,
                  )
                ) {
                  return;
                }
                removeLine.mutate({ groupId: g.id, lineId: line.id });
              }}
              onDeleteGroup={(g) => {
                if (
                  !window.confirm(
                    `Czy na pewno chcesz usunąć całe zamówienie nr ${g.order_number} ` +
                      `wraz ze wszystkimi konsultantami? Tej operacji nie można cofnąć.`,
                  )
                ) {
                  return;
                }
                removeGroup.mutate(g.id);
              }}
              onCloseGroup={(g) => {
                setFormError(null);
                setEndModal({ open: true, group: g });
              }}
              onReopenGroup={(g) => reopenGroup.mutate(g.id)}
              onExtendGroup={(g) => {
                setFormError(null);
                setExtendModal({ open: true, group: g });
              }}
            />
          ))}
        </div>
      )}

      <OrderGroupFormModal
        open={groupModal.open}
        onOpenChange={(open) => setGroupModal((s) => ({ ...s, open }))}
        group={groupModal.group}
        clientId={clientId}
        costOrdersEnabled={costOrdersEnabled}
        submitting={saveGroup.isPending}
        error={formError}
        onSubmit={(values, file) => saveGroup.mutate({ values, file })}
        onDeleteFile={async () => {
          const group = groupModal.group;
          if (!group) return;
          await orderGroupsApi.deleteFile(clientId, group.id);
          invalidate();
          showToast("Plik PDF zamówienia usunięty", "success");
        }}
      />

      <ConsultantLineModal
        open={lineModal.open}
        onOpenChange={(open) => setLineModal((s) => ({ ...s, open }))}
        clientId={clientId}
        group={lineModal.group}
        line={lineModal.line}
        submitting={saveLine.isPending || adjustRemaining.isPending}
        error={formError}
        onSubmit={(values) => saveLine.mutate(values)}
        onAdjustRemaining={
          lineModal.line ? (md) => adjustRemaining.mutate(md) : undefined
        }
      />

      <SwapConsultantModal
        open={swapModal.open}
        onOpenChange={(open) => setSwapModal((s) => ({ ...s, open }))}
        clientId={clientId}
        group={swapModal.group}
        line={swapModal.line}
        submitting={swap.isPending}
        error={formError}
        onSubmit={(values) => swap.mutate(values)}
      />

      <EndOrderGroupModal
        open={endModal.open}
        onOpenChange={(open) => setEndModal((s) => ({ ...s, open }))}
        group={endModal.group}
        submitting={closeGroup.isPending}
        error={formError}
        onSubmit={(values) => closeGroup.mutate(values)}
      />

      <ExtendOrderGroupModal
        open={extendModal.open}
        onOpenChange={(open) => setExtendModal((s) => ({ ...s, open }))}
        clientId={clientId}
        group={extendModal.group}
        submitting={extendGroup.isPending}
        error={formError}
        onSubmit={(values, file) => extendGroup.mutate({ values, file })}
      />
    </div>
  );
}
