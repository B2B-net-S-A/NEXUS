"use client";

/**
 * SourcingHub — rama źródeł kandydatów nad C2 (zakładka „Pozyskiwanie",
 * program „Flow w języku C2", PR 2/7 — docs/c2-flow-program.md, krok 03).
 *
 * C2 (`AIMatchingSection` + `JobMatchDock`, zdefiniowane lokalnie w
 * `app/jobs/[id]/page.tsx`) zostaje SERCEM tego kroku i renderuje się bez
 * zmian jako `children` — ten komponent tylko dokłada nad nim ramę czterech
 * kart-źródeł (AI Matching, Wyszukaj manualnie, Podobne projekty, Portale)
 * z licznikami. „Kandydaci z podobnych projektów" i „Rekomendowani" —
 * dotąd bloki NAD rankingiem — stają się kartą/reveal-em pod ramą, a Historia
 * requestu dostaje kompaktowy podgląd trzech najbliższych requestów.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  Globe,
  Layers,
  Loader2,
  RefreshCw,
  Search,
  Sparkles,
} from "lucide-react";

import {
  historicalCandidatesApi,
  matchingApi,
  postingsApi,
  proposalsApi,
} from "@/lib/api";
import { savedSearchesApi, shortlistApi } from "@/lib/candidate-search-api";
import { jobShortlistQueryKey } from "@/components/v2/jobs/JobShortlist";
import { HistoricalCandidatesSection } from "@/components/HistoricalCandidatesSection";
import { SuggestedCandidatesWidget } from "@/components/SuggestedCandidatesWidget";
import { RequestHistorySection } from "@/components/RequestHistorySection";
import { formatCandidateLocation } from "@/components/v2/pages/candidate-list-helpers";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/Toast";
import { assignErrorMessage } from "@/lib/assign-error";
import { cn } from "@/lib/utils";
import type { JobDetailTab } from "@/components/v2/jobs/JobDetailCompactHeader";

// `postingsApi.list` nie ma własnego generyku (zwraca `any`) — `PostingsSection`
// w page.tsx typuje ją lokalnie tym samym wzorcem; robimy identycznie zamiast
// eksportować typ z page.tsx (plik strony, nie moduł).
interface JobPostingCount {
  status: string;
  applications: number;
}

interface SourcingHubProps {
  jobId: number;
  /** Nietypowane jak w sąsiedniej `AIMatchingSection` (page.tsx) — `job`
   *  pochodzi tam z `useQuery` bez generyku; dorabianie tu ściślejszego typu
   *  rozjechałoby się z tamtym propem dla tych samych danych. */
  job: any;
  readOnly: boolean;
  onTabChange: (tab: JobDetailTab) => void;
  /** C2 — renderowane DOKŁADNIE tak jak dziś, bez żadnych zmian. */
  children: ReactNode;
}

interface SourceCardStat {
  value: ReactNode;
  label: string;
  tone?: "default" | "success" | "warning";
}

