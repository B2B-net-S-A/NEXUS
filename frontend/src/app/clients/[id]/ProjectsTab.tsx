"use client";

import { useState } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Ellipsis, FileSpreadsheet, Search, UserPlus, XCircle } from "lucide-react";
import api from "@/lib/api";
import { TabbedNav } from "@/components/ds";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ClientRecruitingSheet } from "@/components/client-profile/ClientRecruitingSheet";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import {
  recruitersOf,
  workingRecruiters,
  type JobTeamSource,
} from "@/lib/job-team";
import { canViewClientRate } from "@/lib/client-rate-access";
import {
  openedQueryParams,
  openedRangeReversed,
  type JobOpenedRange,
} from "@/lib/jobs-url-filters";
import { previousMonth } from "@/lib/previous-month";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
import { BnpMonthlyReportDialog } from "@/components/client-profile/BnpMonthlyReportDialog";
import { AddCandidateToJobModal } from "@/components/client-profile/actions/AddCandidateToJobModal";
import { CloseJobAsLostModal } from "@/components/client-profile/actions/CloseJobAsLostModal";
import {
  canCloseJobAsLost,
  canMoveInPipeline,
} from "@/components/client-profile/permissions";
import { JobCloseWithReasonDialog } from "@/components/v2/jobs/JobCloseWithReasonDialog";
import { useAuthStore } from "@/store/auth";
import type { JobCloseReason } from "@/types/client-profile";
import {
  OUTCOME_CHIPS,
  UNREVIEWED_NOTE,
  closedOutcomeNote,
  hiredLine,
  outcomeTotal,
  type OutcomeCounts,
  type OutcomeFilter,
  type ProjectOutcome,
} from "./projectOutcome";

// ── Types ─────────────────────────────────────────────────────────────────────

// "Projekty" u klienta = oferty pracy / zapytania rekrutacyjne (Job). Podział na
// aktywne vs zamknięte jest wyprowadzany z istniejącego `status` (draft |
// published | closed) — dane NIE wymagają migracji: każdy rekord ma już status,
// więc segregacja jest czysto prezentacyjna (grupowanie po statusie).
// Pola poniżej `status` to te same, które `/api/jobs` oddaje liście rekrutacji
// (`JobListRowFields` w `v2/jobs/JobListCells`) — tu czytane do kolumn tabeli.
interface ProjectJob extends JobTeamSource {
  id: number;
  title: string;
  location: string | null;
  status: string;
  /** Numer zapytania u klienta (ZOB, SAP…). */
  client_reference?: string | null;
  /** Wszyscy kandydaci, którzy kiedykolwiek byli w tej rekrutacji. */
  candidate_count?: number | null;
  /** `opened_at`, a bez niej `created_at` — jak kolumna „Otwarta” listy rekrutacji. */
  opened_effective_at?: string | null;
  opened_at?: string | null;
  created_at?: string | null;
  /** Wynik zamkniętej (reguła hit ratio, `services/job_outcome.py`). */
  outcome?: ProjectOutcome | null;
  hired_names?: string[] | null;
  close_reason?: JobCloseReason | null;
  close_notes?: string | null;
  duplicate_of_job_id?: number | null;
}

const STATUS_VIEW: Record<string, { label: string; tone: StatusDotTone }> = {
  published: { label: "Aktywna", tone: "success" },
  draft: { label: "Szkic", tone: "neutral" },
};
// Szara, nie czerwona (26.11.2026): czerwień przy każdym zamkniętym projekcie
// czytała się jak „wszystko przegraliśmy”. Wygraną niesie zielony wiersz.
const CLOSED_STATUS = { label: "Zamknięta", tone: "neutral" } as const;

function openedDate(job: ProjectJob): string | null {
  return job.opened_effective_at ?? job.opened_at ?? job.created_at ?? null;
}

interface JobsPage {
  items: ProjectJob[];
  total: number;
  /** Tylko kubełek zamkniętych: liczniki chipów, bez filtra wyniku. */
  outcomeCounts?: OutcomeCounts;
}

type Bucket = "active" | "closed" | "all";

