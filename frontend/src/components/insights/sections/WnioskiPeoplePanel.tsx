"use client";

/**
 * Odrzucenia za liczbą z „Powodów odrzuceń”. Panel z boku jak w „Źródłach”, a lista bierze
 * klasyfikację z tego samego SQL co liczba. Treści opisu tu nie ma: lista mówi „kto”.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { DetailPanel } from "@/components/ds/DetailPanel";
import { Button } from "@/components/ui/button";
import {
  insightsApi,
  insightsQueryKeys,
  type WnioskiPeopleFilter,
} from "@/lib/insights-api";
import { SectionError } from "./_shared";

const PAGE_SIZE = 40;

const DAY = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  timeZone: "Europe/Warsaw",
});

export interface WnioskiPeopleSelection extends WnioskiPeopleFilter {
  title: string;
  total: number;
}

export function WnioskiPeoplePanel({
  selection,
  onClose,
}: {
  selection: WnioskiPeopleSelection;
  onClose: () => void;
}) {
  const [limit, setLimit] = useState(PAGE_SIZE);
  const { bucket, basis, client_id } = selection;
  const filter: WnioskiPeopleFilter = { bucket, basis, client_id };

  const { data, isPending, isError, error, refetch, isFetching } = useQuery({
    queryKey: insightsQueryKeys.wnioskiPeople(filter, limit),
    queryFn: () => insightsApi.wnioskiPeople(filter, limit),
    placeholderData: keepPreviousData,
  });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const rows = data?.rows ?? [];
  const total = data?.total ?? selection.total;

  return (
    <aside
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[620px] flex-col border-l border-border bg-card shadow-xl"
      aria-label="Osoby za liczbą"
      data-testid="wnioski-people-panel"
    >
      <DetailPanel
        title={`Odrzucenia: ${selection.total.toLocaleString("pl-PL")}`}
        subtitle={selection.title}
        onClose={onClose}
        footer={
          <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <span>
              Pokazano {rows.length.toLocaleString("pl-PL")} z {total.toLocaleString("pl-PL")}
            </span>
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
          </div>
        }
      >
        <div className="grid gap-2 p-4">
          {isPending ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : isError ? (
            <SectionError label="Osoby" error={error} onRetry={() => void refetch()} />
          ) : (
            <>
              {total !== selection.total && (
                <p className="text-xs text-muted-foreground" data-testid="wnioski-people-reconcile">
                  Na liście jest {total.toLocaleString("pl-PL")}, a liczba w tabeli to{" "}
                  {selection.total.toLocaleString("pl-PL")}, bo dane zmieniły się po jej policzeniu. Odśwież widok.
                </p>
              )}
              <table className="w-full table-fixed text-xs">
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="w-[30%] py-1.5 pr-2 text-left font-medium">Osoba</th>
                    <th className="w-[14%] py-1.5 pr-2 text-left font-medium">Odrzucenie</th>
                    <th className="py-1.5 pr-2 text-left font-medium">Rekrutacja</th>
                    <th className="w-[20%] py-1.5 text-left font-medium">Klient</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((person, index) => (
                    <tr key={`${person.candidate_id}-${person.job_id}-${index}`} className="border-t border-border align-top">
                      <td className="py-1.5 pr-2">
                        <Link href={`/candidates/${person.candidate_id}`} className="font-medium text-primary hover:underline">
                          {person.name}
                        </Link>
                      </td>
                      <td className="py-1.5 pr-2 tabular-nums text-muted-foreground">
                        {DAY.format(new Date(person.rejected_at))}
                      </td>
                      <td className="truncate py-1.5 pr-2 text-muted-foreground" title={person.job_title ?? undefined}>
                        {person.job_title ?? "—"}
                      </td>
                      <td className="truncate py-1.5 text-muted-foreground" title={person.client}>
                        {person.client}
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