function SourceCard({
  active,
  icon,
  title,
  pillLabel,
  pillVariant,
  description,
  stats,
  onClick,
  testId,
}: {
  active?: boolean;
  icon: ReactNode;
  title: string;
  pillLabel?: string;
  pillVariant?: ComponentProps<typeof Badge>["variant"];
  description: string;
  stats: SourceCardStat[];
  onClick: () => void;
  testId: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      data-testid={testId}
      className={cn(
        "flex flex-col gap-2 rounded-xl border p-3.5 text-left transition-colors",
        active
          ? "border-primary bg-primary/5 ring-1 ring-primary/20"
          : "border-border bg-card hover:border-primary/40 hover:bg-accent/40",
      )}
    >
      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <span className="text-primary">{icon}</span>
        {title}
        {pillLabel ? (
          <Badge variant={pillVariant ?? "outline"} size="sm" className="ml-auto shrink-0">
            {pillLabel}
          </Badge>
        ) : null}
      </div>
      <p className="text-xs leading-snug text-muted-foreground">{description}</p>
      {stats.length > 0 ? (
        <div className="mt-auto flex items-center gap-4 pt-1">
          {stats.map((s) => (
            <div key={s.label}>
              <div
                className={cn(
                  "text-base font-bold tabular-nums",
                  s.tone === "success" && "text-success",
                  s.tone === "warning" && "text-warning",
                  (!s.tone || s.tone === "default") && "text-foreground",
                )}
              >
                {s.value}
              </div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                {s.label}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </button>
  );
}

export function SourcingHub({
  jobId,
  job,
  readOnly,
  onTabChange,
  children,
}: SourcingHubProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // „Podobne projekty" — dotąd blok NAD rankingiem, domyślnie rozwinięty;
  // teraz karta w ramie, domyślnie zwinięta, POD ramą po kliknięciu. Wyjątek:
  // deep link z powiadomienia „Podobny request — gotowi kandydaci"
  // (?tab=similar) musi ją zamontować od razu, inaczej sekcja nie ma się
  // sama doscrollować/podświetlić (ta logika mieszka w niej i zostaje
  // nietknięta — patrz HistoricalCandidatesSection).
  const [similarOpen, setSimilarOpen] = useState(
    () => searchParams?.get("tab") === "similar",
  );
  const similarSectionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (searchParams?.get("tab") === "similar") setSimilarOpen(true);
  }, [searchParams]);

  // „Rekomendowani" — dotąd blok NAD rankingiem; teraz zwinięty pod ramą
  // (wątpliwość rozstrzygnięta na rzecz „zostaw go", bo część jego kontrolek
  // — lokalizacja+źródło, przełączniki budżetu/zdalności — nie ma dziś
  // odpowiednika 1:1 w C2). Deep link z AddJobModal (?highlight=ai-proposals)
  // przeniesiony tu razem z widgetem — page.tsx nadal przełącza samą
  // zakładkę na "ai-matching", żeby SourcingHub w ogóle się zamontował.
  const [recommendedOpen, setRecommendedOpen] = useState(
    () => searchParams?.get("highlight") === "ai-proposals",
  );
  const [recommendedGlow, setRecommendedGlow] = useState(false);
  const recommendedSectionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (searchParams?.get("highlight") !== "ai-proposals") return;
    setRecommendedOpen(true);
    setRecommendedGlow(true);
    // Let React paint the opened section before scrolling.
    const scrollTimer = window.setTimeout(() => {
      recommendedSectionRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }, 150);
    const glowTimer = window.setTimeout(() => setRecommendedGlow(false), 3000);
    const cleanupTimer = window.setTimeout(() => {
      if (pathname) router.replace(pathname, { scroll: false });
    }, 3200);
    return () => {
      window.clearTimeout(scrollTimer);
      window.clearTimeout(glowTimer);
      window.clearTimeout(cleanupTimer);
    };
  }, [searchParams, pathname, router]);

  // Historia requestu → „N kandydatów → źródło": `candidates-from-similar`
  // nie przyjmuje filtra po konkretnym requeście (patrz RequestHistorySection),
  // więc akcja po prostu otwiera i doscrollowuje kartę „Podobne projekty" —
  // czyli wszystkich kandydatów ze WSZYSTKICH bliźniaczych projektów, nie
  // tylko z requestu, z którego kliknięto (tooltip przycisku tłumaczy to).
  const handleCandidatesToSource = useCallback(() => {
    setSimilarOpen(true);
    window.setTimeout(() => {
      similarSectionRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }, 50);
  }, []);

  // ── AI Matching · C2 — liczniki ─────────────────────────────────────────
  // C2 (poniżej, w `children`) trzyma filtr lokalizacji we WŁASNYM stanie
  // i jego klucz zapytania to `["ai-matches", jobId, locationFilter.trim()]`
  // — rama nie ma dostępu do tego stanu (i nie powinna go duplikować), więc
  // liczy ranking na klucz BEZ trzeciego segmentu (bez filtra lokalizacji).
  // To osobne zapytanie sieciowe — react-query dedupe działa tylko po
  // identycznym kluczu, a `["ai-matches", jobId]` nigdy nim nie jest, nawet
  // gdy filtr C2 jest pusty (`["ai-matches", jobId, ""]` ma inną długość).
  // Świadomy, mały koszt: rama pokazuje domyślny (bez-lokalizacyjny) ranking.
  const matchesQuery = useQuery({
    queryKey: ["ai-matches", jobId],
    queryFn: () => matchingApi.getMatches(jobId).then((r) => r.data),
    staleTime: 60_000,
  });
  const matchesCount = matchesQuery.data?.matches.length ?? 0;
  const hiddenMeta = matchesQuery.data?.meta?.hidden;
  const hiddenTotal = (hiddenMeta?.over_budget ?? 0) + (hiddenMeta?.remote_only ?? 0);
  const matchesFailed = matchesQuery.isLoading || matchesQuery.isError;

  // Ten sam klucz co przełącznik Ranking/Shortlista w C2 i JobShortlist —
  // react-query deduplikuje, jeden fetch karmi oba liczniki.
  const shortlistQuery = useQuery({
    queryKey: jobShortlistQueryKey(jobId),
    queryFn: () => shortlistApi.list(jobId),
    staleTime: 30_000,
  });

  const regenerateMutation = useMutation({
    mutationFn: () => {
      if (readOnly) {
        throw new Error("Sekcja Pozyskiwanie jest dostępna tylko do odczytu.");
      }
      return proposalsApi.regenerate(jobId);
    },
    onSuccess: () => {
      // Fuzzy match (domyślne `exact: false`) — `["ai-matches", jobId]` łapie
      // TAKŻE klucz C2 (`["ai-matches", jobId, locationFilter]`), więc jedno
      // kliknięcie odświeża oba rankingi. `proposal-latest` karmi snapshot
      // widoczny w zwiniętej karcie „Rekomendowani" niżej.
      queryClient.invalidateQueries({ queryKey: ["ai-matches", jobId] });
      queryClient.invalidateQueries({ queryKey: ["proposal-latest", jobId] });
      showSuccess("Propozycje AI zostały odświeżone.");
    },
    onError: (error: unknown) => showError(assignErrorMessage(error)),
  });

  // ── Podobne projekty — liczniki (TEN SAM klucz i parametry co
  // HistoricalCandidatesSection poniżej — react-query dedupe: gdy karta się
  // otworzy i zamontuje ten komponent, dostaje dane z cache'u bez drugiego
  // zapytania, dopóki `staleTime` nie minie). ────────────────────────────
  const historicalQuery = useQuery({
    queryKey: ["historical-candidates", jobId],
    queryFn: async () =>
      (
        await historicalCandidatesApi.forJob(jobId, {
          tier: "primary",
          limit: 20,
          include_negative: true,
        })
      ).data,
    staleTime: 60_000,
  });
  const historicalFailed = historicalQuery.isLoading || historicalQuery.isError;
  const historicalCount = historicalQuery.data?.candidates.length ?? 0;
  const topSimilarityPct = useMemo(() => {
    const jobs = historicalQuery.data?.similar_jobs ?? [];
    if (jobs.length === 0) return null;
    return Math.round(Math.max(...jobs.map((j) => j.similarity ?? 0)) * 100);
  }, [historicalQuery.data]);

  // ── Wyszukaj manualnie — licznik zapisanych/zatwierdzonych strategii ────
  // Wyszukiwania rekomendowane przez AI (ChampionRecommendedSearches)
  // materializują się jako SavedSearch przypięty do tej rekrutacji po
  // zatwierdzeniu przez DL — to jest ten licznik. Tanie: jedno filtrowane
  // zapytanie, bez pociągania profilu Championa tylko po tę liczbę.
  const pinnedSearchesQuery = useQuery({
    queryKey: ["saved-searches", "candidates", "pinned-to-job", jobId],
    queryFn: () =>
      savedSearchesApi.list({ entity: "candidates", pinned_to_job_id: jobId }),
    staleTime: 60_000,
  });

  // ── Portale — licznik (TEN SAM klucz co PostingsSection w page.tsx) ─────
  const postingsQuery = useQuery<JobPostingCount[]>({
    queryKey: ["postings", jobId],
    queryFn: () => postingsApi.list(jobId).then((r) => r.data),
    staleTime: 60_000,
  });
  const postings = postingsQuery.data ?? [];
  const postingsFailed = postingsQuery.isLoading || postingsQuery.isError;
  const applicationsTotal = postings.reduce(
    (sum, p) => sum + (p.applications ?? 0),
    0,
  );

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {/* AI Matching · C2 — domyślna, aktywna. Nie jest przyciskiem-
            nawigacją (C2 jest tu, tuż niżej) — niesie tylko liczniki i
            drugorzędną akcję „Odśwież propozycje" przeniesioną z dawnego
            widgetu „Rekomendowani". */}
        <div
          data-testid="sourcing-ai-matching-card"
          className="flex flex-col gap-2 rounded-xl border border-primary bg-primary/5 p-3.5 ring-1 ring-primary/20"
        >
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Sparkles className="h-4 w-4 text-primary" />
            AI Matching · C2
            <Badge variant="success" size="sm" className="ml-auto shrink-0">
              Semantic AI
            </Badge>
          </div>
          <p className="text-xs leading-snug text-muted-foreground">
            Ranking po dopasowaniu do tej rekrutacji, bramka dopuszczalności,
            shortlista.
          </p>
          <div className="mt-auto flex flex-wrap items-center gap-4 pt-1">
            <div>
              <div className="text-base font-bold tabular-nums text-foreground">
                {matchesFailed ? "—" : matchesCount}
              </div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                w rankingu
              </div>
            </div>
            <div>
              <div className="text-base font-bold tabular-nums text-warning">
                {matchesFailed ? "—" : hiddenTotal}
              </div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                ukryto
              </div>
            </div>
            <div>
              <div className="text-base font-bold tabular-nums text-foreground">
                {shortlistQuery.isLoading || shortlistQuery.isError
                  ? "—"
                  : (shortlistQuery.data?.length ?? 0)}
              </div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                shortlista
              </div>
            </div>
            {!readOnly ? (
              <button
                type="button"
                onClick={() => regenerateMutation.mutate()}
                disabled={regenerateMutation.isPending}
                title="Przelicz snapshot propozycji AI dla tej rekrutacji"
                className="ml-auto inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent disabled:opacity-50"
              >
                {regenerateMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                Odśwież propozycje
              </button>
            ) : null}
          </div>
        </div>

        <SourceCard
          testId="sourcing-manual-search-card"
          icon={<Search className="h-4 w-4" />}
          title="Wyszukaj manualnie"
          pillLabel="prefill z rekrutacji"
          description="Pełna wyszukiwarka: frazy, kategorie, skille, lata, miasto, status. Bulk-add do pipeline'u."
          stats={
            pinnedSearchesQuery.isSuccess
              ? [
                  {
                    value: pinnedSearchesQuery.data?.length ?? 0,
                    label: "zapisane strategie",
                  },
                ]
              : []
          }
          onClick={() => onTabChange("manual-search")}
        />

        <SourceCard
          testId="sourcing-similar-projects-card"
          active={similarOpen}
          icon={<Layers className="h-4 w-4" />}
          title="Podobne projekty"
          pillLabel="historia requestu"
          description="Kandydaci z bliźniaczych rekrutacji. Ci, którzy doszli do klienta, pierwsi."
          stats={[
            { value: historicalFailed ? "—" : historicalCount, label: "kandydatów" },
            ...(topSimilarityPct != null
              ? [{ value: `${topSimilarityPct}%`, label: "najbliższy request" } as SourceCardStat]
              : []),
          ]}
          onClick={() => setSimilarOpen((v) => !v)}
        />

        <SourceCard
          testId="sourcing-portals-card"
          icon={<Globe className="h-4 w-4" />}
          title="Portale ogłoszeniowe"
          pillLabel="symulowane"
          pillVariant="warning"
          description="Publikuj na wszystkich / Opublikuj ogłoszenie. Integracja w przygotowaniu — dane symulowane."
          stats={[
            { value: postingsFailed ? "—" : postings.length, label: "publikacji" },
            { value: postingsFailed ? "—" : applicationsTotal, label: "aplikacji" },
          ]}
          onClick={() => onTabChange("portals")}
        />
      </div>

      {similarOpen ? (
        <div ref={similarSectionRef}>
          <HistoricalCandidatesSection jobId={jobId} readOnly={readOnly} />
        </div>
      ) : null}

      <div
        ref={recommendedSectionRef}
        className={cn(
          "rounded-xl border border-border bg-card transition-shadow",
          recommendedGlow &&
            "ring-2 ring-primary ring-offset-2 ring-offset-background shadow-lg",
        )}
      >
        <button
          type="button"
          onClick={() => setRecommendedOpen((v) => !v)}
          aria-expanded={recommendedOpen}
          aria-controls="recommended-candidates-content"
          className="flex w-full items-center gap-2 p-3 text-left"
        >
          <Sparkles className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold text-foreground">
            Rekomendowani (tryb snapshot)
          </span>
          <span className="ml-auto inline-flex items-center gap-1 text-xs text-primary">
            {recommendedOpen ? "Zwiń" : "Rozwiń"}
            {recommendedOpen ? (
              <ChevronUp className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
          </span>
        </button>
        {recommendedOpen ? (
          <div id="recommended-candidates-content" className="border-t border-border p-3">
            <SuggestedCandidatesWidget
              jobId={jobId}
              defaultLocation={formatCandidateLocation(job?.location)}
              jobHasBudget={job?.has_budget_hourly ?? true}
              readOnly={readOnly}
            />
          </div>
        ) : null}
      </div>

      {/* C2 — warsztat AI Matching, bez zmian. */}
      {children}

      <RequestHistorySection
        jobId={jobId}
        clientId={job?.client_id ?? null}
        readOnly={readOnly}
        compact
        maxItems={3}
        onCandidatesToSource={handleCandidatesToSource}
      />
    </div>
  );
}

export type { SourcingHubProps };