// Sufit jednej strony. /api/jobs zwraca max 100 wierszy na page_size — dla
// widoku pojedynczego klienta to praktycznie zawsze pełen zbiór. Gdy zamknięta
// historia przekroczy 100, sekcja pokazuje delikatny hint (patrz truncated).
const PAGE_SIZE = 100;

// Wyszukiwanie po stronie serwera (`q` → Job.title ilike) — spójne z całą resztą
// wyszukiwania ofert w aplikacji i, w odróżnieniu od filtra po pobranej stronie,
// przeszukuje pełny zbiór, a nie tylko pierwsze 100 wierszy.
async function fetchClientJobs(
  clientId: number,
  bucket: Bucket,
  q: string,
  opened: JobOpenedRange,
  outcome: OutcomeFilter = "all",
): Promise<JobsPage> {
  const params: Record<string, unknown> = {
    client_id: clientId,
    page_size: PAGE_SIZE,
    ...openedQueryParams(opened),
  };
  if (bucket === "active") {
    // open_only = status in (draft, published) — "aktywne / w toku".
    params.open_only = true;
  } else if (bucket === "closed") {
    params.status = "closed";
    params.outcome_counts = true;
    if (outcome !== "all") params.outcome = outcome;
  }
  const trimmed = q.trim();
  if (trimmed) params.q = trimmed;

  const r = await api.get("/api/jobs", { params });
  const data = r.data ?? {};
  if (Array.isArray(data)) {
    return { items: data, total: data.length };
  }
  const items: ProjectJob[] = Array.isArray(data.items) ? data.items : [];
  return {
    items,
    total: typeof data.total === "number" ? data.total : items.length,
    outcomeCounts: data.outcome_counts ?? undefined,
  };
}

// ── Row ───────────────────────────────────────────────────────────────────────

function ProjectRow({
  job,
  actions,
  showActions,
  onFillOutcome,
}: {
  job: ProjectJob;
  /** Akcje rekrutacji (Dodaj / Przegrana) — przeniesione z usuniętej sekcji
      „Otwarte rekrutacje" w Profilu (ticket #3); Projekty są teraz jedynym
      miejscem zarządzania rekrutacjami klienta. */
  actions?: React.ReactNode;
  /** Kolumna „Akcje" istnieje (aktywne projekty) — komórka jest zawsze. */
  showActions: boolean;
  /** „Uzupełnij wynik” przy zamkniętej bez powodu; brak = brak uprawnień. */
  onFillOutcome?: (job: ProjectJob) => void;
}) {
  const status = STATUS_VIEW[job.status] ?? CLOSED_STATUS;
  const opened = openedDate(job);
  const recruiters = workingRecruiters(recruitersOf(job));
  const subline = [job.location, job.client_reference].filter(Boolean).join(" · ");
  const won = job.outcome === "won";
  return (
    <TableRow
      className={cn(
        "h-[54px]",
        // Wariant „B + chipy” (26.11.2026): wygrana to cały wiersz na zielono
        // — świadomy wyjątek od „bez tła w wierszach” spokojnych tabel.
        won && "bg-success-muted hover:bg-success-muted",
      )}
      data-outcome={job.outcome ?? undefined}
    >
      <TableCell className={cn(won && "shadow-[inset_3px_0_0_var(--color-success)]")}>
        {/* Nawigacja do rekrutacji zostaje na tytule; akcje są osobnymi
            przyciskami w ostatniej kolumnie (przycisk nie może siedzieć w linku). */}
        <a
          href={`/jobs/${job.id}`}
          className="block max-w-[360px] truncate font-semibold text-foreground hover:text-primary hover:underline"
        >
          {job.title}
        </a>
        {subline ? (
          <span className={cn(CALM_SUBLINE, "max-w-[360px] truncate")}>{subline}</span>
        ) : null}
      </TableCell>
      <TableCell>
        <ProjectStatusCell job={job} status={status} onFillOutcome={onFillOutcome} />
      </TableCell>
      <TableCell className="whitespace-nowrap tabular-nums">
        {opened ? formatIsoDatePl(opened) : <span className={CALM_EMPTY}>—</span>}
      </TableCell>
      <TableCell className={CALM_AMOUNT}>
        {typeof job.candidate_count === "number" ? (
          job.candidate_count
        ) : (
          <span className={CALM_EMPTY}>—</span>
        )}
      </TableCell>
      <TableCell>
        {recruiters.length > 0 ? (
          <span
            className="block max-w-[220px] truncate"
            title={recruiters.map((person) => person.name).join(", ")}
          >
            {recruiters[0].name}
            {recruiters.length > 1 ? (
              <span className="text-muted-foreground"> +{recruiters.length - 1}</span>
            ) : null}
          </span>
        ) : (
          <span className={CALM_EMPTY}>Bez rekrutera</span>
        )}
      </TableCell>
      {showActions ? (
        <TableCell className="text-right">
          <div className="flex items-center justify-end gap-1.5">{actions}</div>
        </TableCell>
      ) : null}
    </TableRow>
  );
}

