"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { CalendarDays, ListFilter } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { FilterBar } from "@/components/ds/FilterBar";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TruncatedText } from "@/components/ds/TruncatedText";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  usePinActivity,
  useSalesMeetings,
  useUnpinActivity,
  type Meeting,
  type MeetingFilters,
  type MeetingOpportunityOption,
} from "@/lib/api/sales";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { hasPermission } from "@/lib/permissions";
import { useUrlWriter } from "@/lib/url-selection";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { CreateOpportunityFromMeetingDialog } from "./CreateOpportunityFromMeetingDialog";
import { isMeetingToday, meetingWhen, shortCompanyName } from "./meeting-helpers";
import { MeetingDecisionCell } from "./MeetingDecisionCell";
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
  fireflies: "Fireflies",
  "msgraph-event": "Outlook",
  pipedrive_activity: "Pipedrive",
};

const QUEUE_PARAMS: Record<string, MeetingFilters["queue"]> = {
  przypiecie: "pin",
  "bez-szansy": "create",
};

/** Pierwsze zdania notatki; zaproszenia z Outlooka zaczynają się od linii podkreślników. */
export function meetingPreview(body: string | null): string {
  return (body ?? "").replace(/_{3,}/g, " ").replace(/\s+/g, " ").trim();
}

interface FilterToggleProps {
  label: string;
  count?: number;
  active: boolean;
  onToggle: () => void;
}

function FilterToggle({ label, count, active, onToggle }: FilterToggleProps) {
  return (
    <Button
      size="sm"
      variant="outline"
      aria-pressed={active}
      aria-label={count !== undefined ? `${label} ${count}` : label}
      onClick={onToggle}
      className={cn(active && "border-primary/40 bg-primary/10 text-primary hover:bg-primary/15")}
    >
      {label}
      {count !== undefined && <span className="tabular-nums opacity-70">{count}</span>}
    </Button>
  );
}

/**
 * Sprzedaż → Spotkania: wszystkie spotkania handlowców w jednym miejscu
 * (w Atlasie ekran /spotkania), przy każdym decyzja, co z nim zrobić.
 * Pełna notatka leży na osi szansy albo firmy.
 */
