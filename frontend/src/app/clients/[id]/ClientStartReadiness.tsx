"use client";

// „Start u klienta: N z M ustalone” nad częściami zakładki. Te same zapytania
// co części poniżej (ten sam klucz React Query), więc licznik nic nie pobiera
// drugi raz. Reguła: `lib/client-start-readiness.ts`.

import { Check } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { useClientPack } from "@/lib/api/client-onboarding";
import { useSettlementRule } from "@/lib/api/consultant-panel";
import { useClientStartDocs } from "@/lib/api/start-documents";
import { startReadiness, type StartPart } from "@/lib/client-start-readiness";
import { resolveViewState } from "@/lib/view-state";

interface QueryLike<T> {
  isLoading: boolean;
  isSuccess: boolean;
  error: unknown;
  data: T | undefined;
}

function partOf<T, D>(query: QueryLike<T>, enabled: boolean, pick: (data: T) => D): StartPart<D> {
  if (!enabled) return { status: "hidden" };
  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (state === "loading") return { status: "loading" };
  // Bez uprawnienia część znika z ekranu (albo zostaje sama notka), więc nie
  // wchodzi do licznika.
  if (state === "forbidden" || state === "not_found") return { status: "hidden" };
  if (state === "error" || query.data === undefined) return { status: "error" };
  return { status: "ready", data: pick(query.data) };
}

interface ClientStartReadinessProps {
  clientId: number;
  /** „Dokumenty do startu” są na ekranie (podgląd Delivery). */
  docsOn: boolean;
  /** Pakiet i sposób rozliczenia są na ekranie (moduł „Wejście i odejście” albo panel konsultanta). */
  packOn: boolean;
}

export function ClientStartReadiness({ clientId, docsOn, packOn }: ClientStartReadinessProps) {
  const documents = useClientStartDocs(clientId, docsOn);
  const settlement = useSettlementRule(clientId, packOn);
  const pack = useClientPack(clientId, packOn);
  const readiness = startReadiness({
    documents: partOf(documents, docsOn, (list) => ({
      count: list.items.length,
      notRequired: list.not_required !== null,
    })),
    settlement: partOf(settlement, packOn, (rule) => ({ mode: rule.mode })),
    pack: partOf(pack, packOn, (data) => ({
      provider: data.equipment.provider,
      place: data.first_day.place,
    })),
  });
  if (!readiness.show) return null;
  const complete = readiness.settled === readiness.total;
  return (
    <section
      aria-label="Start u klienta"
      className="mb-3 space-y-2 rounded-lg border border-border bg-card p-3"
      data-testid="client-start-readiness"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[13px] font-semibold text-foreground">Start u klienta</h3>
        <Badge variant={complete ? "success" : "warning"} className="ml-auto tabular-nums">
          {readiness.settled} z {readiness.total} ustalone
        </Badge>
      </div>
      <dl className="grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-[13px]">
        {readiness.fields.map((field) => (
          <div key={field.key} className="contents">
            <dt className="text-muted-foreground">{field.label}</dt>
            <dd className="flex min-w-0 items-center gap-1.5">
              {field.settled ? (
                <>
                  <Check className="h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
                  <span className="truncate text-foreground" title={field.value}>
                    {field.value}
                  </span>
                  <span className="sr-only">(ustalone)</span>
                </>
              ) : (
                <Badge variant="neutral">{field.value}</Badge>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
