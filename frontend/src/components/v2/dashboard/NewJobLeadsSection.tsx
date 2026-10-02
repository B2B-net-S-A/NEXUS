"use client";

/**
 * „Nowe rekrutacje — kto prowadzi” na pulpicie Head of Recruitment i admina.
 *
 * Każda rekrutacja ma JEDNEGO rekrutera prowadzącego: przydziela go automat
 * zaraz po przekazaniu do searchu albo wskazuje Delivery Lead. Uczestnikami są
 * wszyscy z kategorii rekrutacji — dochodzą sami, w tle. Ta lista niczego nie
 * wymaga: pokazuje, kto prowadzi świeżo przekazane rekrutacje, i pozwala
 * zmienić osobę tam, gdzie Head of Recruitment się nie zgadza. Dlatego nie
 * liczy się do „Czeka na Ciebie” i nie ma licznika w tonie zadania.
 *
 * Wiersze przychodzą z `GET /api/board-tasks` (`new_job_leads`) wyłącznie dla
 * admina i Head of Recruitment; pozostali dostają pustą listę i sekcji nie ma.
 * Propozycja automatu czekająca na akceptację (tryb „shadow”) ma swoje
 * przyciski w sekcji „Propozycje automatu do akceptacji” — tu jest tylko
 * opisana.
 */

import Link from "next/link";
import { Fragment, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  competenceShortLabel,
  competenceTone,
} from "@/components/v2/CompetenceCategoryBadge";
import { replacementOptions } from "@/components/v2/dashboard/AllocationProposalsSection";
import { PickerQueryState } from "@/components/v2/filters/PickerQueryState";
import { RequestPriorityChip } from "@/components/v2/jobs/RequestPriorityChip";
import { useCapability } from "@/hooks/useCapability";
import { apiErrorMessage } from "@/lib/api-error";
import {
  BOARD_TASKS_QUERY_KEY,
  type BoardTasksResponse,
  type NewJobLeadRow,
} from "@/lib/api/boardTasks";
import { useRequestBoard, type LoadPerson } from "@/lib/api/requestAllocation";
import { transitAgo } from "@/lib/cv-in-transit";
import { formatTime } from "@/lib/interview-cycle";
import { formatDeadlineShort, shortenPersonName } from "@/lib/job-header-subtitle";
import { addRecruiter } from "@/lib/job-team";
import { invalidateJobTeam } from "@/lib/job-team-cache";
import { countPl } from "@/lib/plural-pl";
import { requestWord } from "@/lib/request-board";
import { isPriorityLevel } from "@/lib/request-priority";
import { cn } from "@/lib/utils";

export const NEW_JOB_LEADS_TITLE = "Nowe rekrutacje — kto prowadzi";

/** Tyle rekrutacji widać, zanim trzeba kliknąć „Pokaż wszystkie”. */
export const NEW_JOB_LEADS_ROWS = 6;

const ROLE_LABEL: Record<string, string> = {
  recruiter: "rekruter",
};

/** „1 uczestnik”, „3 uczestnicy”, „12 uczestników”. */
export function participantsLabel(count: number): string {
  return countPl(count, "uczestnik", "uczestnicy", "uczestników");
}

/** „dziś, 10:42”, „wczoraj, 16:05”, „3 dni temu” — kiedy przekazano do searchu. */
export function handoffWhen(iso: string, now: Date = new Date()): string {
  if (Number.isNaN(new Date(iso).getTime())) return "";
  const day = transitAgo(iso, now);
  return day === "dziś" || day === "wczoraj" ? `${day}, ${formatTime(iso)}` : day;
}

export interface LeadState {
  /** Imię i nazwisko prowadzącego; `null` = rekrutacja nie ma prowadzącego. */
  name: string | null;
  /** Skąd prowadzący się wziął albo dlaczego go nie ma. */
  note: string | null;
  /** Rekrutacja bez prowadzącego i nikt go nie przydziela — warto zareagować. */
  warning: boolean;
}

/** Kto prowadzi i skąd — same fakty z wiersza. */
export function leadState(row: NewJobLeadRow): LeadState {
  if (row.lead_user_id == null) {
    if (row.pending_reason === "assigning") {
      return { name: null, note: "Automat przydziela…", warning: false };
    }
    if (row.pending_reason === "passive") {
      return {
        name: null,
        note: "Przyjmujemy kandydatów — bez prowadzącego",
        warning: false,
      };
    }
    return { name: null, note: "Brak prowadzącego", warning: true };
  }
  const name = row.lead_name?.trim() || `#${row.lead_user_id}`;
  if (row.proposed) {
    return { name, note: "propozycja automatu — czeka na akceptację", warning: false };
  }
  if (row.lead_source === "auto") return { name, note: "automat", warning: false };
  if (row.lead_source === "manual") {
    return {
      name,
      note: `wskazany ręcznie${row.assigned_by_name ? ` · ${row.assigned_by_name}` : ""}`,
      warning: false,
    };
  }
  return { name, note: null, warning: false };
}