function ProjectStatusCell({
  job,
  status,
  onFillOutcome,
}: {
  job: ProjectJob;
  status: { label: string; tone: StatusDotTone };
  onFillOutcome?: (job: ProjectJob) => void;
}) {
  if (job.outcome === "won") {
    const hired = hiredLine(job.hired_names);
    return (
      <>
        <span className="inline-flex items-center gap-1 rounded-full bg-success px-2 py-0.5 text-xs font-semibold text-success-foreground">
          <Check className="h-3 w-3" aria-hidden="true" />
          Wygrana
        </span>
        {hired ? (
          <span
            className={cn(CALM_SUBLINE, "max-w-[240px] truncate text-success-muted-foreground")}
            title={hired}
          >
            {hired}
          </span>
        ) : null}
      </>
    );
  }
  const note = closedOutcomeNote(job);
  return (
    <>
      <StatusDot tone={status.tone}>{status.label}</StatusDot>
      {note ? (
        <span className={cn(CALM_SUBLINE, "max-w-[240px] truncate")} title={note}>
          {note}
        </span>
      ) : null}
      {job.outcome === "unreviewed" ? (
        onFillOutcome ? (
          <button
            type="button"
            onClick={() => onFillOutcome(job)}
            aria-label={`Uzupełnij wynik: ${job.title}`}
            className="block text-xs font-medium text-primary hover:underline"
          >
            Uzupełnij wynik
          </button>
        ) : (
          <span className={CALM_SUBLINE}>{UNREVIEWED_NOTE}</span>
        )
      ) : null}
    </>
  );
}

function OutcomeChips({
  value,
  counts,
  onChange,
}: {
  value: OutcomeFilter;
  counts: OutcomeCounts;
  onChange: (value: OutcomeFilter) => void;
}) {
  return (
    <div role="group" aria-label="Wynik projektu" className="flex flex-wrap items-center gap-1.5">
      {OUTCOME_CHIPS.map((chip) => {
        const n = chip.value === "all" ? outcomeTotal(counts) : counts[chip.value];
        const pressed = value === chip.value;
        return (
          <button
            key={chip.value}
            type="button"
            aria-pressed={pressed}
            onClick={() => onChange(chip.value)}
            className={cn(
              "inline-flex h-7 items-center gap-1.5 rounded-full border px-3 text-xs transition-colors",
              pressed
                ? chip.value === "won"
                  ? "border-success bg-success-muted font-semibold text-success-muted-foreground"
                  : "border-primary bg-primary/10 font-semibold text-foreground"
                : "border-border bg-card text-foreground hover:bg-muted",
            )}
          >
            {chip.label}
            <span className="tabular-nums text-muted-foreground">{n}</span>
          </button>
        );
      })}
    </div>
  );
}

// ── Section ───────────────────────────────────────────────────────────────────

type ProjectGroupKey = "unassigned" | "running" | "draft";

/**
 * Grupy aktywnych projektów (makieta 19.11.2026, wariant A ekranu Rekrutacje):
 * najpierw opublikowane bez przypisanego rekrutera — to, czym ktoś musi się
 * zająć — potem w toku i szkice. „Rekruter” = ta sama definicja co kolumna
 * „Rekruter” (`workingRecruiters`, przypisania zespołu rekrutacji), a nie pole
 * właściciela z profilu klienta — 19.11.2026 te dwa źródła różniły się
 * u PKO BP (34 i 16 „bez rekrutera”).
 */
