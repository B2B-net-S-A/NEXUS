"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { EmptyState, QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import {
  orderGroupsApi,
  type OrderGroupInput,
  type OrderGroupRead,
  type OrderLineRead,
  type SwapConsultantInput,
} from "@/lib/api/orderGroups";
import { countPl } from "@/lib/plural-pl";
import { canManageMultiConsultantOrders, useAuthStore } from "@/store/auth";

import { ConsultantLineModal, type LineFormValues } from "./ConsultantLineModal";
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

interface Props {
  clientId: number;
}

/**
 * Zakładka „Zamówienia" dla klientów rozliczanych w T&M na MD
 * (BIK / Polkomtel / BNP). Pozostali klienci renderują niezmieniony
 * `OrdersAndContractsTab` — wybór następuje w `app/clients/[id]/page.tsx`
 * na podstawie flagi z API, nie na podstawie kopii listy klientów we froncie.
 */
export function MultiConsultantOrdersTab({ clientId }: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const user = useAuthStore((s) => s.user);
  const canManage = canManageMultiConsultantOrders(user);

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
  const [formError, setFormError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["client-order-groups", clientId],
    queryFn: async () => (await orderGroupsApi.list(clientId)).data,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["client-order-groups", clientId] });
    queryClient.invalidateQueries({ queryKey: ["order-group-events", clientId] });
  };

  const saveGroup = useMutation({
    mutationFn: async (values: OrderGroupInput) => {
      if (groupModal.group) {
        return (await orderGroupsApi.update(clientId, groupModal.group.id, values)).data;
      }
      return (await orderGroupsApi.create(clientId, values)).data;
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
            input_mode: values.input_mode,
            input_value: values.input_value,
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

  const groups = query.data?.groups ?? [];

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
      ) : groups.length === 0 ? (
        <EmptyState
          title="Brak zamówień"
          description="Ten klient nie ma jeszcze zamówień wielo-konsultantowych."
        />
      ) : (
        <div className="flex flex-col gap-4">
          {groups.map((group) => (
            <OrderGroupCard
              key={group.id}
              clientId={clientId}
              group={group}
              canManage={canManage}
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
            />
          ))}
        </div>
      )}

      <OrderGroupFormModal
        open={groupModal.open}
        onOpenChange={(open) => setGroupModal((s) => ({ ...s, open }))}
        group={groupModal.group}
        submitting={saveGroup.isPending}
        error={formError}
        onSubmit={(values) => saveGroup.mutate(values)}
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
    </div>
  );
}
