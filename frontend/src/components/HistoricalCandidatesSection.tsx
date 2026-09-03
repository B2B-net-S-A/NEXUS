"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Clock,
  Sparkles,
  UserCheck,
  Building2,
  Plus,
  Check,
  CheckSquare,
  Square,
  Loader2,
  Ban,
} from "lucide-react";
import {
  historicalCandidatesApi,
  type CandidatesFromSimilarResponse,
  type HistoricalCandidate,
  type HistoricalSource,
} from "@/lib/api";
import { proposalsBulkApi } from "@/lib/candidate-search-api";
import { useToast } from "@/components/Toast";
import { assignErrorMessage } from "@/lib/assign-error";
import {
  httpStatusFromError,
  isBlockingViewState,
  resolveViewState,
} from "@/lib/view-state";
import {
  QueryStateNotice,
  type BlockingViewState,
} from "@/components/ds/QueryStateNotice";

interface Props {
  jobId: number;
  readOnly?: boolean;
}

// Notatka job-scoped doklejana przy hurtowym przepinaniu (widoczna w
// timeline kandydata przy tej rekrutacji).
const BULK_REPIN_NOTE =
  "Przepięty hurtowo z sekcji „Kandydaci z podobnych projektów” (szybkie przepinanie).";

const STAGE_LABEL_PL: Record<string, string> = {
  new: "Nowy",
  prep_call: "Prep call",
  screening: "Screening",
  interview: "Interview",
  cv_sent: "CV wysłane",
  client_interview: "Rozmowa u klienta",
  acceptance: "Akceptacja",
  negotiation: "Negocjacje",
  onboarding: "Onboarding",
  hired: "Zatrudniony",
  rejected: "Odrzucony",
  withdrawn: "Wycofał się",
};

function stageLabel(stage: string): string {
  return STAGE_LABEL_PL[stage] ?? stage;
}

function formatMonthsAgo(months: number): string {
  if (months < 1) return "<1 mies. temu";
  if (months < 2) return "1 mies. temu";
  if (months < 12) return `${Math.round(months)} mies. temu`;
  const years = months / 12;
  if (years < 1.5) return "~1 rok temu";
  return `~${Math.round(years)} lat temu`;
}

function AvailabilityBadge({ value }: { value: HistoricalCandidate["current_availability"] }) {
  if (value === "available") {
    return (
      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-green-100 text-green-700">
        dostępny
      </span>
    );
  }
  if (value === "busy") {
    return (
      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">
        w projekcie
      </span>
    );
  }
  return (
    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
      nieznany status
    </span>
  );
}

function TierBadge({ tier }: { tier: HistoricalCandidate["tier"] }) {
  const cls =
    tier === "A"
      ? "bg-indigo-100 text-indigo-700 border-indigo-200"
      : "bg-slate-100 text-slate-600 border-slate-200";
  return (
    <span
      className={`text-[10px] font-medium px-1.5 py-0.5 rounded border ${cls}`}
      title={
        tier === "A"
          ? "Tier A — projekt bardzo podobny (cosine ≥ 0.70)"
          : "Tier B — projekt pokrewny (cosine ≥ 0.55)"
      }
    >
      Tier {tier}
    </span>
  );
}

function SourcesList({ sources }: { sources: HistoricalSource[] }) {
  if (sources.length === 0) return null;
  return (
    <ul className="mt-2 space-y-1 pl-6">
      {sources.map((s) => (
        <li key={`${s.job_id}-${s.moved_at}`} className="text-xs text-slate-600">
          <Link
            href={`/jobs/${s.job_id}`}
            className="font-medium text-indigo-600 hover:underline"
          >
            {s.job_title}
          </Link>
          <span className="mx-1 text-slate-400">·</span>
          <span>{stageLabel(s.stage)}</span>
          <span className="mx-1 text-slate-400">·</span>
          <span className="inline-flex items-center gap-0.5">
            <Clock className="h-3 w-3" />
            {formatMonthsAgo(s.months_ago)}
          </span>
          <span className="mx-1 text-slate-400">·</span>
          <span title="Podobieństwo projektów (cosine)">
            sim {(s.similarity * 100).toFixed(0)}%
          </span>
        </li>
      ))}
    </ul>
  );
}