export function groupActiveProjects(
  items: readonly ProjectJob[],
): { key: ProjectGroupKey; label: string; items: ProjectJob[] }[] {
  const unassigned: ProjectJob[] = [];
  const running: ProjectJob[] = [];
  const draft: ProjectJob[] = [];
  for (const job of items) {
    if (job.status !== "published") draft.push(job);
    else if (workingRecruiters(recruitersOf(job)).length === 0) unassigned.push(job);
    else running.push(job);
  }
  return [
    { key: "unassigned" as const, label: "Bez przypisanego rekrutera", items: unassigned },
    { key: "running" as const, label: "W toku", items: running },
    { key: "draft" as const, label: "Szkice", items: draft },
  ].filter((group) => group.items.length > 0);
}

function ProjectsSection({
  total,
  items,
  isLoading,
  isError,
  searching,
  emptyLabel,
  renderActions,
  grouped = false,
  onFillOutcome,
  stale = false,
}: {
  total: number;
  items: ProjectJob[];
  isLoading: boolean;
  isError: boolean;
  searching: boolean;
  emptyLabel: string;
  renderActions?: (job: ProjectJob) => React.ReactNode;
  /** Aktywne projekty w grupach (bez rekrutera · w toku · szkice). */
  grouped?: boolean;
  onFillOutcome?: (job: ProjectJob) => void;
  /** Stara lista widoczna, dopóki nie przyjdzie nowa (zmiana chipa wyniku). */
  stale?: boolean;
}) {
  const truncated = total > items.length;
  const showActions = Boolean(renderActions);
  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 rounded-lg border border-border py-6 text-sm text-muted-foreground">
        <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        Ładowanie…
      </div>
    );
  }
  if (isError) {
    return (
      <div className="rounded-lg border border-border py-6 text-center text-sm text-muted-foreground">
        Nie udało się załadować projektów.
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-border py-6 text-center text-sm text-muted-foreground">
        {/* Pustka po wyszukaniu ≠ brak projektów — inaczej czyta się jak
            utratę danych (ten sam wzorzec co w rejestrze umów B2B). */}
        {searching ? "Brak projektów pasujących do filtrów." : emptyLabel}
      </div>
    );
  }
  return (
    <div
      className={cn("space-y-2 transition-opacity", stale && "opacity-60")}
      aria-busy={stale || undefined}
    >
      <Table density="compact" className="min-w-[820px]">
        <TableHeader>
          <TableRow>
            <TableHead className={CALM_HEAD}>Projekt</TableHead>
            <TableHead className={CALM_HEAD}>Status</TableHead>
            <TableHead className={CALM_HEAD}>Otwarty</TableHead>
            <TableHead className={cn(CALM_HEAD, "text-right")}>Kandydaci</TableHead>
            <TableHead className={CALM_HEAD}>Rekruter</TableHead>
            {showActions ? (
              <TableHead className={cn(CALM_HEAD, "text-right")}>Akcje</TableHead>
            ) : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {grouped
            ? groupActiveProjects(items).map((group) => (
                <ProjectGroupRows
                  key={group.key}
                  group={group}
                  columns={showActions ? 6 : 5}
                  renderRow={(job) => (
                    <ProjectRow
                      key={job.id}
                      job={job}
                      actions={renderActions?.(job)}
                      showActions={showActions}
                      onFillOutcome={onFillOutcome}
                    />
                  )}
                />
              ))
            : items.map((job) => (
                <ProjectRow
                  key={job.id}
                  job={job}
                  actions={renderActions?.(job)}
                  showActions={showActions}
                  onFillOutcome={onFillOutcome}
                />
              ))}
        </TableBody>
      </Table>
      {truncated && (
        <p className="text-center text-xs text-muted-foreground">
          Pokazano {items.length} z {total}. Zawęź wyszukiwaniem, aby znaleźć
          pozostałe.
        </p>
      )}
    </div>
  );
}

