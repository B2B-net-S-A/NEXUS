"use client";

// Klient → Faktury: rozliczenie miesiąca dla Delivery Leada (roadmapa E5.1).
// Decyzja Artura z 09.11.2026: marżę w zł i % widzą Finanse i DL swoich klientów
// (kwoty według `can_read_client_finance`). Tu DL przyjmuje albo odrzuca koszty
// integracji, które wpisały Finanse. Moduł rozliczeń wyłączony = sekcji nie ma (404).
import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useDecideIntegrationCost,
  useDeliverySettlements,
  type IntegrationCost,
} from "@/lib/api/client-settlements";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";

import { CLIENT_INVOICE, INTEGRATION_STATUS, defaultMonth, integrationUsageText, mdText, monthLabel, pctText, pln } from "./format";

function shift(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const index = y * 12 + (m - 1) + delta;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`;
}

function quantity(positions: { quantity: string; kind: string }[]): string {
  const md = positions.filter((p) => p.kind !== "correction").reduce((sum, p) => sum + Number(p.quantity), 0);
  return mdText(String(md));
}

export function DeliverySettlementsSection({ clientId }: { clientId: number }) {
  const today = warsawToday();
  const latest = useMemo(() => defaultMonth(today), [today]);
  const [month, setMonth] = useState(latest);
  const query = useDeliverySettlements(clientId, month);
  const decide = useDecideIntegrationCost(clientId, month);
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showSuccess, showError } = useToast();
  const state = resolveViewState({ isLoading: query.isLoading, error: query.error, isSuccess: query.isSuccess });

  if (state === "not_found" || state === "forbidden") return null;
  if (state === "error") {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(query.error, "Nie udało się pobrać rozliczenia miesiąca.")}
        onRetry={() => query.refetch()}
      />
    );
  }

  async function onDecide(cost: IntegrationCost, approve: boolean) {
    const ok = await askConfirm(
      approve
        ? {
            title: `Zgoda na ${pln(cost.amount)} kosztów integracji?`,
            description: `${cost.person ?? "Konsultant"}, ${monthLabel(cost.month)}: ${cost.description}. Koszt obniży marżę miesiąca.`,
            confirmLabel: "Zgoda",
          }
        : {
            title: "Odrzucić koszt integracji?",
            description: `${cost.person ?? "Konsultant"}, ${monthLabel(cost.month)}: ${cost.description}.`,
            confirmLabel: "Odrzuć",
            variant: "destructive",
          },
    );
    if (!ok) return;
    try {
      await decide.mutateAsync({ costId: cost.id, approve });
      showSuccess(approve ? "Zgoda zapisana." : "Koszt odrzucony.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać decyzji."));
    }
  }

  const data = query.data;
  return (
    <section className="space-y-3 rounded-xl border bg-card p-4" aria-label="Rozliczenie miesiąca i marża">
      {confirmDialog}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Rozliczenie miesiąca i marża</h3>
          <p className="text-xs text-muted-foreground">Z przyjętych RCP. Marża po kosztach integracji ze zgodą DL-a.</p>
        </div>
        <div className="flex items-center gap-1">
          <Button size="icon" variant="ghost" aria-label="Poprzedni miesiąc" onClick={() => setMonth(shift(month, -1))}>
            <ChevronLeft aria-hidden className="size-4" />
          </Button>
          <span className="min-w-28 text-center text-sm font-medium">{monthLabel(month)}</span>
          <Button
            size="icon"
            variant="ghost"
            aria-label="Następny miesiąc"
            disabled={month >= latest}
            onClick={() => setMonth(shift(month, 1))}
          >
            <ChevronRight aria-hidden className="size-4" />
          </Button>
        </div>
      </div>
      {!data ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Ładowanie…</p>
      ) : (
        <>
          {data.rows.filter((r) => r.kind).length === 0 ? (
            <p className="rounded-lg bg-muted/40 px-3 py-4 text-center text-sm text-muted-foreground">
              W tym miesiącu nie ma jeszcze przyjętego RCP.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-[13px]">
                <thead className="border-b text-left text-[11px] text-muted-foreground">
                  <tr>
                    <th className="py-1.5 pr-2 font-medium">Osoba</th>
                    <th className="px-2 py-1.5 font-medium">Faktura</th>
                    <th className="px-2 py-1.5 text-right font-medium">MD</th>
                    {data.can_see_amounts ? (
                      <>
                        <th className="px-2 py-1.5 text-right font-medium">Do klienta</th>
                        <th className="px-2 py-1.5 text-right font-medium">Koszt</th>
                        <th className="px-2 py-1.5 text-right font-medium">Integracja</th>
                        <th className="py-1.5 pl-2 text-right font-medium">Marża</th>
                      </>
                    ) : null}
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {data.rows
                    .filter((r) => r.kind)
                    .map((r) => (
                      <tr key={r.contract_id}>
                        <td className="py-1.5 pr-2">
                          <span className="block font-medium">{r.person}</span>
                          <span className="block text-[11px] text-muted-foreground">
                            {[r.order_number, r.kind === "estimate" ? "z planu" : null].filter(Boolean).join(" · ")}
                          </span>
                        </td>
                        <td className="px-2 py-1.5">
                          <StatusDot tone={CLIENT_INVOICE[r.state].tone}>{CLIENT_INVOICE[r.state].label}</StatusDot>
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums">{quantity(r.positions)}</td>
                        {data.can_see_amounts ? (
                          <>
                            <td className="px-2 py-1.5 text-right tabular-nums">
                              {r.currency === "PLN" ? pln(r.net) : `${r.net ?? "–"} ${r.currency}`}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums">{pln(r.cost)}</td>
                            <td className="px-2 py-1.5 text-right tabular-nums">{r.integration_cost ? `−${pln(r.integration_cost)}` : "–"}</td>
                            <td className="py-1.5 pl-2 text-right tabular-nums">
                              <span className="block font-medium">{pln(r.margin)}</span>
                              <span className="block text-[11px] text-muted-foreground">{pctText(r.margin_pct) ?? "–"}</span>
                            </td>
                          </>
                        ) : null}
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
          {data.integration.enabled ? (
            <div className="border-t pt-3">
              <h4 className="text-sm font-semibold">Koszty integracji</h4>
              <p className="text-xs text-muted-foreground">
                Na koszt B2B{data.integration.limit ? `, do ${pln(data.integration.limit)} na konsultanta w roku` : ""}. Wpisują
                Finanse, zgodę daje DL klienta.
              </p>
              {data.integration.items.length === 0 ? (
                <p className="mt-1 text-xs text-muted-foreground">Nic nie czeka na decyzję.</p>
              ) : (
                <ul className="mt-1 divide-y text-[13px]">
                  {data.integration.items.map((cost) => (
                    <li key={cost.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                      <span className="min-w-0 flex-1">
                        <span className="block font-medium">
                          {cost.person} · {monthLabel(cost.month)} · {pln(cost.amount)}
                        </span>
                        <span className="block text-xs text-muted-foreground">{cost.description}</span>
                        {cost.usage ? (
                          <span className="block text-[11px] text-muted-foreground tabular-nums">{integrationUsageText(cost.usage)}</span>
                        ) : null}
                      </span>
                      {cost.status === "pending" && data.can_decide ? (
                        <span className="flex gap-1.5">
                          <Button size="sm" disabled={decide.isPending} onClick={() => onDecide(cost, true)}>
                            Zgoda
                          </Button>
                          <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => onDecide(cost, false)}>
                            Odrzuć
                          </Button>
                        </span>
                      ) : (
                        <StatusDot tone={INTEGRATION_STATUS[cost.status].tone}>{INTEGRATION_STATUS[cost.status].label}</StatusDot>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
