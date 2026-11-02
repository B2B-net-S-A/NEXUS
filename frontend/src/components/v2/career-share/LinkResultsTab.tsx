"use client";

/**
 * Zakładka „Wyniki” okna „Udostępnij rekrutację” (etap 4 linków, 19.10.2026).
 *
 * Co przyniosły linki osoby: kafle, kto się zgłosił i tabela per link w dwóch
 * grupach (link ogólny, linki do rekrutacji). Zgłoszenia liczą też osoby, które
 * były już w bazie. Wejścia w okresie liczą się z dziennych zapisów (0638), które
 * zaczynają się w dniu wdrożenia; „Od początku” czyta licznik linku.
 * Makieta: https://claude.ai/artifact/BcevDUToiG7AGHfgY86T5P (A).
 */

import Link from "next/link";
import { Fragment, useState } from "react";
import { Copy } from "lucide-react";

import { useToast } from "@/components/Toast";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DialogBody } from "@/components/ui/dialog";
import {
  type LinkResultCounts,
  type LinkResultRow,
  type LinkResultState,
  type LinkResultsPeriod,
  useLinkPeople,
  useLinkResults,
} from "@/lib/api/careerLinks";
import {
  linkPersonAppliedAt,
  linkPersonKey,
  linkPersonLinkName,
  linkPersonNow,
} from "@/lib/career-link-people";
import { copyTextToClipboard } from "@/lib/clipboard";
import { formatDate } from "./share-utils";
import { resolveViewState } from "@/lib/view-state";

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

const TILES: { key: "applications" | "new_candidates" | "in_process" | "cv_sent"; label: string }[] = [
  { key: "applications", label: "Zgłoszenia" },
  { key: "new_candidates", label: "Nowi w bazie" },
  { key: "in_process", label: "W rekrutacji" },
  { key: "cv_sent", label: "CV wysłane" },
];

const COUNT_COLUMNS: {
  key: "applications" | "in_process" | "verified" | "cv_sent" | "hired";
  label: string;
}[] = [
  { key: "applications", label: "Zgłoszenia" },
  { key: "in_process", label: "W rekrutacji" },
  { key: "verified", label: "Zweryf." },
  { key: "cv_sent", label: "CV" },
  { key: "hired", label: "Zatrudn." },
];

function linkName(row: LinkResultRow): string {
  if (row.kind === "recruiter") return "Mój link ogólny";
  return row.job_title || "Rekrutacja";
}

