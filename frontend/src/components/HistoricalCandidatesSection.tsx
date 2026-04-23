"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  History,
  AlertTriangle,
  Clock,
  Sparkles,
  UserCheck,
} from "lucide-react";
import {
  historicalCandidatesApi,
  type CandidatesFromSimilarResponse,
  type HistoricalCandidate,
  type HistoricalSource,
} from "@/lib/api";

interface Props {
  jobId: number;
}

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
    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
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

function CandidateRow({ candidate }: { candidate: HistoricalCandidate }) {
  const [open, setOpen] = useState(false);
  const Icon = open ? ChevronDown : ChevronRight;
  const initials = `${candidate.name.charAt(0)}${candidate.lastname.charAt(0)}`.toUpperCase();

  return (
    <li className="border border-slate-200 rounded-lg bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-3 p-3 text-left hover:bg-slate-50 rounded-lg"
      >
        <Icon className="h-4 w-4 text-slate-400 flex-shrink-0" />
        <div className="h-8 w-8 rounded-full bg-indigo-100 text-indigo-700 text-xs font-semibold flex items-center justify-center flex-shrink-0">
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
            {candidate.recommended_count > 1 ? (
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-violet-100 text-violet-700">
                {candidate.recommended_count}× rekomendowany
              </span>
            ) : null}
            {candidate.negative_signal ? (
              <span
                className="inline-flex items-center gap-0.5 text-[10px] font-medium px-1.5 py-0.5 rounded bg-red-100 text-red-700"
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
        <div className="text-right flex-shrink-0">
          <div className="text-xs text-slate-500">Historical score</div>
          <div className="text-sm font-semibold text-slate-900">
            {candidate.historical_score.toFixed(2)}
          </div>
        </div>
      </button>
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

export function HistoricalCandidatesSection({ jobId }: Props) {
  const [expanded, setExpanded] = useState(true);

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

  // Quietly hide the section when nothing useful is available — we never want
  // to scream "no data" when the real answer is "we haven't run this before".
  const hasCandidates = (query.data?.candidates.length ?? 0) > 0;
  if (query.isError) return null;
  if (query.isFetched && !hasCandidates) return null;

  const candidates = query.data?.candidates ?? [];
  const similarJobs = query.data?.similar_jobs ?? [];
  const tierUsed = query.data?.tier_used ?? "primary";

  return (
    <section className="bg-slate-50 border border-slate-200 rounded-xl p-4 mb-4">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 mb-3"
      >
        <Sparkles className="h-4 w-4 text-indigo-600" />
        <h3 className="text-sm font-semibold text-slate-900">
          Kandydaci z podobnych projektów
        </h3>
        <span className="text-xs text-slate-500">
          {query.isLoading
            ? "ładowanie…"
            : `${candidates.length} kandydatów z ${similarJobs.length} podobnych projektów${
                tierUsed === "extended" ? " (Tier A + B)" : ""
              }`}
        </span>
        <span className="ml-auto text-xs text-indigo-600 hover:underline">
          {expanded ? "Zwiń" : "Rozwiń"}
        </span>
      </button>

      {!expanded ? null : query.isLoading ? (
        <p className="text-sm text-slate-500">Szukam kandydatów z pokrewnych rekrutacji…</p>
      ) : candidates.length === 0 ? (
        <p className="text-sm text-slate-500">
          Brak kandydatów w historii podobnych projektów.
        </p>
      ) : (
        <>
          <div className="mb-3 text-xs text-slate-500 flex items-center gap-1">
            <UserCheck className="h-3.5 w-3.5" />
            AI podpowiada osoby, które już przeszły dalej w podobnych rekrutacjach — zacznij od nich, zanim zaczniesz szukać świeżej krwi.
          </div>
          <ul className="space-y-2">
            {candidates.map((c) => (
              <CandidateRow key={c.candidate_id} candidate={c} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
