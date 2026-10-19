"use client";

/**
 * Zakładka „Wyniki” okna „Udostępnij rekrutację” (etap 4 linków, 19.10.2026).
 *
 * Co przyniosły linki osoby: lejek wszystkich linków i tabela per link.
 * Zgłoszenia liczą też osoby, które były już w bazie (do 19.10 nie liczyły się
 * nigdzie). Wejścia to licznik od początku istnienia linku — dat wejść nie
 * zapisujemy, więc wejścia nie zmieniają się z okresem.
 * Makieta: https://claude.ai/artifact/8aVZkzVxkVnkVVNBUDgL4h (plansza 4).
 */

import { useState } from "react";
import { Copy } from "lucide-react";

import { useToast } from "@/components/Toast";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DialogBody } from "@/components/ui/dialog";
import {
  type LinkResultRow,
  type LinkResultState,
  type LinkResultsPeriod,
  useLinkResults,
} from "@/lib/api/careerLinks";
import { copyTextToClipboard } from "@/lib/clipboard";
import { resolveViewState } from "@/lib/view-state";
import { cn } from "@/lib/utils";

const PERIODS: { value: LinkResultsPeriod; label: string }[] = [
  { value: 30, label: "30 dni" },
  { value: 90, label: "90 dni" },
  { value: 0, label: "Od początku" },
];

const STATE_LABEL: Record<LinkResultState, string> = {
  live: "działa",
  not_live: "czeka na zatwierdzenie",
  closed: "rekrutacja zamknięta",
  expired: "wygasł",
  revoked: "wycofany",
};

const STATE_VARIANT: Record<LinkResultState, "success" | "warning" | "neutral"> = {
  live: "success",
  not_live: "warning",
  closed: "neutral",
  expired: "neutral",
  revoked: "neutral",
};

const FUNNEL: { key: keyof LinkResultRow; label: string; indent?: boolean }[] = [
  { key: "applications", label: "Zgłoszenia" },
  { key: "new_candidates", label: "nowi w bazie", indent: true },
  { key: "existing_candidates", label: "już byli w bazie", indent: true },
  { key: "in_process", label: "W rekrutacji" },
  { key: "verified", label: "Zweryfikowani" },
  { key: "cv_sent", label: "CV wysłane" },
  { key: "hired", label: "Zatrudnieni" },
];

function linkName(row: LinkResultRow): string {
  if (row.kind === "recruiter") return "Mój link ogólny";
  return row.job_title || "Rekrutacja";
}

export function LinkResultsTab({ enabled }: { enabled: boolean }) {
  const [days, setDays] = useState<LinkResultsPeriod>(30);
  const query = useLinkResults(enabled, days);
  const { showSuccess, showError } = useToast();
  const data = query.data;
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: (data?.links.length ?? 0) === 0,
  });
  const totals = data?.totals;
  const scale = Math.max(totals?.applications ?? 0, 1);

  const copy = async (url: string) => {
    if (await copyTextToClipboard(url)) showSuccess("Skopiowano link.");
    else showError("Nie udało się skopiować — zaznacz adres i skopiuj ręcznie.");
  };

  return (
    <DialogBody className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-foreground">Co przyniosły Twoje linki</h3>
        <div className="flex gap-1" role="group" aria-label="Okres">
          {PERIODS.map((p) => (
            <Button
              key={p.value}
              size="sm"
              variant={days === p.value ? "secondary" : "outline"}
              aria-pressed={days === p.value}
              onClick={() => setDays(p.value)}
            >
              {p.label}
            </Button>
          ))}
        </div>
      </div>

      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Liczę wyniki linków…</p>
      ) : state === "error" || state === "forbidden" || state === "not_found" ? (
        <QueryStateNotice
          state={state === "forbidden" ? "forbidden" : "error"}
          description="Nie udało się policzyć wyników linków. To nie znaczy, że ich nie ma."
          onRetry={() => query.refetch()}
        />
      ) : state === "empty" ? (
        <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
          Nie masz jeszcze linków. Wygeneruj link w zakładce „Link do tej rekrutacji”
          albo ustaw stały adres w „Mój link ogólny”.
        </p>
      ) : data && totals ? (
        <>
          <section className="space-y-2" aria-labelledby="results-funnel-heading">
            <h4 id="results-funnel-heading" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Wszystkie Twoje linki
            </h4>
            <p className="text-sm text-foreground">
              <span className="text-lg font-semibold tabular-nums">{totals.visits}</span> wejść
              od początku · <span className="font-semibold tabular-nums">{totals.applications}</span>{" "}
              zgłoszeń {days ? `w ostatnich ${days} dniach` : "od początku"}
            </p>
            <ul className="space-y-1.5" data-testid="results-funnel">
              {FUNNEL.map((step) => {
                const value = Number(totals[step.key as keyof typeof totals] ?? 0);
                return (
                  <li
                    key={step.key}
                    className="grid grid-cols-[9.5rem_minmax(0,1fr)_2.5rem] items-center gap-3 text-sm"
                  >
                    <span className={cn("text-foreground", step.indent && "pl-3 text-muted-foreground")}>
                      {step.label}
                    </span>
                    <span className="h-3 overflow-hidden rounded bg-muted" aria-hidden="true">
                      <span
                        className="block h-full rounded bg-primary"
                        style={{ width: `${Math.round((value / scale) * 100)}%` }}
                      />
                    </span>
                    <span className="text-right font-semibold tabular-nums">{value}</span>
                  </li>
                );
              })}
            </ul>
            <p className="text-xs text-muted-foreground">
              Paski względem zgłoszeń. „W rekrutacji” i dalsze etapy liczą osobę, gdy po
              zgłoszeniu trafiła na ten etap w rekrutacji linku (link ogólny: w dowolnej).
            </p>
          </section>

          <section className="space-y-2" aria-labelledby="results-links-heading">
            <h4 id="results-links-heading" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Twoje linki
            </h4>
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[640px] text-sm" data-testid="results-links">
                <thead className="bg-muted/50 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Link</th>
                    <th className="px-3 py-2 text-right font-medium">Wejścia</th>
                    <th className="px-3 py-2 text-right font-medium">Zgłoszenia</th>
                    <th className="px-3 py-2 text-right font-medium">W rekrutacji</th>
                    <th className="px-3 py-2 text-right font-medium">Zweryfikowani</th>
                    <th className="px-3 py-2 text-right font-medium">Zatrudnieni</th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {data.links.map((row) => (
                    <tr key={`${row.kind}-${row.slug ?? row.job_id}`} className="border-t border-border">
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium text-foreground">{linkName(row)}</span>
                          <Badge size="sm" variant={STATE_VARIANT[row.state]}>
                            {STATE_LABEL[row.state]}
                          </Badge>
                        </div>
                        {row.existing_candidates > 0 ? (
                          <span className="text-xs text-muted-foreground">
                            w tym {row.existing_candidates} już w bazie
                          </span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{row.visits}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{row.applications}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{row.in_process}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{row.verified}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{row.hired}</td>
                      <td className="px-3 py-2 text-right">
                        {row.state === "live" && row.public_url ? (
                          <Button
                            size="sm"
                            variant="tertiary"
                            onClick={() => copy(row.public_url as string)}
                            aria-label={`Kopiuj link: ${linkName(row)}`}
                          >
                            <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                            Kopiuj
                          </Button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </DialogBody>
  );
}
