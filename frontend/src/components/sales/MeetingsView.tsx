"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { CalendarDays } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { FilterBar } from "@/components/ds/FilterBar";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useSalesMeetings, type MeetingFilters } from "@/lib/api/sales";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDateTimePl } from "@/lib/date-pl";
import { useUrlWriter } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";

import { MeetingTranscriptDialog } from "./MeetingTranscriptDialog";
import { SalesSelect } from "./SalesSelect";

const PAGE = 50;
const LINK_OPTIONS = [
  { value: "opportunity", label: "Przy szansie" },
  { value: "company", label: "Tylko przy firmie" },
  { value: "transcript", label: "Z transkryptem" },
];

const SOURCE_LABELS: Record<string, string> = {
  atlas: "Fireflies",
  "msgraph-event": "Outlook",
  pipedrive_activity: "Pipedrive",
};

/** Pierwsze zdania notatki; zaproszenia z Outlooka zaczynają się od linii podkreślników. */
export function meetingPreview(body: string | null): string {
  return (body ?? "").replace(/_{3,}/g, " ").replace(/\s+/g, " ").trim();
}

/**
 * Sprzedaż → Spotkania: wszystkie spotkania handlowców w jednym miejscu
 * (w Atlasie ekran /spotkania). Pełna notatka leży na osi szansy albo firmy.
 */
export function MeetingsView() {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const [q, setQ] = useState(searchParams?.get("q") ?? "");
  const scope = searchParams?.get("przypisanie") ?? "";
  const [reading, setReading] = useState<number | null>(null);
  const dateFrom = searchParams?.get("od") ?? "";
  const dateTo = searchParams?.get("do") ?? "";
  const offset = Math.max(0, Number(searchParams?.get("strona") ?? 0) || 0);
  const meetings = useSalesMeetings({
    q,
    linked: scope === "transcript" ? undefined : (scope as MeetingFilters["linked"]) || undefined,
    has_transcript: scope === "transcript",
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    limit: PAGE,
    offset,
  });
  const items = meetings.data?.items ?? [];
  const total = meetings.data?.total ?? 0;
  const state = resolveViewState({
    isLoading: meetings.isLoading,
    error: meetings.error,
    isSuccess: meetings.isSuccess,
    isEmpty: items.length === 0,
  });

  const writeParams = (patch: Record<string, string | null>) => {
    const params = new URLSearchParams(window.location.search);
    params.delete("strona");
    for (const [key, value] of Object.entries(patch)) {
      if (value) params.set(key, value);
      else params.delete(key);
    }
    const qs = params.toString();
    replaceUrl(qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  };

  return (
    <div className="space-y-3">
      <FilterBar
        search={{
          value: q,
          onChange: (value) => {
            setQ(value);
            writeParams({ q: value.trim() || null });
          },
          placeholder: "Szukaj po temacie, firmie albo szansie…",
          ariaLabel: "Szukaj spotkania",
        }}
        filters={
          <div className="flex flex-wrap items-center gap-2">
            <SalesSelect
              ariaLabel="Przypisanie"
              className="w-52"
              value={scope}
              onValueChange={(value) => writeParams({ przypisanie: value || null })}
              options={LINK_OPTIONS}
              anyLabel="Wszystkie spotkania"
            />
            <Input
              type="date"
              aria-label="Spotkania od"
              className="h-8 w-36"
              value={dateFrom}
              max={dateTo || undefined}
              onChange={(event) => writeParams({ od: event.target.value || null })}
            />
            <Input
              type="date"
              aria-label="Spotkania do"
              className="h-8 w-36"
              value={dateTo}
              min={dateFrom || undefined}
              onChange={(event) => writeParams({ do: event.target.value || null })}
            />
          </div>
        }
        resultCount={meetings.isSuccess ? total : undefined}
      />
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie spotkań…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void meetings.refetch()} />
      ) : state === "empty" ? (
        <EmptyState
          icon={CalendarDays}
          title="Nic nie pasuje do filtrów"
          description="Zmień wyszukiwanie albo zakres dat."
        />
      ) : (
        <>
          <div className="relative overflow-x-auto">
            <Table className="min-w-[860px]">
              <TableHeader>
                <TableRow>
                  <TableHead className={`${CALM_HEAD} w-40`}>Kiedy</TableHead>
                  <TableHead className={CALM_HEAD}>Spotkanie</TableHead>
                  <TableHead className={CALM_HEAD}>Firma i szansa</TableHead>
                  <TableHead className={`${CALM_HEAD} w-24`}>Źródło</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((meeting) => (
                  <TableRow key={meeting.id} className={CALM_ROW}>
                    <TableCell className="text-sm tabular-nums">
                      {formatDateTimePl(meeting.occurred_at ?? meeting.created_at)}
                    </TableCell>
                    <TableCell className="max-w-96">
                      <span className="font-medium text-foreground">{meeting.subject ?? "Spotkanie bez tytułu"}</span>
                      {meeting.transcript_status === "fetched" && (
                        <Badge variant="soft" size="sm" className="ml-1.5">
                          transkrypt
                        </Badge>
                      )}
                      {meeting.transcript_summary ? (
                        <p className={`${CALM_SUBLINE} line-clamp-2`}>{meeting.transcript_summary}</p>
                      ) : (
                        meetingPreview(meeting.body) && (
                          <p className={`${CALM_SUBLINE} truncate`}>{meetingPreview(meeting.body)}</p>
                        )
                      )}
                      {meeting.transcript_status === "fetched" && (
                        <Button
                          size="sm"
                          variant="quiet"
                          className="px-0"
                          onClick={() => setReading(meeting.id)}
                        >
                          Czytaj transkrypt
                        </Button>
                      )}
                    </TableCell>
                    <TableCell>
                      {meeting.company ? (
                        <Link href={`/sales/companies/${meeting.company.id}`} className="hover:underline">
                          {meeting.company.name}
                        </Link>
                      ) : (
                        "—"
                      )}
                      {meeting.opportunity && (
                        <p className={CALM_SUBLINE}>
                          <Link href={`/sales/opportunities/${meeting.opportunity.id}`} className="hover:underline">
                            {meeting.opportunity.name}
                          </Link>
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {SOURCE_LABELS[meeting.external_source ?? ""] ?? "NEXUS"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {total > PAGE && (
            <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
              <span>
                {offset + 1}–{Math.min(offset + PAGE, total)} z {total}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={offset === 0}
                onClick={() => writeParams({ strona: offset - PAGE > 0 ? String(offset - PAGE) : null })}
              >
                Poprzednie
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={offset + PAGE >= total}
                onClick={() => writeParams({ strona: String(offset + PAGE) })}
              >
                Następne
              </Button>
            </div>
          )}
        </>
      )}
      {reading !== null && (
        <MeetingTranscriptDialog activityId={reading} onClose={() => setReading(null)} />
      )}
    </div>
  );
}
