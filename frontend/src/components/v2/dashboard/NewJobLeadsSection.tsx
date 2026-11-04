"use client";

/**
 * „Nowe rekrutacje P1 — kto prowadzi” na pulpicie Head of Recruitment i admina.
 *
 * Każda rekrutacja ma JEDNEGO rekrutera prowadzącego: przydziela go automat
 * zaraz po przekazaniu do searchu albo wskazuje Delivery Lead. Uczestnikami są
 * wszyscy z kategorii rekrutacji — dochodzą sami, w tle. Ta lista niczego nie
 * wymaga: pokazuje, kto prowadzi świeżo przekazane rekrutacje, i pozwala
 * zmienić osobę tam, gdzie Head of Recruitment się nie zgadza. Dlatego nie
 * liczy się do „Czeka na Ciebie” i nie ma licznika w tonie zadania.
 *
 * Lista ma koniec (decyzja Artura 07.10.2026): „Potwierdź” zdejmuje
 * rekrutację z listy — serwer pamięta potwierdzoną osobę i pokaże wiersz
 * znowu tylko wtedy, gdy prowadzący zmieni się później; wtedy wiersz mówi,
 * kto był wcześniej (`returned_from_name`).
 *
 * Od 20.10.2026 (prośba Head of Recruitment) „Zmień” niczego nie zapisuje:
 * zaznacza jedną albo kilka osób w szkicu wiersza, a zapis idzie dopiero po
 * „Potwierdź” (`leadDraftTeam`). Prowadzi obecny prowadzący, jeśli zostaje
 * zaznaczony, inaczej pierwsza zaznaczona osoba; pozostałe dochodzą jako
 * rekruterzy. Każda trasa zmiany zespołu zapisuje decyzję Head of Recruitment
 * po stronie serwera, więc szkic nie może iść na serwer przed „Potwierdź”.
 *
 * Od 14.10.2026 (uwagi Head of Recruitment, decyzje Artura D1–D3) lista jest
 * tylko dla P1 bez championa, a zespół ustawiony przez Head of Recruitment albo
 * admina na DOWOLNYM ekranie liczy się jak „Potwierdź” (serwer:
 * `services/new_job_leads.py`). „Przekazano …” mówi, co zaczęło bieżący cykl:
 * przekazanie, ponowne otwarcie albo wejście na P1 (`since_reason`).
 *
 * Wiersze przychodzą z `GET /api/board-tasks` (`new_job_leads`) wyłącznie dla
 * admina i Head of Recruitment; pozostali dostają pustą listę i sekcji nie ma.
 * Propozycja automatu czekająca na akceptację (tryb „shadow”) ma swoje
 * przyciski w sekcji „Propozycje automatu do akceptacji” — tu jest tylko
 * opisana. Rekrutacja opublikowana, której nikt nigdy nie przekazał do searchu
 * (`pending_reason: "not_handed_off"`), ma zamiast prowadzącego komunikat
 * i link „Przekaż do searchu” — prowadzącego wybiera się przy przekazaniu.
 *
 * Filtry (09.10.2026): klient, kategoria, Delivery Lead, prowadzący, priorytet
 * — po stronie przeglądarki, z opcjami z samych wierszy
 * (`lib/new-job-leads-filters.ts`, pasek: `LeadFiltersBar`, wspólny z listą
 * propozycji automatu). Pasek stoi dopiero, gdy lista nie mieści
 * się bez „Pokaż wszystkie”; krótką listę widać w całości. Wybór jest
 * zapamiętany w przeglądarce dla konta, więc przeżywa odświeżenie strony.
 */