function ProjectGroupRows({
  group,
  columns,
  renderRow,
}: {
  group: { key: ProjectGroupKey; label: string; items: ProjectJob[] };
  columns: number;
  renderRow: (job: ProjectJob) => React.ReactNode;
}) {
  return (
    <>
      <TableRow className="hover:bg-transparent">
        <TableCell
          colSpan={columns}
          className={cn(
            "pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wide",
            group.key === "unassigned" ? "text-warning-muted-foreground" : "text-muted-foreground",
          )}
        >
          {group.label} · {group.items.length}
        </TableCell>
      </TableRow>
      {group.items.map((job) => renderRow(job))}
    </>
  );
}

// ── Tab ───────────────────────────────────────────────────────────────────────

export function ProjectsTab({ clientId }: { clientId: number }) {
  // Przyciski tylko dla ról, którym backend nie odmówi (audyt S11).
  const user = useAuthStore((s) => s.user);
  const canAddCandidate = canMoveInPipeline(user);
  const canCloseLost = canCloseJobAsLost(user);
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const [opened, setOpened] = useState<JobOpenedRange>({});
  const reversed = openedRangeReversed(opened);
  // Odwrócony zakres nie idzie do serwera (422); lista zostaje bez zawężenia.
  const appliedOpened = reversed ? {} : opened;
  const openedActive = Object.keys(openedQueryParams(appliedOpened)).length > 0;
  const searching = debouncedSearch.trim().length > 0 || openedActive;
  const [reportOpen, setReportOpen] = useState(false);
  const reportAvailable = useQuery({
    queryKey: ["bnp-report-availability", clientId],
    enabled: canViewClientRate(user),
    staleTime: 300_000,
    queryFn: async () =>
      (await api.get(`/api/clients/${clientId}/bnp-report/availability`)).data as {
        available: boolean;
      },
  });

  // Akcje rekrutacji — jedyny dom po usunięciu sekcji „Otwarte rekrutacje"
  // z Profilu (ticket #3). CloseJobAsLostModal to JEDYNY caller
  // POST /api/jobs/{id}/close w całej aplikacji.
  const [addCandidateTo, setAddCandidateTo] = useState<ProjectJob | null>(null);
  const [closeJobAsLost, setCloseJobAsLost] = useState<ProjectJob | null>(null);

  // Jeden przełącznik zamiast dwóch akordeonów: renderujemy DOKŁADNIE jedną
  // listę, domyślnie aktywne. Stan lokalny, bez parametru w URL-u — spójnie
  // z podzakładkami w Profilu.
  const [bucket, setBucket] = useState<Bucket>("active");

  // OBA zapytania lecą ZAWSZE, bez `enabled:` — i to jest cecha, nie
  // przeoczenie. Ticket wymaga liczników przy obu opcjach niezależnie od
  // wyboru, a `enabled: bucket === …` zgasiłoby licznik niewybranej opcji do
  // `0` przez `?? 0` niżej, czyli skłamałby „brak zamkniętych projektów".
  // Dane oba, render jeden.
  const activeQuery = useQuery({
    queryKey: ["client-jobs", clientId, "active", debouncedSearch, appliedOpened],
    queryFn: () => fetchClientJobs(clientId, "active", debouncedSearch, appliedOpened),
    staleTime: 10_000,
  });
  // Chip wyniku zamkniętych (26.11.2026). Filtr idzie do serwera, liczniki
  // chipów wracają w tej samej odpowiedzi i nie zależą od wybranego chipa.
  const [outcomeFilter, setOutcomeFilter] = useState<OutcomeFilter>("all");
  const [fillOutcomeFor, setFillOutcomeFor] = useState<ProjectJob | null>(null);
  const closedQuery = useQuery({
    queryKey: ["client-jobs", clientId, "closed", debouncedSearch, appliedOpened, outcomeFilter],
    queryFn: () =>
      fetchClientJobs(clientId, "closed", debouncedSearch, appliedOpened, outcomeFilter),
    staleTime: 10_000,
    placeholderData: keepPreviousData,
  });
  const outcomeCounts = closedQuery.data?.outcomeCounts;
  // Licznik zakładki to wszystkie zamknięte, nie tylko te z wybranego chipa.
  const closedTotal = outcomeCounts
    ? outcomeTotal(outcomeCounts)
    : (closedQuery.data?.total ?? 0);
  // „Wszystkie” pobiera wiersze dopiero po wyborze; licznik to suma dwóch kubełków.
  const allQuery = useQuery({
    enabled: bucket === "all",
    queryKey: ["client-jobs", clientId, "all", debouncedSearch, appliedOpened],
    queryFn: () => fetchClientJobs(clientId, "all", debouncedSearch, appliedOpened),
    staleTime: 10_000,
  });

  const activeJobs = activeQuery.data?.items ?? [];
  const closedJobs = closedQuery.data?.items ?? [];

  return (
    <div className="space-y-3">
      {/* Przełącznik kubełków i wyszukiwarka w jednym rzędzie (makieta
          02.10.2026) — tabela zaczyna się wyżej. */}
      <div className="flex flex-wrap items-center gap-2">
        {/* Liczniki: awaria NIE może wyrenderować się jako „(0)" — to czyta się
            jako „nie ma zamkniętych projektów". Przy błędzie zdejmujemy liczbę
            i dopisujemy „(—)" do etykiety, a w trakcie ładowania nie pokazujemy
            nic (inaczej licznik mignąłby „0" zanim dojdą dane). */}
        <TabbedNav
          ariaLabel="Kubełki projektów klienta"
          className="sm:w-auto"
          listClassName="sm:w-auto"
          value={bucket}
          onValueChange={(v) => setBucket(v as Bucket)}
          tabs={[
            {
              value: "active",
              label: activeQuery.isError
                ? "Aktywne projekty (—)"
                : "Aktywne projekty",
              count:
                activeQuery.isError || activeQuery.isLoading
                  ? undefined
                  : (activeQuery.data?.total ?? 0),
            },
            {
              value: "closed",
              label: closedQuery.isError
                ? "Zamknięte projekty (—)"
                : "Zamknięte projekty",
              count:
                closedQuery.isError || closedQuery.isLoading
                  ? undefined
                  : closedTotal,
            },
            {
              value: "all",
              label: "Wszystkie",
              count:
                activeQuery.isSuccess && closedQuery.isSuccess
                  ? activeQuery.data.total + closedTotal
                  : undefined,
            },
          ]}
        />
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Szukaj projektu po nazwie…"
            aria-label="Szukaj projektów"
            className="h-9 w-full rounded-lg border border-border bg-card pl-9 pr-3 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground">Data otwarcia</span>
        <Input
          type="date"
          aria-label="Data otwarcia od"
          aria-invalid={reversed || undefined}
          className="h-9 w-[150px]"
          value={opened.from ?? ""}
          onChange={(e) => setOpened({ ...opened, from: e.target.value || undefined })}
        />
        <span className="text-muted-foreground">–</span>
        <Input
          type="date"
          aria-label="Data otwarcia do"
          aria-invalid={reversed || undefined}
          className="h-9 w-[150px]"
          value={opened.to ?? ""}
          onChange={(e) => setOpened({ ...opened, to: e.target.value || undefined })}
        />
        <Button
          size="sm"
          variant="outline"
          data-tour="client-projects.previous-month"
          onClick={() => {
            const { from, to } = previousMonth();
            setOpened({ from, to });
            setBucket("all");
          }}
        >
          Poprzedni miesiąc
        </Button>
        {opened.from || opened.to ? (
          <Button size="sm" variant="quiet" onClick={() => setOpened({})}>
            Wyczyść
          </Button>
        ) : null}
        {reportAvailable.data?.available ? (
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            onClick={() => setReportOpen(true)}
          >
            <FileSpreadsheet className="h-3.5 w-3.5" aria-hidden="true" />
            Raport miesięczny BNP
          </Button>
        ) : null}
      </div>
      {reversed ? (
        <p role="alert" className="text-xs text-destructive">
          Data „od” jest późniejsza niż „do” — popraw zakres, żeby go zastosować.
        </p>
      ) : null}

      {/* Renderujemy DOKŁADNIE jedną listę — niewybrany kubełek wychodzi z DOM,
          nie jest ukrywany CSS-em (inaczej „aktywne znikają" byłoby pozorne). */}
      {bucket === "active" ? (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-3 2xl:grid-cols-[minmax(0,1fr)_300px] 2xl:items-start">
        <ProjectsSection
          grouped
          total={activeQuery.data?.total ?? 0}
          items={activeJobs}
          isLoading={activeQuery.isLoading}
          isError={activeQuery.isError}
          searching={searching}
          emptyLabel="Brak aktywnych projektów."
          renderActions={(job) =>
            job.status === "published" && (canAddCandidate || canCloseLost) ? (
              <>
                {canAddCandidate ? (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setAddCandidateTo(job)}
                    title="Dodaj kandydata do pipeline"
                  >
                    <UserPlus className="h-3.5 w-3.5" aria-hidden="true" />
                    Dodaj
                  </Button>
                ) : null}
                {canCloseLost ? (
                  // Rzadka i nieodwracalna akcja w menu wiersza (makieta
                  // 19.11.2026), nie obok „Dodaj”, gdzie łatwo w nią trafić.
                  <DropdownMenu modal={false}>
                    <DropdownMenuTrigger asChild>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-8 w-8 p-0"
                        aria-label={`Więcej akcji: ${job.title}`}
                        title="Więcej akcji"
                      >
                        <Ellipsis className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        onSelect={() => window.setTimeout(() => setCloseJobAsLost(job), 0)}
                      >
                        <XCircle className="h-4 w-4" aria-hidden="true" />
                        Zamknij z powodem…
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : null}
              </>
            ) : null
          }
        />
        <ClientRecruitingSheet clientId={clientId} />
        </div>
      ) : bucket === "all" ? (
        <ProjectsSection
          total={allQuery.data?.total ?? 0}
          items={allQuery.data?.items ?? []}
          isLoading={allQuery.isLoading}
          isError={allQuery.isError}
          searching={searching}
          emptyLabel="Brak projektów."
          onFillOutcome={canCloseLost ? setFillOutcomeFor : undefined}
        />
      ) : (
        /* Bez `renderActions` — akcje rekrutacji nie mogą wyciec do zamkniętych. */
        <div className="space-y-2">
          {outcomeCounts ? (
            <OutcomeChips
              value={outcomeFilter}
              counts={outcomeCounts}
              onChange={setOutcomeFilter}
            />
          ) : null}
          <ProjectsSection
            total={closedQuery.data?.total ?? 0}
            items={closedJobs}
            isLoading={closedQuery.isLoading}
            isError={closedQuery.isError}
            searching={searching || outcomeFilter !== "all"}
            emptyLabel="Brak zamkniętych projektów."
            onFillOutcome={canCloseLost ? setFillOutcomeFor : undefined}
            stale={closedQuery.isPlaceholderData}
          />
        </div>
      )}

      {reportOpen ? (
        <BnpMonthlyReportDialog clientId={clientId} onClose={() => setReportOpen(false)} />
      ) : null}

      {addCandidateTo && (
        <AddCandidateToJobModal
          jobId={addCandidateTo.id}
          jobTitle={addCandidateTo.title}
          clientId={clientId}
          onClose={() => setAddCandidateTo(null)}
        />
      )}
      {fillOutcomeFor ? (
        <JobCloseWithReasonDialog
          mode="change"
          open
          onOpenChange={(open) => {
            if (!open) setFillOutcomeFor(null);
          }}
          jobId={fillOutcomeFor.id}
          jobTitle={fillOutcomeFor.title}
          clientId={clientId}
          initial={{
            reason: fillOutcomeFor.close_reason ?? null,
            notes: fillOutcomeFor.close_notes ?? null,
            duplicateOfJobId: fillOutcomeFor.duplicate_of_job_id ?? null,
          }}
          onClosed={() =>
            void queryClient.invalidateQueries({ queryKey: ["client-jobs", clientId] })
          }
        />
      ) : null}
      {closeJobAsLost && (
        <CloseJobAsLostModal
          jobId={closeJobAsLost.id}
          jobTitle={closeJobAsLost.title}
          clientId={clientId}
          onClose={() => setCloseJobAsLost(null)}
        />
      )}
    </div>
  );
}
