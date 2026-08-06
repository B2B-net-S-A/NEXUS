"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Briefcase, ExternalLink, Search, UserPlus, XCircle } from "lucide-react";
import api from "@/lib/api";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
import { AddCandidateToJobModal } from "@/components/client-profile/actions/AddCandidateToJobModal";
import { CloseJobAsLostModal } from "@/components/client-profile/actions/CloseJobAsLostModal";

// ── Types ─────────────────────────────────────────────────────────────────────

// "Projekty" u klienta = oferty pracy / zapytania rekrutacyjne (Job). Podział na
// aktywne vs zamknięte jest wyprowadzany z istniejącego `status` (draft |
// published | closed) — dane NIE wymagają migracji: każdy rekord ma już status,
// więc segregacja jest czysto prezentacyjna (grupowanie po statusie).
interface ProjectJob {
  id: number;
  title: string;
  location: string | null;
  status: string;
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
}: {
  job: ProjectJob;
  /** Akcje rekrutacji (Dodaj / Lost) — przeniesione z usuniętej sekcji
      „Otwarte rekrutacje" w Profilu (ticket #3); Projekty są teraz jedynym
      miejscem zarządzania rekrutacjami klienta. */
  actions?: React.ReactNode;
}) {
  // Wiersz to <div>, nie <a> — akcje (przyciski) nie mogą być zagnieżdżone
  // w linku; nawigacja do rekrutacji zostaje na tytule + ikonie.
  return (
    <div className="flex items-center gap-3 p-3 bg-card dark:bg-muted border border-border dark:border-border rounded-xl hover:border-purple-300 transition-colors group">
      <a
        href={`/jobs/${job.id}`}
        className="flex items-center gap-3 flex-1 min-w-0"
      >
        <div className="w-8 h-8 bg-purple-50 dark:bg-purple-900/30 rounded-lg flex items-center justify-center shrink-0">
          <Briefcase className="w-4 h-4 text-purple-600" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-foreground dark:text-muted-foreground truncate">
            {job.title}
          </p>
          {job.location && (
            <p className="text-xs text-muted-foreground truncate">{job.location}</p>
          )}
        </div>
      </a>
      <div className="flex items-center gap-2 shrink-0">
        {actions}
        <span
          className={cn(
            "text-xs px-2 py-0.5 rounded-full font-medium",
            job.status === "published"
              ? "bg-green-100 text-green-700"
              : job.status === "draft"
                ? "bg-muted text-muted-foreground"
                : "bg-destructive/15 text-destructive",
          )}
        >
          {job.status === "published"
            ? "Aktywna"
            : job.status === "draft"
              ? "Szkic"
              : "Zamknięta"}
        </span>
        <a
          href={`/jobs/${job.id}`}
          aria-label={`Przejdź do rekrutacji ${job.title}`}
        >
          <ExternalLink className="w-3.5 h-3.5 text-muted-foreground group-hover:text-purple-500 transition-colors" />
        </a>
      </div>
    </div>
  );
}

// ── Section ───────────────────────────────────────────────────────────────────