import Link from "next/link";
import { Fragment, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown } from "lucide-react";

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
import { LeadFiltersBar, useLeadFilters } from "@/components/v2/dashboard/LeadFiltersBar";
import { PickerQueryState } from "@/components/v2/filters/PickerQueryState";
import { RequestPriorityChip } from "@/components/v2/jobs/RequestPriorityChip";
import { useCapability } from "@/hooks/useCapability";
import { apiErrorMessage } from "@/lib/api-error";
import {
  BOARD_TASKS_QUERY_KEY,
  type BoardTasksResponse,
  type NewJobLeadRow,
  type NewJobLeadSinceReason,
} from "@/lib/api/boardTasks";
import {
  confirmJobLead,
  useRequestBoard,
  type LoadPerson,
} from "@/lib/api/requestAllocation";
import { shortDate } from "@/lib/candidate-followup";
import { transitAgo } from "@/lib/cv-in-transit";
import { formatTime } from "@/lib/interview-cycle";
import { formatDeadlineShort, shortenPersonName } from "@/lib/job-header-subtitle";
import { addRecruiter, joinNames } from "@/lib/job-team";
import { invalidateJobTeam } from "@/lib/job-team-cache";
import { countPl } from "@/lib/plural-pl";
import { p1LoadLabel } from "@/lib/request-board";
import { isPriorityLevel } from "@/lib/request-priority";
import { cn } from "@/lib/utils";

export const NEW_JOB_LEADS_TITLE = "Nowe rekrutacje P1 — kto prowadzi";

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

const SINCE_VERB: Record<NewJobLeadSinceReason, string> = {
  handoff: "przekazano",
  reopen: "otwarta ponownie",
  p1: "podniesiona na P1",
};

/** „przekazano dziś, 10:42”, „otwarta ponownie 2 dni temu”, „podniesiona na P1 wczoraj, 16:05”. */
export function cycleStartLabel(row: Pick<NewJobLeadRow, "handed_off_at" | "since_reason">): string {
  const when = handoffWhen(row.handed_off_at);
  if (!when) return "";
  return `${SINCE_VERB[row.since_reason ?? "handoff"] ?? SINCE_VERB.handoff} ${when}`;
}