function LeadPicker({
  row,
  disabled,
  busy,
  onPick,
}: {
  row: NewJobLeadRow;
  disabled: boolean;
  busy: boolean;
  onPick: (person: LoadPerson) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  // Obłożenie czytamy dopiero po otwarciu listy: sekcja stoi na pulpicie,
  // a prowadzącego zmienia się rzadko.
  const board = useRequestBoard({ enabled: open });
  const currentId = row.lead_user_id ?? -1;
  const people = useMemo(
    () => replacementOptions(board.data?.load ?? [], currentId, query),
    [board.data, currentId, query],
  );
  const hasLead = row.lead_user_id != null;

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuery("");
      }}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled}
          loading={busy}
          aria-label={`${hasLead ? "Zmień" : "Wybierz"} prowadzącego: ${row.title}`}
        >
          {hasLead ? "Zmień" : "Wybierz"}
          <ChevronDown className="h-3.5 w-3.5 opacity-60" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(340px,calc(100vw-2rem))] p-0">
        <Command shouldFilter={false}>
          <CommandInput placeholder="Szukaj osoby…" value={query} onValueChange={setQuery} />
          <CommandList>
            {/* Awaria nie może wyglądać jak „nikogo nie ma”: pusty stan dopiero
                przy udanym odczycie. Błąd przy danych już wczytanych zostawia
                listę. */}
            <PickerQueryState
              isPending={board.isPending}
              isError={board.isError && board.data === undefined}
              onRetry={() => void board.refetch()}
              loadingLabel="Ładowanie osób…"
              errorLabel="Nie udało się pobrać listy osób."
            />
            {board.isSuccess && <CommandEmpty>Brak osób.</CommandEmpty>}
            <CommandGroup>
              {people.map((person) => {
                const current = person.user_id === row.lead_user_id;
                return (
                  <CommandItem
                    key={person.user_id}
                    value={String(person.user_id)}
                    disabled={current}
                    onSelect={() => {
                      setOpen(false);
                      setQuery("");
                      onPick(person);
                    }}
                    className="justify-between gap-3"
                  >
                    <span className="min-w-0">
                      <span className={cn("block truncate", current && "font-medium")}>
                        {person.name}
                      </span>
                      {(current || person.leave_until) && (
                        <span className="block truncate text-xs text-muted-foreground">
                          {[
                            current ? "prowadzi teraz" : null,
                            person.leave_until
                              ? `urlop do ${formatDeadlineShort(person.leave_until) ?? person.leave_until}`
                              : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                      )}
                    </span>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {person.count} {requestWord(person.count)}
                    </span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
        <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">
          Wybrana osoba zostaje rekruterem prowadzącym od razu.
        </p>
      </PopoverContent>
    </Popover>
  );
}

export interface NewJobLeadsSectionProps {
  rows: NewJobLeadRow[];
  /**
   * Panel „Czeka na Ciebie” nie ma nic do zrobienia — lista stoi wtedy sama,
   * we własnej ramce nad pulpitem.
   */
  standalone?: boolean;
}

export function NewJobLeadsSection({ rows, standalone = false }: NewJobLeadsSectionProps) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  // Serwer wysyła wiersze tylko adminowi i Head of Recruitment; capability
  // dokłada to, czego odczyt nie mówi: w „podglądzie jako” zapis kończy się
  // odmową, więc przycisków nie ma.
  const canAct = useCapability("job.recruiter.assign");
  const [pending, setPending] = useState<Record<number, true>>({});
  const [expanded, setExpanded] = useState(false);

  if (rows.length === 0) return null;
  const shown = expanded ? rows : rows.slice(0, NEW_JOB_LEADS_ROWS);

  const assign = async (row: NewJobLeadRow, person: LoadPerson) => {
    setPending((current) => ({ ...current, [row.job_id]: true }));
    try {
      // Zmiana prowadzącego i wskazanie pierwszego to to samo żądanie
      // (`POST /api/jobs/{id}/owner`): serwer w jednej transakcji zdejmuje
      // poprzednią osobę i przypisuje nową.
      await addRecruiter(row.job_id, person.user_id, {
        hasWorkingOwner: false,
        canStaff: true,
      });
      // Wiersz pokazuje nową osobę od razu; odczyt z serwera potwierdza resztę.
      queryClient.setQueryData<BoardTasksResponse>(BOARD_TASKS_QUERY_KEY, (current) =>
        current?.new_job_leads
          ? {
              ...current,
              new_job_leads: current.new_job_leads.map((lead) =>
                lead.job_id === row.job_id
                  ? {
                      ...lead,
                      lead_user_id: person.user_id,
                      lead_name: person.name,
                      lead_source: "manual" as const,
                      assigned_by_name: null,
                      proposed: false,
                      pending_reason: null,
                    }
                  : lead,
              ),
            }
          : current,
      );
      showSuccess(`${person.name} prowadzi „${row.title}”.`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zmienić rekrutera prowadzącego."));
    } finally {
      setPending((current) => {
        const next = { ...current };
        delete next[row.job_id];
        return next;
      });
      // Odświeża też „Czeka na Ciebie” i pulpit „Requesty i obłożenie” —
      // także po błędzie, bo odmowa znaczy, że lista pokazuje stary stan.
      invalidateJobTeam(queryClient, row.job_id);
    }
  };

  const section = (
    <section
      aria-label={NEW_JOB_LEADS_TITLE}
      className={cn("@container/leads min-w-0", !standalone && "lg:col-span-3")}
    >
      <header className="mb-1 flex flex-wrap items-baseline gap-2">
        <h3 className="text-sm font-semibold">{NEW_JOB_LEADS_TITLE}</h3>
        {/* Sama liczba, bez plakietki zadania — ta lista o nic nie prosi. */}
        <span className="text-xs tabular-nums text-muted-foreground">{rows.length}</span>
      </header>
      <p className="mb-2 text-xs text-muted-foreground">
        Uczestnikami każdej rekrutacji są wszyscy z jej kategorii. Zmieniasz tylko to,
        z czym się nie zgadzasz.
        {canAct ? "" : " W tym widoku nie możesz zmieniać rekrutera prowadzącego."}
      </p>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {shown.map((row) => {
          const lead = leadState(row);
          const busy = pending[row.job_id] === true;
          const categoryLabel = row.category_name
            ? (competenceShortLabel(row.category_slug) ?? row.category_name)
            : null;
          const when = handoffWhen(row.handed_off_at);
          const meta: { key: string; node: ReactNode }[] = [];
          if (row.client_name) meta.push({ key: "client", node: row.client_name });
          if (when) meta.push({ key: "when", node: `przekazano ${when}` });
          if (row.delivery_lead_name) {
            meta.push({
              key: "dl",
              node: (
                <span title={`Delivery Lead: ${row.delivery_lead_name}`}>
                  DL: {shortenPersonName(row.delivery_lead_name) ?? row.delivery_lead_name}
                </span>
              ),
            });
          }
          const roleLabel = row.lead_role ? (ROLE_LABEL[row.lead_role] ?? row.lead_role) : null;

          return (
            <li
              key={row.job_id}
              // Cztery strefy obok siebie dopiero od 780 px sekcji; węziej —
              // jedna pod drugą.
              className="grid gap-x-4 gap-y-1.5 px-3 py-2.5 @min-[780px]/leads:grid-cols-[minmax(0,1.3fr)_minmax(0,0.8fr)_minmax(0,1fr)_auto] @min-[780px]/leads:items-center"
            >
              <div className="min-w-0">
                <div className="flex min-w-0 items-start gap-1.5">
                  <Link
                    href={`/jobs/${row.job_id}`}
                    title={row.title}
                    className="min-w-0 truncate text-sm font-medium hover:underline"
                  >
                    {row.title}
                  </Link>
                  <RequestPriorityChip
                    level={isPriorityLevel(row.priority_level) ? row.priority_level : null}
                    className="mt-0.5 shrink-0"
                  />
                </div>
                <p className="text-xs text-muted-foreground" data-testid="lead-request-meta">
                  {meta.map((item, index) => (
                    <Fragment key={item.key}>
                      {index > 0 && <span aria-hidden> · </span>}
                      {item.node}
                    </Fragment>
                  ))}
                </p>
              </div>
              <p
                className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted-foreground"
                data-testid="lead-category"
              >
                {categoryLabel ? (
                  <>
                    <Badge
                      variant={competenceTone(row.category_slug)}
                      size="sm"
                      title={row.category_name ?? undefined}
                    >
                      {categoryLabel}
                    </Badge>
                    <span>{participantsLabel(row.participants)}</span>
                  </>
                ) : (
                  "bez kategorii"
                )}
              </p>
              <div className="min-w-0" data-testid="lead-person">
                {lead.name ? (
                  <p className="truncate text-sm">
                    <span className="font-medium">{lead.name}</span>
                    {roleLabel ? (
                      <>
                        {" "}
                        <span className="text-xs text-muted-foreground">{roleLabel}</span>
                      </>
                    ) : null}
                  </p>
                ) : null}
                {lead.note ? (
                  <p
                    className={cn(
                      "text-xs",
                      lead.warning ? "font-medium text-warning" : "text-muted-foreground",
                    )}
                  >
                    {lead.note}
                  </p>
                ) : null}
              </div>
              {/* Propozycję automatu rozstrzyga sekcja propozycji wyżej. */}
              {canAct && !row.proposed ? (
                <div className="flex items-center @min-[780px]/leads:justify-end">
                  <LeadPicker
                    row={row}
                    disabled={busy}
                    busy={busy}
                    onPick={(person) => void assign(row, person)}
                  />
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
      {rows.length > NEW_JOB_LEADS_ROWS && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="mt-1.5 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? "Zwiń" : `Pokaż wszystkie (${rows.length})`}
        </button>
      )}
    </section>
  );

  return standalone ? (
    <div className="rounded-xl border border-border bg-card p-4">{section}</div>
  ) : (
    section
  );
}
