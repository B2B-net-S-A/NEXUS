"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  ORDER_COST_CORRECTIONS_KEY,
  decideOrderCostCorrection,
  useOrderCostCorrections,
  type CostCorrectionDecision,
  type CostPart,
  type OrderCostCorrection,
} from "@/lib/api/order-cost-corrections";
import { CALM_AMOUNT, CALM_SUBLINE } from "@/lib/calm-table";
import { monthTitlePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";

/** „01.07.2026” z ISO. */
function dayPl(iso: string | null): string {
  if (!iso) return "bez końca";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

/** „120 zł/h do 31.08.2026 · 130 zł/h od 01.09.2026”. */
export function partsText(parts: CostPart[], unit: string, currency: string): string {
  if (parts.length === 1) return formatMoney(parts[0].rate, currency, unit);
  return parts
    .map((part, index) =>
      index === 0
        ? `${formatMoney(part.rate, currency, unit)} do ${dayPl(part.to)}`
        : `${formatMoney(part.rate, currency, unit)} od ${dayPl(part.from)}`,
    )
    .join(" · ");
}

/**
 * Finanse → „Rozjazdy stawek” → „Do korekty po zmianie stawki”.
 *
 * Zakończone zamówienia ostatniego pół roku, których koszt nie zgadza się
 * z harmonogramem stawki Partnera w kontrakcie (aneks albo progresja wpisane
 * wstecz). Trwające zamówienia poprawia synchronizacja sama — tu ich nie ma.
 */
export function OrderCostCorrections({ canWrite }: { canWrite: boolean }) {
  const query = useOrderCostCorrections();
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();

  const decide = useMutation({
    mutationFn: ({ orderId, decision }: { orderId: number; decision: CostCorrectionDecision }) =>
      decideOrderCostCorrection(orderId, decision),
    onSuccess: (_data, { decision }) => {
      queryClient.invalidateQueries({ queryKey: ORDER_COST_CORRECTIONS_KEY });
      showSuccess(
        decision === "apply"
          ? "Koszt zamówienia ustawiony z kontraktu."
          : "Zostawione — zamówienie wróci na listę przy kolejnej zmianie stawki.",
      );
    },
    onError: (error) =>
      showError(apiErrorMessage(error, "Nie udało się zapisać decyzji o koszcie zamówienia.")),
  });

  async function apply(row: OrderCostCorrection) {
    const ok = await askConfirm({
      title: `Ustawić koszt zamówienia ${row.order_number} z kontraktu?`,
      description: `${row.person}: ${partsText(row.in_contract, row.unit, row.currency)}. Stawka dla klienta i faktury się nie zmieniają.`,
      confirmLabel: "Ustaw koszt z kontraktu",
    });
    if (ok) decide.mutate({ orderId: row.order_id, decision: "apply" });
  }

  if (query.isLoading) {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie listy…</p>;
  }
  if (query.isError) {
    return <QueryStateNotice state="error" onRetry={() => query.refetch()} />;
  }
  const rows = query.data?.rows ?? [];

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-foreground">Do korekty po zmianie stawki</h2>
        <p className="text-sm text-muted-foreground">
          Zakończone zamówienia, w których koszt nie zgadza się z harmonogramem stawki Partnera
          w kontrakcie · {countPl(rows.length, "zamówienie", "zamówienia", "zamówień")}
        </p>
      </div>
      {query.isSuccess && rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          Koszt zakończonych zamówień zgadza się ze stawkami w kontraktach.
        </div>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card">
          {rows.map((row) => (
            <li
              key={row.order_id}
              className="flex flex-wrap items-start justify-between gap-3 px-4 py-3"
            >
              <div className="min-w-0 flex-1 space-y-1 text-sm">
                <p className="font-medium text-foreground">
                  {row.person}
                  <span className="font-normal text-muted-foreground">
                    {" "}
                    · {row.client_name} · {row.order_number} ({dayPl(row.start_date)}–
                    {dayPl(row.end_date)})
                  </span>
                </p>
                <p className="text-muted-foreground">
                  W zamówieniu: {partsText(row.in_order, row.unit, row.currency)}
                </p>
                <p className="text-foreground">
                  Z kontraktu: {partsText(row.in_contract, row.unit, row.currency)}
                </p>
                <p className={CALM_SUBLINE}>
                  {row.months
                    .map(
                      (month) =>
                        `${monthTitlePl(month.month)}: ${formatMoney(month.diff, row.currency, row.unit)}`,
                    )
                    .join(" · ")}
                </p>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-2">
                <span className={CALM_AMOUNT} title="Szacunek przy pełnym miesiącu">
                  {formatMoney(row.estimate, row.currency)}
                </span>
                {canWrite ? (
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={decide.isPending}
                      onClick={() => decide.mutate({ orderId: row.order_id, decision: "dismiss" })}
                    >
                      Zostaw
                    </Button>
                    <Button size="sm" disabled={decide.isPending} onClick={() => apply(row)}>
                      Ustaw koszt z kontraktu
                    </Button>
                  </div>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
      {confirmDialog}
    </section>
  );
}
