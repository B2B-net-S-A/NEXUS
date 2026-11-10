"use client";

// Finanse → Rozliczenia → plan miesiąca (roadmapa E5.3, E5.4): poprzedni miesiąc,
// reszta puli po nim i plan (RCP z planowanymi dniami). Plan przyjmujemy po
// przyjęciu poprzedniego miesiąca i nie ponad resztę puli.
import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useAcceptBatch, useEstimates, type EstimateRow } from "@/lib/api/client-settlements";

import { STATUS, mdText, monthLabel, pln } from "./format";

function planCell(r: EstimateRow) {
  if (r.over_pool) return <StatusDot tone="danger">Ponad pulę o {mdText(r.over_pool)} MD</StatusDot>;
  if (r.plan_status === "missing") return <StatusDot tone="neutral">Brak planu</StatusDot>;
  if (r.plan_status === "ok") return <StatusDot tone="info">Do przyjęcia</StatusDot>;
  return <StatusDot tone={STATUS[r.plan_status].tone}>{STATUS[r.plan_status].label}</StatusDot>;
}

interface EstimatesViewProps {
  clientId: number;
  month: string;
  canWrite: boolean;
  onOpen: (contractId: number) => void;
}

export function EstimatesView({ clientId, month, canWrite, onOpen }: EstimatesViewProps) {
  const query = useEstimates(clientId, month);
  const batch = useAcceptBatch();
  const { showSuccess, showError } = useToast();

  if (query.isError) {
    return (
      <QueryStateNotice state="error" description={apiErrorMessage(query.error, "Nie udało się pobrać planów.")} onRetry={() => query.refetch()} />
    );
  }
  if (!query.isSuccess) {
    return <div className="py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>;
  }
  const data = query.data;
  const previous = monthLabel(data.previous_month);
  const ready = data.rows.filter((r) => r.plan_status === "ok" && !r.over_pool && r.previous_status === "accepted").length;

  async function onBatch() {
    try {
      const { accepted } = await batch.mutateAsync({ clientId, month, kind: "estimate" });
      showSuccess(`Przyjęto plany: ${accepted}.`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się przyjąć planów."));
    }
  }

  if (!data.enabled) {
    return (
      <p className="rounded-xl border bg-card px-3 py-6 text-center text-sm text-muted-foreground">
        {data.client_name} nie ma estymacji za {monthLabel(month)}. Włącza ją reguła „Estymacja” w regułach klienta.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="max-w-[80ch] text-sm text-muted-foreground">
          Estymacja to zwykłe RCP z planowanymi dniami, przysłane przed końcem miesiąca. Najpierw przyjmujemy {previous} i
          zdejmujemy MD, potem plan, który nie może przekroczyć tego, co zostało.
        </p>
        {canWrite ? (
          <Button size="sm" disabled={ready === 0 || batch.isPending} onClick={onBatch}>
            Przyjmij plany bez uwag ({ready})
          </Button>
        ) : null}
      </div>
      <div className="overflow-x-auto rounded-xl border bg-card">
        <table className="w-full min-w-[820px] table-fixed text-[13px]">
          <colgroup>
            <col className="w-[25%]" />
            <col className="w-[17%]" />
            <col className="w-[11%]" />
            <col className="w-[10%]" />
            <col className="w-[19%]" />
            {data.can_see_amounts ? <col className="w-[18%]" /> : null}
          </colgroup>
          <thead className="border-b bg-muted/40 text-left text-[11px] text-muted-foreground">
            <tr>
              <th className="px-3 py-1.5 font-medium">Osoba</th>
              <th className="px-2 py-1.5 font-medium">{previous}</th>
              <th className="px-2 py-1.5 text-right font-medium">Zostało MD</th>
              <th className="px-2 py-1.5 text-right font-medium">Plan</th>
              <th className="px-2 py-1.5 font-medium">Plan {monthLabel(month).split(" ")[0]}</th>
              {data.can_see_amounts ? <th className="px-3 py-1.5 text-right font-medium">Do faktury</th> : null}
            </tr>
          </thead>
          <tbody className="divide-y">
            {data.rows.map((r) => (
              <tr
                key={r.contract_id}
                onClick={() => (r.plan_status !== "missing" ? onOpen(r.contract_id) : undefined)}
                className={r.plan_status !== "missing" ? "cursor-pointer hover:bg-muted/40" : undefined}
              >
                <td className="truncate px-3 py-1.5">
                  <span className="block truncate font-medium">{r.person}</span>
                  <span className="block truncate text-[11px] text-muted-foreground">{r.order_number ?? "Brak numeru zamówienia"}</span>
                </td>
                <td className="px-2 py-1.5">
                  <StatusDot tone={STATUS[r.previous_status].tone}>
                    {STATUS[r.previous_status].label}
                    {r.previous_md ? `, ${mdText(r.previous_md)} MD` : ""}
                  </StatusDot>
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">{mdText(r.remaining_after_previous)}</td>
                <td className="px-2 py-1.5 text-right tabular-nums">{mdText(r.plan_md)}</td>
                <td className="px-2 py-1.5">{planCell(r)}</td>
                {data.can_see_amounts ? <td className="px-3 py-1.5 text-right tabular-nums">{pln(r.to_invoice)}</td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Gdy ktoś przepracuje mniej, różnica schodzi na fakturze za kolejny miesiąc, bez korekty. Więcej niż w planie nie przyjmujemy,
        bo zjadłoby MD z nowego zamówienia.
      </p>
    </div>
  );
}