function ProjectsSection({
  title,
  tone,
  total,
  items,
  isLoading,
  isError,
  searching,
  emptyLabel,
  open,
  onToggle,
  renderActions,
}: {
  title: string;
  tone: Bucket;
  total: number;
  items: ProjectJob[];
  isLoading: boolean;
  isError: boolean;
  searching: boolean;
  emptyLabel: string;
  open: boolean;
  onToggle: (event: React.SyntheticEvent<HTMLDetailsElement>) => void;
  renderActions?: (job: ProjectJob) => React.ReactNode;
}) {
  const truncated = total > items.length;
  return (
    <details
      open={open}
      onToggle={onToggle}
      className="border border-border rounded-lg group"
    >
      <summary className="cursor-pointer select-none p-4 font-medium flex items-center gap-2 hover:bg-accent/30">
        <Briefcase
          className={cn(
            "w-4 h-4",
            tone === "active" ? "text-purple-600" : "text-muted-foreground",
          )}
        />
        <span>{title}</span>
        <span
          className="text-xs font-semibold px-2 py-0.5 rounded-full bg-muted text-muted-foreground"
          aria-label={isLoading ? "Ładowanie liczby projektów" : `Liczba: ${total}`}
        >
          {/* "…" w trakcie ładowania — inaczej licznik mignąłby "0" zanim
              dojdą dane. */}
          {isLoading ? "…" : total}
        </span>
        <span className="ml-auto text-xs text-muted-foreground group-open:hidden">
          rozwiń
        </span>
      </summary>
      <div className="p-4 pt-0 border-t border-border space-y-2">
        {isLoading ? (
          <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
            <div className="w-4 h-4 border-2 border-purple-400 border-t-transparent rounded-full animate-spin" />
            Ładowanie…
          </div>
        ) : isError ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            Nie udało się załadować projektów.
          </div>
        ) : items.length === 0 ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            {/* Pustka po wyszukaniu ≠ brak projektów — inaczej czyta się jak
                utratę danych (ten sam wzorzec co w rejestrze umów B2B). */}
            {searching
              ? "Brak projektów pasujących do wyszukiwania."
              : emptyLabel}
          </div>
        ) : (
          <>
            {items.map((job) => (
              <ProjectRow key={job.id} job={job} actions={renderActions?.(job)} />
            ))}
            {truncated && (
              <p className="pt-1 text-center text-xs text-muted-foreground">
                Pokazano {items.length} z {total}. Zawęź wyszukiwaniem, aby
                znaleźć pozostałe.
              </p>
            )}
          </>
        )}
      </div>
    </details>
  );
}

// ── Tab ───────────────────────────────────────────────────────────────────────

export function ProjectsTab({ clientId }: { clientId: number }) {
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 300);
  const searching = debouncedSearch.trim().length > 0;

  // Akcje rekrutacji — jedyny dom po usunięciu sekcji „Otwarte rekrutacje"
  // z Profilu (ticket #3). CloseJobAsLostModal to JEDYNY caller
  // POST /api/jobs/{id}/close w całej aplikacji.
  const [addCandidateTo, setAddCandidateTo] = useState<ProjectJob | null>(null);
  const [closeJobAsLost, setCloseJobAsLost] = useState<ProjectJob | null>(null);

  // Aktywne rozwinięte domyślnie (wymóg: "domyślnie widoczna sekcja Aktywne"),
  // zamknięte zwinięte. Aktywne wyszukiwanie wymusza rozwinięcie obu sekcji, żeby
  // trafienie w zwiniętej sekcji zamkniętych nie było niewidoczne.
  const [openActive, setOpenActive] = useState(true);
  const [openClosed, setOpenClosed] = useState(false);

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
    <div className="space-y-4">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Szukaj projektu po nazwie…"
          aria-label="Szukaj projektów"
          className="w-full border border-border rounded-lg pl-9 pr-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
        />
      </div>

      <ProjectsSection
        title="Aktywne projekty"
        tone="active"
        total={activeQuery.data?.total ?? 0}
        items={activeJobs}
        isLoading={activeQuery.isLoading}
        isError={activeQuery.isError}
        searching={searching}
        emptyLabel="Brak aktywnych projektów."
        open={searching ? true : openActive}
        onToggle={(e) => {
          if (!searching) setOpenActive(e.currentTarget.open);
        }}
        renderActions={(job) =>
          job.status === "published" ? (
            <>
              <button
                onClick={() => setAddCandidateTo(job)}
                title="Dodaj kandydata do pipeline"
                className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-900/30 hover:bg-purple-100 dark:hover:bg-purple-900/50 rounded-md transition-colors"
              >
                <UserPlus className="w-3 h-3" />
                Dodaj
              </button>
              <button
                onClick={() => setCloseJobAsLost(job)}
                title="Zamknij jako przegraną"
                className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-destructive dark:text-red-300 hover:bg-destructive/10 dark:hover:bg-red-900/30 rounded-md transition-colors"
              >
                <XCircle className="w-3 h-3" />
                Lost
              </button>
            </>
          ) : null
        }
      />

      <ProjectsSection
        title="Zamknięte projekty"
        tone="closed"
        total={closedQuery.data?.total ?? 0}
        items={closedJobs}
        isLoading={closedQuery.isLoading}
        isError={closedQuery.isError}
        searching={searching}
        emptyLabel="Brak zamkniętych projektów."
        open={searching ? true : openClosed}
        onToggle={(e) => {
          if (!searching) setOpenClosed(e.currentTarget.open);
        }}
      />

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