/** Wiersz wrócił po decyzji Head of Recruitment — kto prowadził wtedy. */
export function returnedNote(row: Pick<NewJobLeadRow, "returned_from_name">): string | null {
  const name = row.returned_from_name?.trim();
  return name
    ? `Wraca, bo prowadzący zmienił się po decyzji Head of Recruitment: było ${name}.`
    : null;
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
  if (row.pending_reason === "not_handed_off") {
    return { name: null, note: "Bez przekazania do searchu", warning: true };
  }
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

/** Osoba w szkicu zespołu wiersza. */
export interface DraftPerson {
  user_id: number;
  name: string;
}

export interface LeadDraftTeam {
  /** Kto będzie prowadził po „Potwierdź”; `null` = nikt nie jest zaznaczony. */
  lead: DraftPerson | null;
  /** Osoby dopisywane jako rekruterzy obok prowadzącego. */
  others: DraftPerson[];
  /** Szkic różni się od tego, co jest na serwerze. */
  dirty: boolean;
}

/** Zaznaczenie bez szkicu: sam obecny prowadzący (albo nikt). */
export function initialSelection(row: NewJobLeadRow): DraftPerson[] {
  if (row.lead_user_id == null) return [];
  return [{ user_id: row.lead_user_id, name: leadState(row).name ?? `#${row.lead_user_id}` }];
}

/**
 * Zespół, który zapisze „Potwierdź”. Obecny prowadzący zostaje prowadzącym,
 * dopóki jest zaznaczony; odznaczony — prowadzi pierwsza zaznaczona osoba.
 */
export function leadDraftTeam(
  row: NewJobLeadRow,
  draft: readonly DraftPerson[] | undefined,
): LeadDraftTeam {
  const selected = draft ?? initialSelection(row);
  const lead =
    selected.find((person) => person.user_id === row.lead_user_id) ?? selected[0] ?? null;
  const others = selected.filter((person) => person.user_id !== lead?.user_id);
  const dirty = (lead?.user_id ?? null) !== row.lead_user_id || others.length > 0;
  return { lead, others, dirty };
}

function LeadPicker({
  row,
  selected,
  disabled,
  onToggle,
}: {
  row: NewJobLeadRow;
  selected: readonly DraftPerson[];
  disabled: boolean;
  onToggle: (person: LoadPerson) => void;
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
  const hasLead = row.lead_user_id != null || selected.length > 0;
  const selectedIds = new Set(selected.map((person) => person.user_id));

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
                const checked = selectedIds.has(person.user_id);
                return (
                  <CommandItem
                    key={person.user_id}
                    value={String(person.user_id)}
                    // Lista zostaje otwarta: zaznacza się kilka osób naraz.
                    onSelect={() => onToggle(person)}
                    // `aria-selected` należy do cmdk (podświetlenie klawiaturą).
                    data-checked={checked || undefined}
                    className="justify-between gap-3"
                  >
                    <Check
                      className={cn("h-4 w-4 shrink-0", checked ? "opacity-100" : "opacity-0")}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1">
                      <span className={cn("block truncate", current && "font-medium")}>
                        {person.name}
                        {checked ? <span className="sr-only"> (zaznaczona)</span> : null}
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
                      {p1LoadLabel(person.count)}
                    </span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
        <p className="border-t border-border px-3 py-2 text-xs text-muted-foreground">
          Zaznacz jedną albo kilka osób. Zapiszą się dopiero po „Potwierdź”.
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
  // Szkic zespołu per rekrutacja — tylko w przeglądarce, do „Potwierdź”.
  const [drafts, setDrafts] = useState<Record<number, DraftPerson[]>>({});
  const [expanded, setExpanded] = useState(false);
  const filter = useLeadFilters(rows, "new-job-leads", NEW_JOB_LEADS_ROWS);
  const { filtered, filtering } = filter;

  if (rows.length === 0) return null;
  const shown = expanded ? filtered : filtered.slice(0, NEW_JOB_LEADS_ROWS);

  const dropRow = (jobId: number) =>
    queryClient.setQueryData<BoardTasksResponse>(BOARD_TASKS_QUERY_KEY, (current) =>
      current?.new_job_leads
        ? {
            ...current,
            new_job_leads: current.new_job_leads.filter((lead) => lead.job_id !== jobId),
          }
        : current,
    );

  const markPending = (jobId: number, on: boolean) =>
    setPending((current) => {
      const next = { ...current };
      if (on) next[jobId] = true;
      else delete next[jobId];
      return next;
    });

  const clearDraft = (jobId: number) =>
    setDrafts((current) => {
      const next = { ...current };
      delete next[jobId];
      return next;
    });

  const toggle = (row: NewJobLeadRow, person: LoadPerson) =>
    setDrafts((current) => {
      const selected = current[row.job_id] ?? initialSelection(row);
      const next = selected.some((item) => item.user_id === person.user_id)
        ? selected.filter((item) => item.user_id !== person.user_id)
        : [...selected, { user_id: person.user_id, name: person.name }];
      return { ...current, [row.job_id]: next };
    });

  const confirmTeam = async (row: NewJobLeadRow) => {
    const { lead, others, dirty } = leadDraftTeam(row, drafts[row.job_id]);
    if (!lead) return;
    markPending(row.job_id, true);
    const saved: string[] = [];
    try {
      if (lead.user_id !== row.lead_user_id) {
        // `POST /api/jobs/{id}/owner`: serwer w jednej transakcji zdejmuje
        // poprzedniego prowadzącego i przypisuje nowego.
        await addRecruiter(row.job_id, lead.user_id, { hasWorkingOwner: false, canStaff: true });
        saved.push(`${lead.name} prowadzi`);
      }
      for (const person of others) {
        // Obok prowadzącego — `POST /api/jobs/{id}/collaborators`.
        await addRecruiter(row.job_id, person.user_id, { hasWorkingOwner: true, canStaff: true });
        saved.push(`dołącza ${person.name}`);
      }
      // Trasy zespołu same zapisują decyzję; bez zmian zostaje samo „zgadzam się”.
      if (!dirty) await confirmJobLead(row.job_id, lead.user_id);
      dropRow(row.job_id);
      const joined = others.length > 0 ? `, dołącza ${joinNames(others.map((p) => p.name))}` : "";
      showSuccess(`Potwierdzono: ${lead.name} prowadzi „${row.title}”${joined}.`);
    } catch (error) {
      const message = apiErrorMessage(error, "Nie udało się zapisać rekrutera prowadzącego.");
      showError(saved.length > 0 ? `Zapisano: ${saved.join(", ")}. Reszta nie: ${message}` : message);
    } finally {
      markPending(row.job_id, false);
      // Po błędzie wiersz pokazuje stan z serwera, nie szkic.
      clearDraft(row.job_id);
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
        <span className="text-xs tabular-nums text-muted-foreground">
          {filtering ? `${filtered.length} z ${rows.length}` : rows.length}
        </span>
      </header>
      <p className="mb-2 text-xs text-muted-foreground">
        Rekrutacje P1 z ostatnich 7 dni, o których prowadzącym nikt z Head of Recruitment
        jeszcze nie zdecydował. Zespół ustawiony na dowolnym ekranie liczy się jak „Potwierdź”.
        {canAct ? "" : " W tym widoku nie możesz zmieniać rekrutera prowadzącego."}
      </p>
      <LeadFiltersBar state={filter} />
      {filtered.length === 0 ? (
        <p role="status" className="rounded-lg border border-border px-3 py-2.5 text-sm text-muted-foreground">
          Żadna rekrutacja nie pasuje do ustawionych filtrów.
        </p>
      ) : (
      <ul className="divide-y divide-border rounded-lg border border-border">
        {shown.map((row) => {
          const lead = leadState(row);
          const busy = pending[row.job_id] === true;
          const categoryLabel = row.category_name
            ? (competenceShortLabel(row.category_slug) ?? row.category_name)
            : null;
          const notHandedOff = row.pending_reason === "not_handed_off";
          const when = notHandedOff ? "" : cycleStartLabel(row);
          const returned = returnedNote(row);
          const meta: { key: string; node: ReactNode }[] = [];
          if (row.client_name) meta.push({ key: "client", node: row.client_name });
          if (when) meta.push({ key: "when", node: when });
          // Bez przekazania `handed_off_at` niesie datę założenia rekrutacji.
          if (notHandedOff && row.handed_off_at) {
            meta.push({ key: "created", node: `założona ${shortDate(row.handed_off_at)}` });
          }
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
          const draft = drafts[row.job_id];
          const team = leadDraftTeam(row, draft);

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
                {team.dirty ? (
                  <>
                    <p className="truncate text-sm">
                      {team.lead ? (
                        <span className="font-medium">{team.lead.name}</span>
                      ) : (
                        <span className="text-muted-foreground">Nikt nie zaznaczony</span>
                      )}
                      {team.others.length > 0 ? (
                        <span className="text-muted-foreground">
                          {" "}
                          + {joinNames(team.others.map((person) => person.name))}
                        </span>
                      ) : null}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      niezapisane — zapisze „Potwierdź”
                      {" · "}
                      <button
                        type="button"
                        onClick={() => clearDraft(row.job_id)}
                        className="font-medium text-primary hover:underline"
                        aria-label={`Cofnij zmiany: ${row.title}`}
                      >
                        Cofnij
                      </button>
                    </p>
                  </>
                ) : lead.name ? (
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
                {!team.dirty && lead.note ? (
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
              {notHandedOff ? (
                <div className="flex items-center @min-[780px]/leads:justify-end">
                  <Link
                    href={`/jobs/${row.job_id}`}
                    aria-label={`Przekaż do searchu: ${row.title}`}
                    className="text-xs font-medium text-primary hover:underline"
                  >
                    Przekaż do searchu
                  </Link>
                </div>
              ) : canAct && !row.proposed ? (
                <div className="flex items-center gap-2 @min-[780px]/leads:justify-end">
                  {team.lead ? (
                    <Button
                      type="button"
                      size="sm"
                      variant={team.dirty ? "primary" : "outline"}
                      disabled={busy}
                      loading={busy}
                      onClick={() => void confirmTeam(row)}
                      aria-label={`Potwierdź prowadzącego: ${row.title}`}
                    >
                      Potwierdź
                    </Button>
                  ) : null}
                  <LeadPicker
                    row={row}
                    selected={draft ?? initialSelection(row)}
                    disabled={busy}
                    onToggle={(person) => toggle(row, person)}
                  />
                </div>
              ) : null}
              {returned ? (
                <p
                  data-testid="lead-returned"
                  className="rounded-md bg-warning-muted px-2.5 py-1.5 text-xs text-warning-muted-foreground @min-[780px]/leads:col-span-4"
                >
                  {returned}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
      )}
      {filtered.length > NEW_JOB_LEADS_ROWS && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="mt-1.5 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? "Zwiń" : `Pokaż wszystkie (${filtered.length})`}
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