export function LinkResultsTab({ enabled }: { enabled: boolean }) {
  const [days, setDays] = useState<LinkResultsPeriod>(30);
  const query = useLinkResults(enabled, days);
  const peopleQuery = useLinkPeople(enabled, days);
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
  const visitsOf = (counts: LinkResultCounts): number =>
    days ? (counts.visits_in_period ?? 0) : counts.visits;
  const trackedFrom = data?.visits_tracked_from ?? null;
  const groups: { title: string; rows: LinkResultRow[] }[] = [
    {
      title: "Link ogólny: osoba trafia do bazy i do Moich ludzi",
      rows: data?.links.filter((row) => row.kind === "recruiter") ?? [],
    },
    {
      title: "Linki do rekrutacji: osoba trafia do „Nowi” tej rekrutacji",
      rows: data?.links.filter((row) => row.kind !== "recruiter") ?? [],
    },
  ];

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
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5" data-testid="results-tiles">
            <div className="rounded-lg border border-border px-3 py-2">
              <p className="text-xs text-muted-foreground">
                {days ? `Wejścia, ${days} dni` : "Wejścia od początku"}
              </p>
              <p className="text-lg font-semibold tabular-nums text-foreground">{visitsOf(totals)}</p>
            </div>
            {TILES.map((tile) => (
              <div key={tile.key} className="rounded-lg border border-border px-3 py-2">
                <p className="text-xs text-muted-foreground">{tile.label}</p>
                <p className="text-lg font-semibold tabular-nums text-foreground">{totals[tile.key]}</p>
              </div>
            ))}
          </div>

          {days ? (
            <p className="text-xs text-muted-foreground" data-testid="results-visits-note">
              {trackedFrom
                ? `Wejścia dzień po dniu zapisujemy od ${formatDate(trackedFrom)}, starsze są tylko w sumie „Od początku”.`
                : "Wejścia dzień po dniu jeszcze się nie zebrały. Suma jest w „Od początku”."}
            </p>
          ) : null}

          <section className="space-y-2" aria-labelledby="results-people-heading">
            <h4 id="results-people-heading" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Kto się zgłosił
              {peopleQuery.isSuccess ? ` (${peopleQuery.data.total})` : ""}
            </h4>
            {peopleQuery.isError ? (
              <QueryStateNotice
                state="error"
                description="Nie udało się wczytać listy osób. To nie znaczy, że nikt się nie zgłosił."
                onRetry={() => peopleQuery.refetch()}
              />
            ) : !peopleQuery.isSuccess ? (
              <p className="text-sm text-muted-foreground">Wczytuję osoby…</p>
            ) : peopleQuery.data.people.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border px-4 py-3 text-sm text-muted-foreground">
                W tym okresie nikt nie zgłosił się z Twoich linków.
              </p>
            ) : (
              <ul className="divide-y divide-border rounded-lg border border-border" data-testid="results-people">
                {peopleQuery.data.people.map((person) => (
                  <li key={linkPersonKey(person)} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                    <div className="min-w-0 flex-1 basis-64">
                      <Link
                        href={`/candidates/${person.candidate_id}`}
                        className="text-sm font-medium text-foreground hover:underline"
                      >
                        {person.full_name}
                      </Link>
                      <p className="truncate text-xs text-muted-foreground">
                        {linkPersonAppliedAt(person)} · {linkPersonLinkName(person)} ·{" "}
                        {person.was_duplicate ? "już był w bazie" : "nowy w bazie"}
                      </p>
                    </div>
                    <span className="max-w-[16rem] text-right text-xs text-foreground">
                      {linkPersonNow(person)}
                    </span>
                    <Badge size="sm" variant={person.in_my_people ? "success" : "neutral"}>
                      {person.in_my_people ? "W Moich ludziach" : "Poza Moimi ludźmi"}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
            {peopleQuery.data?.truncated ? (
              <p className="text-xs text-muted-foreground">
                Pokazuję {peopleQuery.data.people.length} najnowszych z {peopleQuery.data.total} zgłoszeń.
              </p>
            ) : null}
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
                    {COUNT_COLUMNS.map((column) => (
                      <th key={column.key} className="px-3 py-2 text-right font-medium">
                        {column.label}
                      </th>
                    ))}
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {groups.map((group) =>
                    group.rows.length === 0 ? null : (
                      <Fragment key={group.title}>
                        <tr className="border-t border-border bg-muted/30">
                          <td colSpan={COUNT_COLUMNS.length + 3} className="px-3 py-1.5 text-xs font-medium text-muted-foreground">
                            {group.title} ({group.rows.length})
                          </td>
                        </tr>
                        {group.rows.map((row) => (
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
                            <td className="px-3 py-2 text-right tabular-nums">{visitsOf(row)}</td>
                            {COUNT_COLUMNS.map((column) => (
                              <td key={column.key} className="px-3 py-2 text-right tabular-nums">
                                {row[column.key]}
                              </td>
                            ))}
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
                      </Fragment>
                    ),
                  )}
                </tbody>
                <tfoot>
                  <tr className="border-t border-border bg-muted/30 font-medium">
                    <td className="px-3 py-2">Razem</td>
                    <td className="px-3 py-2 text-right tabular-nums">{visitsOf(totals)}</td>
                    {COUNT_COLUMNS.map((column) => (
                      <td key={column.key} className="px-3 py-2 text-right tabular-nums">
                        {totals[column.key]}
                      </td>
                    ))}
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </DialogBody>
  );
}
