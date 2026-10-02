"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, UserPlus, XCircle } from "lucide-react";
import api from "@/lib/api";
import { TabbedNav } from "@/components/ds";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
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
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
import { AddCandidateToJobModal } from "@/components/client-profile/actions/AddCandidateToJobModal";
import { CloseJobAsLostModal } from "@/components/client-profile/actions/CloseJobAsLostModal";
import {
  canCloseJobAsLost,
  canMoveInPipeline,
} from "@/components/client-profile/permissions";
import { useAuthStore } from "@/store/auth";

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
}

const STATUS_VIEW: Record<string, { label: string; tone: StatusDotTone }> = {
  published: { label: "Aktywna", tone: "success" },
  draft: { label: "Szkic", tone: "neutral" },
};
const CLOSED_STATUS = { label: "Zamknięta", tone: "danger" } as const;

function openedDate(job: ProjectJob): string | null {
  return job.opened_effective_at ?? job.opened_at ?? job.created_at ?? null;
}

interface JobsPage {
  items: ProjectJob[];
  total: number;
}

type Bucket = "active" | "closed";

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
): Promise<JobsPage> {
  const params: Record<string, unknown> = {
    client_id: clientId,
    page_size: PAGE_SIZE,
  };
  if (bucket === "active") {
    // open_only = status in (draft, published) — "aktywne / w toku".
    params.open_only = true;
  } else {
    params.status = "closed";
  }
  const trimmed = q.trim();
  if (trimmed) params.q = trimmed;

  const r = await api.get("/api/jobs", { params });
  const data = r.data ?? {};
  if (Array.isArray(data)) {
    return { items: data, total: data.length };
  }
  const items: ProjectJob[] = Array.isArray(data.items) ? data.items : [];
  return { items, total: typeof data.total === "number" ? data.total : items.length };
}

// ── Row ───────────────────────────────────────────────────────────────────────

function ProjectRow({
  job,
  actions,
  showActions,
}: {
  job: ProjectJob;
  /** Akcje rekrutacji (Dodaj / Przegrana) — przeniesione z usuniętej sekcji
      „Otwarte rekrutacje" w Profilu (ticket #3); Projekty są teraz jedynym
      miejscem zarządzania rekrutacjami klienta. */
  actions?: React.ReactNode;
  /** Kolumna „Akcje" istnieje (aktywne projekty) — komórka jest zawsze. */
  showActions: boolean;
}) {
  const status = STATUS_VIEW[job.status] ?? CLOSED_STATUS;
  const opened = openedDate(job);
  const recruiters = workingRecruiters(recruitersOf(job));
  const subline = [job.location, job.client_reference].filter(Boolean).join(" · ");
  return (
    <TableRow className="h-[54px]">
      <TableCell>
        {/* Nawigacja do rekrutacji zostaje na tytule; akcje są osobnymi
            przyciskami w ostatniej kolumnie (przycisk nie może siedzieć w linku). */}
        <a
          href={`/jobs/${job.id}`}
          className="block max-w-[460px] truncate font-semibold text-foreground hover:text-primary hover:underline"
        >
          {job.title}
        </a>
        {subline ? (
          <span className={cn(CALM_SUBLINE, "max-w-[460px] truncate")}>{subline}</span>
        ) : null}
      </TableCell>
      <TableCell>
        <StatusDot tone={status.tone}>{status.label}</StatusDot>
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

// ── Section ───────────────────────────────────────────────────────────────────

function ProjectsSection({
  total,
  items,
  isLoading,
  isError,
  searching,
  emptyLabel,
  renderActions,
}: {
  total: number;
  items: ProjectJob[];
  isLoading: boolean;
  isError: boolean;
  searching: boolean;
  emptyLabel: string;
  renderActions?: (job: ProjectJob) => React.ReactNode;
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
        {searching ? "Brak projektów pasujących do wyszukiwania." : emptyLabel}
      </div>
    );
  }
  return (
    <div className="space-y-2">
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
          {items.map((job) => (
            <ProjectRow
              key={job.id}
              job={job}
              actions={renderActions?.(job)}
              showActions={showActions}
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

// ── Tab ───────────────────────────────────────────────────────────────────────

export function ProjectsTab({ clientId }: { clientId: number }) {
  // Przyciski tylko dla ról, którym backend nie odmówi (audyt S11).
  const user = useAuthStore((s) => s.user);
  const canAddCandidate = canMoveInPipeline(user);
  const canCloseLost = canCloseJobAsLost(user);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const searching = debouncedSearch.trim().length > 0;

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
    queryKey: ["client-jobs", clientId, "active", debouncedSearch],
    queryFn: () => fetchClientJobs(clientId, "active", debouncedSearch),
    staleTime: 10_000,
  });
  const closedQuery = useQuery({
    queryKey: ["client-jobs", clientId, "closed", debouncedSearch],
    queryFn: () => fetchClientJobs(clientId, "closed", debouncedSearch),
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
                  : (closedQuery.data?.total ?? 0),
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

      {/* Renderujemy DOKŁADNIE jedną listę — niewybrany kubełek wychodzi z DOM,
          nie jest ukrywany CSS-em (inaczej „aktywne znikają" byłoby pozorne). */}
      {bucket === "active" ? (
        <ProjectsSection
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
                  <Button
                    size="sm"
                    variant="quiet"
                    onClick={() => setCloseJobAsLost(job)}
                    title="Zamknij jako przegraną"
                  >
                    <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
                    Przegrana
                  </Button>
                ) : null}
              </>
            ) : null
          }
        />
      ) : (
        /* Bez `renderActions` — akcje rekrutacji nie mogą wyciec do zamkniętych. */
        <ProjectsSection
          total={closedQuery.data?.total ?? 0}
          items={closedJobs}
          isLoading={closedQuery.isLoading}
          isError={closedQuery.isError}
          searching={searching}
          emptyLabel="Brak zamkniętych projektów."
        />
      )}

      {addCandidateTo && (
        <AddCandidateToJobModal
          jobId={addCandidateTo.id}
          jobTitle={addCandidateTo.title}
          clientId={clientId}
          onClose={() => setAddCandidateTo(null)}
        />
      )}
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
