"use client";

/**
 * Osoby za liczbą z zakładki „Źródła”. Panel z boku, nie okno: tabela zostaje na
 * miejscu (decyzja Artura 03.11.2026). Listę wyprowadza ten sam SQL co liczbę, więc
 * różnica z klikniętą liczbą oznacza zmianę danych w międzyczasie i ekran to pisze.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Download, Loader2 } from "lucide-react";

import { DetailPanel } from "@/components/ds/DetailPanel";
import { Button } from "@/components/ui/button";
import { buildInsightsCsv, downloadCsv } from "@/components/insights/PeriodPicker";
import { apiErrorMessage } from "@/lib/api-error";
import { BOARD_COLUMN_LABEL, boardColumnForEnum } from "@/lib/board-stages";
import {
  insightsApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
  type SourceMetric,
  type SourcePeopleFilter,
  type SourcePerson,
} from "@/lib/insights-api";
import { SectionError } from "./_shared";

const PAGE_SIZE = 40;
const EXPORT_LIMIT = 5000;

export const SOURCE_METRICS: { key: SourceMetric; label: string; means: string }[] = [
  { key: "people", label: "Osoby", means: "Każda osoba, która w tym okresie zgłosiła się z tego źródła." },
  { key: "applications", label: "Zgłoszenia", means: "Osoby ze zgłoszeniami w okresie. Jedna osoba może mieć kilka zgłoszeń." },
  { key: "fresh", label: "Nowi w bazie", means: "Osoby, których przed tym zgłoszeniem nie było w NEXUSIE." },
  { key: "in_process", label: "W rekrutacji", means: "Osoby z ruchem na Tablicy po zgłoszeniu, poza etapem „Z ogłoszenia”." },
  { key: "verified", label: "Zweryfikowani", means: "Osoby, które po zgłoszeniu doszły do etapu „Zweryfikowany”." },
  { key: "cv_sent", label: "CV wysłane", means: "Osoby, których CV po zgłoszeniu poszło do klienta." },
  { key: "hired", label: "Zatrudnieni", means: "Osoby zatrudnione po zgłoszeniu." },
];

export interface SourcePeopleSelection extends SourcePeopleFilter {
  title: string;
  total: number;
}

const CLOSED_LABEL: Record<string, string> = {
  rejected: "Odrzucony",
  withdrawn: "Zrezygnował",
};

function stageLabel(stage: string | null): string {
  if (!stage) return "Tylko w bazie";
  if (CLOSED_LABEL[stage]) return CLOSED_LABEL[stage];
  const column = boardColumnForEnum(stage);
  return column ? BOARD_COLUMN_LABEL[column] : stage;
}

function origin(person: SourcePerson): string {
  if (person.offer) return person.offer;
  if (person.link_job_title) return person.link_job_title;
  if (person.link_owner) return `Link: ${person.link_owner}`;
  return "Link";
}

const DAY = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  timeZone: "Europe/Warsaw",
});

function appliedOn(iso: string): string {
  return DAY.format(new Date(iso));
}

export function SourcesPeoplePanel({
  selection,
  period,
  rangeLabel,
  canExport,
  onClose,
}: {
  selection: SourcePeopleSelection;
  period: InsightsPeriodParams;
  rangeLabel: string;
  canExport: boolean;
  onClose: () => void;
}) {
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const { source, metric, offer, owner_id, job_id } = selection;
  const filter: SourcePeopleFilter = { source, metric, offer, owner_id, job_id };

  const { data, isPending, isError, error, refetch, isFetching } = useQuery({
    queryKey: insightsQueryKeys.sourcePeople(period, filter, limit),
    queryFn: () => insightsApi.sourcePeople(period, filter, limit),
    placeholderData: keepPreviousData,
  });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const column = SOURCE_METRICS.find((c) => c.key === metric);
  const rows = data?.rows ?? [];
  const total = data?.total ?? selection.total;

  const handleExport = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const all = await insightsApi.sourcePeople(period, filter, EXPORT_LIMIT);
      downloadCsv(
        `zrodla-${source}-${metric}.csv`,
        buildInsightsCsv(
          ["Osoba", "Zgłoszenie", "Ogłoszenie albo link", "Najdalszy etap", "Rekrutacja"],
          all.rows.map((person) => [
            person.name,
            appliedOn(person.applied_at),
            origin(person),
            stageLabel(person.stage),
            person.job_title,
          ]),
        ),
      );
    } catch (err) {
      setExportError(apiErrorMessage(err, "Nie udało się przygotować pliku."));
    } finally {
      setExporting(false);
    }
  };

  return (
    <aside
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[620px] flex-col border-l border-border bg-card shadow-xl"
      aria-label="Osoby za liczbą"
      data-testid="sources-people-panel"
    >
      <DetailPanel
        title={`${column?.label ?? ""}: ${selection.total.toLocaleString("pl-PL")}`}
        subtitle={`${selection.title} · ${rangeLabel}`}
        onClose={onClose}
        footer={
          <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <span>
              Pokazano {rows.length.toLocaleString("pl-PL")} z {total.toLocaleString("pl-PL")}
              {exportError ? <span className="ml-2 text-destructive">{exportError}</span> : null}
            </span>
            <div className="flex items-center gap-2">
              {rows.length < total && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={isFetching}
                  onClick={() => setLimit((current) => current + PAGE_SIZE)}
                >
                  Pokaż więcej
                </Button>
              )}
              {canExport && rows.length > 0 && (
                <Button type="button" variant="outline" size="sm" disabled={exporting} onClick={() => void handleExport()}>
                  <Download className="h-3.5 w-3.5" />
                  Eksportuj
                </Button>
              )}
            </div>
          </div>
        }
      >
        <div className="grid gap-2 p-4">
          <p className="text-xs text-muted-foreground">{column?.means}</p>
          {isPending ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : isError ? (
            <SectionError label="Osoby" error={error} onRetry={() => void refetch()} />
          ) : (
            <>
              {data.total !== selection.total && (
                <p className="text-xs text-muted-foreground" data-testid="sources-people-reconcile">
                  Na liście jest {data.total.toLocaleString("pl-PL")}, a liczba w tabeli to{" "}
                  {selection.total.toLocaleString("pl-PL")}, bo dane zmieniły się po jej policzeniu. Odśwież widok.
                </p>
              )}
              <table className="w-full table-fixed text-xs">
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="w-[27%] py-1.5 pr-2 text-left font-medium">Osoba</th>
                    <th className="w-[14%] py-1.5 pr-2 text-left font-medium">Zgłoszenie</th>
                    <th className="py-1.5 pr-2 text-left font-medium">Ogłoszenie albo link</th>
                    <th className="w-[33%] py-1.5 text-left font-medium">Najdalszy etap</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((person, index) => (
                    <tr key={`${person.candidate_id}-${index}`} className="border-t border-border align-top">
                      <td className="py-1.5 pr-2">
                        <Link href={`/candidates/${person.candidate_id}`} className="font-medium text-primary hover:underline">
                          {person.name}
                        </Link>
                      </td>
                      <td className="py-1.5 pr-2 tabular-nums text-muted-foreground">{appliedOn(person.applied_at)}</td>
                      <td className="truncate py-1.5 pr-2 text-muted-foreground" title={origin(person)}>
                        {origin(person)}
                      </td>
                      <td className="py-1.5">
                        <span className="font-medium text-foreground">{stageLabel(person.stage)}</span>
                        {person.job_title ? (
                          <span className="block truncate text-muted-foreground" title={person.job_title}>
                            {person.job_title}
                          </span>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      </DetailPanel>
    </aside>
  );
}