export function MeetingsView() {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const { showActionToast, showError } = useToast();
  const pin = usePinActivity();
  const unpin = useUnpinActivity();
  const [q, setQ] = useState(searchParams?.get("q") ?? "");
  const scope = searchParams?.get("przypisanie") ?? "";
  const [reading, setReading] = useState<number | null>(null);
  const [creating, setCreating] = useState<Meeting | null>(null);
  const dateFrom = searchParams?.get("od") ?? "";
  const dateTo = searchParams?.get("do") ?? "";
  const mine = searchParams?.get("moje") !== "0";
  const queueParam = searchParams?.get("kolejka") ?? "";
  const queue = QUEUE_PARAMS[queueParam];
  const upcoming = searchParams?.get("przyszle") === "1";
  const offset = Math.max(0, Number(searchParams?.get("strona") ?? 0) || 0);
  const meetings = useSalesMeetings({
    q,
    linked: scope === "transcript" ? undefined : (scope as MeetingFilters["linked"]) || undefined,
    has_transcript: scope === "transcript",
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    mine,
    queue,
    upcoming,
    limit: PAGE,
    offset,
  });
  const items = meetings.data?.items ?? [];
  const total = meetings.data?.total ?? 0;
  const counts = meetings.data?.counts;
  const state = resolveViewState({
    isLoading: meetings.isLoading,
    error: meetings.error,
    isSuccess: meetings.isSuccess,
    isEmpty: items.length === 0,
  });
  const extraFilters = [scope, dateFrom, dateTo].filter(Boolean).length;

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
  const toggleQueue = (value: string) => writeParams({ kolejka: queueParam === value ? null : value });

  const undo = (activityId: number) =>
    unpin.mutate(activityId, {
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się cofnąć przypięcia.")),
    });
  const pinTo = (meeting: Meeting, option: MeetingOpportunityOption) =>
    pin.mutate(
      { activityId: meeting.id, opportunityId: option.id },
      {
        onSuccess: () => {
          // Przy filtrze kolejki wiersz znika od razu, więc cofnięcie idzie komunikatem.
          if (queue) {
            showActionToast(`Przypięte: ${option.title}`, {
              actionLabel: "Cofnij",
              onAction: () => undo(meeting.id),
            });
          }
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się przypiąć spotkania.")),
      },
    );

  const lastSoonId = items.some((item) => item.timing !== "soon")
    ? items.filter((item) => item.timing === "soon").at(-1)?.id
    : undefined;

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
          <>
            <FilterToggle label="Moje" active={mine} onToggle={() => writeParams({ moje: mine ? "0" : null })} />
            <FilterToggle
              label="Do przypięcia"
              count={counts?.pin}
              active={queue === "pin"}
              onToggle={() => toggleQueue("przypiecie")}
            />
            <FilterToggle
              label="Bez szansy"
              count={counts?.create}
              active={queue === "create"}
              onToggle={() => toggleQueue("bez-szansy")}
            />
            <FilterToggle
              label="Przyszłe"
              count={counts?.upcoming}
              active={upcoming}
              onToggle={() => writeParams({ przyszle: upcoming ? null : "1" })}
            />
            <Popover>
              <PopoverTrigger asChild>
                <Button size="sm" variant={extraFilters ? "primary" : "outline"}>
                  <ListFilter className="mr-1 h-4 w-4" aria-hidden />
                  Filtry{extraFilters ? ` (${extraFilters})` : ""}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-72 space-y-3">
                <div className="space-y-1">
                  <Label htmlFor="meetings-filter-link">Przypisanie</Label>
                  <SalesSelect
                    id="meetings-filter-link"
                    ariaLabel="Przypisanie"
                    value={scope}
                    onValueChange={(value) => writeParams({ przypisanie: value || null })}
                    options={LINK_OPTIONS}
                    anyLabel="Wszystkie spotkania"
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label htmlFor="meetings-filter-from">Od</Label>
                    <Input
                      id="meetings-filter-from"
                      type="date"
                      aria-label="Spotkania od"
                      value={dateFrom}
                      max={dateTo || undefined}
                      onChange={(event) => writeParams({ od: event.target.value || null })}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="meetings-filter-to">Do</Label>
                    <Input
                      id="meetings-filter-to"
                      type="date"
                      aria-label="Spotkania do"
                      value={dateTo}
                      min={dateFrom || undefined}
                      onChange={(event) => writeParams({ do: event.target.value || null })}
                    />
                  </div>
                </div>
              </PopoverContent>
            </Popover>
          </>
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
          description="Zmień wyszukiwanie albo wyłącz część filtrów."
          action={
            mine ? (
              <Button size="sm" variant="outline" onClick={() => writeParams({ moje: "0" })}>
                Pokaż spotkania wszystkich
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          <div className="relative overflow-x-auto">
            <Table density="compact" className="min-w-[920px] table-fixed">
              <TableHeader>
                <TableRow>
                  <TableHead className={`${CALM_HEAD} w-[112px]`}>Kiedy</TableHead>
                  <TableHead className={`${CALM_HEAD} w-[200px]`}>Firma</TableHead>
                  <TableHead className={CALM_HEAD}>Temat</TableHead>
                  <TableHead className={`${CALM_HEAD} w-[72px]`}>Źródło</TableHead>
                  <TableHead className={`${CALM_HEAD} w-[296px] text-right`}>Co dalej</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((meeting) => {
                  const held = meeting.occurred_at ?? meeting.created_at;
                  return (
                    <TableRow
                      key={meeting.id}
                      className={cn(CALM_ROW, meeting.id === lastSoonId && "border-b-foreground/30")}
                    >
                      <TableCell
                        className={cn(
                          "whitespace-nowrap text-sm tabular-nums",
                          isMeetingToday(held) && "font-medium text-primary",
                        )}
                      >
                        {meetingWhen(held)}
                      </TableCell>
                      <TableCell>
                        {meeting.company ? (
                          <Link href={`/sales/companies/${meeting.company.id}`} className="block hover:underline">
                            <TruncatedText className="max-w-full" title={meeting.company.name}>
                              {shortCompanyName(meeting.company.name)}
                            </TruncatedText>
                          </Link>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex min-w-0 items-center gap-1.5">
                          <TruncatedText
                            className="max-w-full font-medium text-foreground"
                            title={[meeting.subject, meetingPreview(meeting.body)].filter(Boolean).join("\n")}
                          >
                            {meeting.subject ?? "Spotkanie bez tytułu"}
                          </TruncatedText>
                          {meeting.transcript_status === "fetched" && (
                            <Badge variant="soft" size="sm">
                              transkrypt
                            </Badge>
                          )}
                        </div>
                        {meeting.transcript_summary && (
                          <p className={`${CALM_SUBLINE} line-clamp-2`}>{meeting.transcript_summary}</p>
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
                      <TableCell className="text-sm text-muted-foreground">
                        {SOURCE_LABELS[meeting.external_source ?? ""] ?? "NEXUS"}
                      </TableCell>
                      <TableCell>
                        <MeetingDecisionCell
                          meeting={meeting}
                          canEdit={canEdit}
                          busy={pin.isPending || unpin.isPending}
                          onPin={(option) => pinTo(meeting, option)}
                          onCreate={() => setCreating(meeting)}
                          onUnpin={() => undo(meeting.id)}
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
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
      {creating && (
        <CreateOpportunityFromMeetingDialog meeting={creating} onClose={() => setCreating(null)} />
      )}
    </div>
  );
}