function CandidateRow({
  candidate,
  jobId,
  isAdded,
  isSelected,
  onToggleSelect,
  onAdded,
  readOnly,
}: {
  candidate: HistoricalCandidate;
  jobId: number;
  isAdded: boolean;
  isSelected: boolean;
  onToggleSelect: (id: number) => void;
  onAdded: (id: number) => void;
  readOnly: boolean;
}) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const Icon = open ? ChevronDown : ChevronRight;
  const initials = `${candidate.name.charAt(0)}${candidate.lastname.charAt(0)}`.toUpperCase();
  const fullName = `${candidate.name} ${candidate.lastname}`.trim();

  const addMutation = useMutation({
    mutationFn: () =>
      proposalsBulkApi.add(jobId, { candidate_ids: [candidate.candidate_id] }),
    onSuccess: (res) => {
      // Refresh the kanban so a newly-added candidate appears immediately.
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      const ok =
        res.total_added > 0 ||
        res.skipped.some((s) => s.reason === "already_in_job");
      if (res.total_added > 0) {
        showSuccess(`${fullName} — dodano do pipeline`);
      } else if (res.skipped.some((s) => s.reason === "already_in_job")) {
        showSuccess(`${fullName} jest już w pipeline tej rekrutacji`);
      } else {
        const reason = res.skipped[0]?.reason;
        showError(
          reason === "blacklisted"
            ? `${fullName} jest na czarnej liście`
            : "Nie udało się dodać kandydata do pipeline",
        );
      }
      if (ok) onAdded(candidate.candidate_id);
    },
    onError: (error: unknown) => showError(assignErrorMessage(error)),
  });

  const inPipeline = isAdded;

  return (
    <li className="border border-slate-200 rounded-lg bg-card">
      <div className="flex items-center gap-2 p-3">
        {/* Multi-select do hurtowego przepinania. */}
        {!readOnly ? (
          <input
            type="checkbox"
            checked={isSelected}
            disabled={inPipeline}
            onChange={() => onToggleSelect(candidate.candidate_id)}
            aria-label={`Zaznacz ${fullName}`}
            className="h-4 w-4 shrink-0 rounded border-slate-300 accent-indigo-600 disabled:opacity-40"
          />
        ) : null}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex flex-1 items-center gap-3 text-left min-w-0 rounded-md hover:opacity-80"
        >
          <Icon className="h-4 w-4 text-slate-400 shrink-0" />
          <div className="h-8 w-8 rounded-full bg-indigo-100 text-indigo-700 text-xs font-semibold flex items-center justify-center shrink-0">
            {candidate.avatar_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={candidate.avatar_url}
                alt=""
                className="h-8 w-8 rounded-full object-cover"
              />
            ) : (
              initials
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <Link
                href={`/candidates/${candidate.candidate_id}`}
                className="text-sm font-medium text-slate-900 hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {candidate.name} {candidate.lastname}
              </Link>
              <TierBadge tier={candidate.tier} />
              <AvailabilityBadge value={candidate.current_availability} />
              {candidate.same_client && !candidate.rejected_by_same_client ? (
                <span
                  className="inline-flex items-center gap-0.5 text-[10px] font-medium px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700"
                  title="Kandydat był już rozważany u tego klienta — najszybsza ścieżka"
                >
                  <Building2 className="h-3 w-3" />
                  znany klientowi
                </span>
              ) : null}
              {candidate.recommended_count > 1 ? (
                <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-violet-100 text-violet-700">
                  {candidate.recommended_count}× rekomendowany
                </span>
              ) : null}
              {candidate.rejected_by_same_client ? (
                <span
                  className="inline-flex items-center gap-0.5 text-[10px] font-semibold px-1.5 py-0.5 rounded bg-destructive/15 text-destructive"
                  title="Ten klient odrzucił już tego kandydata (lub kandydat się wycofał) na podobnym projekcie — ponowne wysłanie wymaga świadomej decyzji"
                >
                  <Ban className="h-3 w-3" />
                  klient odrzucił wcześniej
                </span>
              ) : candidate.negative_signal ? (
                <span
                  className="inline-flex items-center gap-0.5 text-[10px] font-medium px-1.5 py-0.5 rounded bg-destructive/15 text-destructive"
                  title="Kandydat został wcześniej odrzucony lub się wycofał w podobnym projekcie"
                >
                  <AlertTriangle className="h-3 w-3" />
                  uwaga
                </span>
              ) : null}
            </div>
            {candidate.competence_category ? (
              <p className="text-xs text-slate-500 truncate">
                {candidate.competence_category}
              </p>
            ) : null}
          </div>
          <div className="text-right shrink-0">
            <div className="text-xs text-slate-500">Historical score</div>
            <div className="text-sm font-semibold text-slate-900">
              {candidate.historical_score.toFixed(2)}
            </div>
          </div>
        </button>

        {/* Add this historical candidate straight into the job's pipeline. */}
        {!readOnly ? <button
          type="button"
          onClick={() => addMutation.mutate()}
          disabled={addMutation.isPending || inPipeline}
          title={
            inPipeline
              ? "Kandydat jest w pipeline tej rekrutacji"
              : "Dodaj kandydata do pipeline tej rekrutacji"
          }
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg shrink-0 whitespace-nowrap transition-colors disabled:cursor-default ${
            inPipeline
              ? "bg-green-100 text-green-700 border border-green-200"
              : "bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60"
          }`}
        >
          {addMutation.isPending ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Dodaję…
            </>
          ) : inPipeline ? (
            <>
              <Check className="h-3.5 w-3.5" />
              W pipeline
            </>
          ) : (
            <>
              <Plus className="h-3.5 w-3.5" />
              Dodaj do pipeline
            </>
          )}
        </button> : null}
      </div>
      {open ? (
        <div className="px-3 pb-3">
          <p className="text-xs text-slate-500 pl-6">
            Projekty, w których kandydat był już rozważany:
          </p>
          <SourcesList sources={candidate.sources} />
        </div>
      ) : null}
    </li>
  );
}

export function HistoricalCandidatesSection({ jobId, readOnly = false }: Props) {
  const [expanded, setExpanded] = useState(true);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [added, setAdded] = useState<Set<number>>(new Set());
  const [deepLinkGlow, setDeepLinkGlow] = useState(false);
  const sectionRef = useRef<HTMLElement>(null);
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();

  const query = useQuery<CandidatesFromSimilarResponse>({
    queryKey: ["historical-candidates", jobId],
    queryFn: async () => {
      const r = await historicalCandidatesApi.forJob(jobId, {
        tier: "primary",
        limit: 20,
        include_negative: true,
      });
      return r.data;
    },
    retry: 1,
    staleTime: 60_000,
  });

  // Deep link z notyfikacji „Podobny request — gotowi kandydaci”
  // (/jobs/{id}?tab=similar): rozwiń, doscrolluj i podświetl sekcję.
  useEffect(() => {
    if (searchParams?.get("tab") !== "similar") return;
    setExpanded(true);
    setDeepLinkGlow(true);
    const scrollTimer = window.setTimeout(() => {
      sectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 200);
    const glowTimer = window.setTimeout(() => setDeepLinkGlow(false), 3000);
    return () => {
      window.clearTimeout(scrollTimer);
      window.clearTimeout(glowTimer);
    };
  }, [searchParams]);

  const bulkMutation = useMutation({
    mutationFn: (ids: number[]) =>
      proposalsBulkApi.add(jobId, {
        candidate_ids: ids,
        note: BULK_REPIN_NOTE,
      }),
    onSuccess: (res) => {
      const okIds = [
        ...res.added,
        ...res.skipped
          .filter((s) => s.reason === "already_in_job")
          .map((s) => s.candidate_id),
      ];
      setAdded((prev) => new Set([...prev, ...okIds]));
      setSelected(new Set());
      queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
      if (res.total_added > 0) {
        showSuccess(
          `Dodano ${res.total_added} kandydatów do pipeline${
            res.total_skipped > 0 ? `, pominięto ${res.total_skipped}` : ""
          }`,
        );
      } else {
        showError(
          "Nie dodano nikogo — kandydaci są już w pipeline lub zablokowani",
        );
      }
    },
    onError: (error: unknown) => showError(assignErrorMessage(error)),
  });

  const candidates = query.data?.candidates ?? [];
  const similarJobs = query.data?.similar_jobs ?? [];
  const tierUsed = query.data?.tier_used ?? "primary";

  // Do sierpnia 2026 stały tu DWA `return null`: jeden na `query.isError`, drugi
  // na pusty wynik. Cała sekcja znikała wtedy z profilu rekrutacji — nie „pusta
  // lista", nie komunikat, po prostu jej nie było. Rekruter zgłaszał „zniknęła
  // mi sekcja", a system nie miał na to żadnej odpowiedzi. Do tego z
  // powiadomienia „Podobny request — gotowi kandydaci" prowadzi deep link
  // `?tab=similar` do kotwicy, której w DOM-ie nie ma.
  //
  // Kolejność kanoniczna (`lib/view-state.ts`): ładowanie → awaria → pusto →
  // dane. Pusty stan wisi na sukcesie (`isPending`, nie `isLoading`) —
  // w przerwie między ponowieniami `isLoading` jest już `false`, a `candidates`
  // dalej puste, więc na `isLoading` twierdzilibyśmy „brak kandydatów", zanim
  // cokolwiek wiadomo.
  const viewState = resolveViewState({
    isLoading: query.isPending,
    isError: query.isError,
    error: query.error,
    isEmpty: candidates.length === 0,
  });
  const failed = isBlockingViewState(viewState);

  // `tier_used === "degraded"` znaczy „wyszukiwanie podobnych ofert nie
  // odpowiedziało" — czyli NIE WIEMY, czy historia jest pusta. Musi renderować
  // się jak awaria, nie jak pusty stan: „Brak kandydatów w historii podobnych
  // projektów" czyta się jako fakt o świecie i rekruter przestaje szukać
  // dokładnie tam, gdzie system po prostu nie odpowiedział. Ta sama zasada, co
  // przy `meta.degraded` w Talent Radarze.
  const degraded = tierUsed === "degraded";

  // Bramka dopuszczalności (backend, `candidates_from_similar_jobs`) wycina
  // z tej sekcji jej NAJBOGATSZĄ populację: ludzi rozważanych już u TEGO
  // klienta, czyli dokładnie tych, u których siedzą aktywne blacklisty, NDA,
  // konflikty konkurencyjne i weta hiring managera. Bez rozgałęzienia poniżej
  // zdanie „Brak kandydatów w historii podobnych projektów" stałoby się
  // nieprawdą właśnie u klientów z najgęstszą historią — czyli tam, gdzie ta
  // sekcja jest najbardziej potrzebna.
  //
  // LICZBY świadomie nie pokazujemy. „Ukryto 3" byłoby wyrocznią na NDA:
  // powiedziałoby rekruterowi, ilu ludzi u tego klienta istnieje, a nie wolno
  // mu ich zobaczyć. Renderujemy sam FAKT blokady, nie jej rozmiar.
  const hiddenIneligible = query.data?.meta?.hidden_ineligible ?? 0;

  // Faza 3: kandydaci znani temu klientowi na górze — to najszybsza ścieżka.
  const sameClient = candidates.filter((c) => c.same_client);
  const others = candidates.filter((c) => !c.same_client);
  const grouped = sameClient.length > 0;

  // Select-all pomija osoby już w pipeline oraz odrzucone przez tego klienta
  // (te wymagają świadomej pojedynczej decyzji, nie hurtu).
  const selectable = candidates.filter(
    (c) => !added.has(c.candidate_id) && !c.rejected_by_same_client,
  );
  const allSelected =
    selectable.length > 0 &&
    selectable.every((c) => selected.has(c.candidate_id));

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(selectable.map((c) => c.candidate_id)));
    }
  };

  const renderRows = (items: HistoricalCandidate[]) => (
    <ul className="space-y-2">
      {items.map((c) => (
        <CandidateRow
          key={c.candidate_id}
          candidate={c}
          jobId={jobId}
          isAdded={added.has(c.candidate_id)}
          isSelected={selected.has(c.candidate_id)}
          onToggleSelect={toggleSelect}
          onAdded={(id) => setAdded((prev) => new Set([...prev, id]))}
          readOnly={readOnly}
        />
      ))}
    </ul>
  );

  return (
    <section
      ref={sectionRef}
      id="historical-candidates"
      className={`bg-slate-50 border border-slate-200 rounded-xl p-4 mb-4 transition-shadow ${
        deepLinkGlow
          ? "ring-2 ring-indigo-500 ring-offset-2 ring-offset-background shadow-lg"
          : ""
      }`}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-controls="historical-candidates-content"
        className="w-full flex items-center gap-2 mb-3"
      >
        <Sparkles className="h-4 w-4 text-indigo-600" />
        <h3 className="text-sm font-semibold text-slate-900">
          Kandydaci z podobnych projektów
        </h3>
        <span className="text-xs text-slate-500">
          {/* Liczniki przy awarii byłyby zerami z inicjalizacji, a nie
              wynikiem szukania — nagłówek mówi wtedy wprost, że nie wiemy. */}
          {viewState === "loading"
            ? "ładowanie…"
            : failed
              ? "nie udało się pobrać"
              : degraded
                ? "nie udało się sprawdzić"
                : `${candidates.length} kandydatów z ${similarJobs.length} podobnych projektów${
                  tierUsed === "extended" ? " (Tier A + B)" : ""
                }`}
        </span>
        <span className="ml-auto text-xs text-indigo-600 hover:underline">
          {expanded ? "Zwiń" : "Rozwiń"}
        </span>
      </button>

      {!expanded ? null : (
        <div id="historical-candidates-content">
          {viewState === "loading" ? (
            <p className="text-sm text-slate-500">
              Szukam kandydatów z pokrewnych rekrutacji…
            </p>
          ) : failed ? (
        <QueryStateNotice
          state={viewState as BlockingViewState}
          className="bg-white"
          description={
            viewState === "forbidden"
              ? "Twoja rola nie ma dostępu do historii podobnych projektów. Historia NIE jest pusta — poproś administratora o uprawnienia."
              : httpStatusFromError(query.error) === undefined
                ? "Nie udało się połączyć z serwerem. Sprawdź internet lub VPN i spróbuj ponownie."
                : undefined
          }
          onRetry={
            viewState === "error" ? () => void query.refetch() : undefined
          }
        />
      ) : degraded ? (
        <div
          role="status"
          className="rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
        >
          Wyszukiwanie podobnych rekrutacji nie odpowiedziało, więc{" "}
          <strong className="font-medium">nie wiadomo</strong>, czy w historii są
          kandydaci. To nie jest informacja o braku historii.{" "}
          <button
            type="button"
            onClick={() => void query.refetch()}
            className="underline underline-offset-2"
          >
            Ponów
          </button>
        </div>
      ) : viewState === "empty" ? (
        <p className="text-sm text-slate-500">
          {hiddenIneligible > 0
            ? "W historii podobnych projektów są kandydaci, ale wszyscy są zablokowani dla tego klienta (blacklista, NDA, konflikt konkurencyjny albo weto hiring managera)."
            : "Brak kandydatów w historii podobnych projektów."}
        </p>
      ) : (
        <>
          <div className="mb-3 text-xs text-slate-500 flex items-center gap-1">
            <UserCheck className="h-3.5 w-3.5" />
            AI podpowiada osoby, które już przeszły dalej w podobnych rekrutacjach — zacznij od nich, zanim zaczniesz szukać świeżej krwi.
          </div>

          {/* Pasek hurtowego przepinania (Faza 2). */}
          {!readOnly ? <div className="mb-3 flex items-center gap-2 flex-wrap">
            <button
              type="button"
              onClick={toggleSelectAll}
              disabled={selectable.length === 0}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-100 disabled:opacity-50"
            >
              {allSelected ? (
                <CheckSquare className="h-3.5 w-3.5" />
              ) : (
                <Square className="h-3.5 w-3.5" />
              )}
              {allSelected ? "Odznacz wszystkich" : "Zaznacz wszystkich"}
            </button>
            <button
              type="button"
              onClick={() => bulkMutation.mutate([...selected])}
              disabled={selected.size === 0 || bulkMutation.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {bulkMutation.isPending ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Dodaję…
                </>
              ) : (
                <>
                  <Plus className="h-3.5 w-3.5" />
                  Dodaj zaznaczonych ({selected.size}) do pipeline
                </>
              )}
            </button>
            {selectable.length < candidates.length ? (
              <span className="text-[11px] text-slate-400">
                Odrzuceni przez tego klienta i osoby już w pipeline nie wchodzą do „zaznacz wszystkich”.
              </span>
            ) : null}
          </div> : null}

          {grouped ? (
            <div className="space-y-4">
              <div>
                <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-emerald-700">
                  <Building2 className="h-3.5 w-3.5" />
                  Znani temu klientowi ({sameClient.length})
                </div>
                {renderRows(sameClient)}
              </div>
              {others.length > 0 ? (
                <div>
                  <div className="mb-2 text-xs font-semibold text-slate-600">
                    Z podobnych projektów u innych klientów ({others.length})
                  </div>
                  {renderRows(others)}
                </div>
              ) : null}
            </div>
          ) : (
            renderRows(candidates)
          )}
        </>
          )}
        </div>
      )}
    </section>
  );
}
