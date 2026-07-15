"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Building2,
  ChevronDown,
  ChevronRight,
  Loader2,
  RefreshCw,
  Users,
  X,
} from "lucide-react";
import {
  cortexApi,
  extractErrorMsg,
  type CortexResolvedSkills,
  type CortexSkillCandidate,
  type CortexSkillCandidates,
} from "@/lib/api";
import { EmptyState } from "@/components/ds/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AvailabilityBadge,
  confidencePct,
  FreshnessBadge,
  SeniorityBadge,
  SENIORITY_LABELS,
} from "@/components/cortex/shared";

const PAGE_SIZE = 25;

const SENIORITY_ORDER = ["junior", "mid", "senior", "unknown"] as const;

const SOURCE_OPTIONS = [
  { value: "", label: "Wszystkie źródła" },
  { value: "traffit", label: "Traffit (technologie)" },
  { value: "cv_llm", label: "CV (ekstrakcja AI)" },
  { value: "screening", label: "Screening" },
];

const EMPLOYMENT_OPTIONS = [
  { value: "", label: "Zatrudnienie: wszyscy" },
  { value: "at_client", label: "U naszego klienta" },
  { value: "available", label: "Dostępni (bez projektu)" },
];

const CONFIDENCE_OPTIONS = [
  { value: "", label: "Pewność: dowolna" },
  { value: "0.5", label: "≥ 50%" },
  { value: "0.7", label: "≥ 70%" },
  { value: "0.9", label: "≥ 90%" },
];

export interface SkillCandidatesDrawerProps {
  skillId: number;
  skillName: string;
  /** Preselect a single seniority bucket (used when opening from a heatmap cell). */
  preselectedSeniority?: string;
  onClose: () => void;
}

export function SkillCandidatesDrawer({
  skillId,
  skillName,
  preselectedSeniority,
  onClose,
}: SkillCandidatesDrawerProps) {
  const [seniorities, setSeniorities] = useState<string[]>(
    preselectedSeniority ? [preselectedSeniority] : []
  );
  const [source, setSource] = useState("");
  const [employment, setEmployment] = useState("");
  const [minConfidence, setMinConfidence] = useState("");
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Any filter change invalidates the current page — jump back to the start.
  const resetPage = () => setOffset(0);

  const toggleSeniority = (value: string) => {
    resetPage();
    setSeniorities((prev) =>
      prev.includes(value)
        ? prev.filter((s) => s !== value)
        : [...prev, value]
    );
  };

  const { data, isLoading, isError, error, refetch, isFetching } =
    useQuery<CortexSkillCandidates>({
      queryKey: [
        "cortex-skill-candidates",
        skillId,
        seniorities,
        source,
        employment,
        minConfidence,
        offset,
      ],
      queryFn: async () =>
        (
          await cortexApi.skillCandidates(skillId, {
            seniority: seniorities.length ? seniorities : undefined,
            source: source || undefined,
            employment:
              employment === "at_client" || employment === "available"
                ? employment
                : undefined,
            min_confidence: minConfidence ? Number(minConfidence) : undefined,
            limit: PAGE_SIZE,
            offset,
          })
        ).data,
      placeholderData: (prev) => prev,
    });

  const total = data?.total ?? 0;
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + PAGE_SIZE, total);
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  const activeFilterCount = useMemo(
    () =>
      seniorities.length +
      (source ? 1 : 0) +
      (employment ? 1 : 0) +
      (minConfidence ? 1 : 0),
    [seniorities, source, employment, minConfidence]
  );

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/40"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="skill-candidates-drawer-title"
    >
      <div
        className="flex w-full flex-col sm:max-w-2xl h-full bg-card dark:bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 flex items-center justify-between px-5 py-3.5 border-b border-border bg-card z-10">
          <div className="flex items-center gap-2 min-w-0">
            <Users className="w-5 h-5 text-primary flex-shrink-0" aria-hidden />
            <div className="min-w-0">
              <h2
                id="skill-candidates-drawer-title"
                className="font-semibold text-foreground text-sm truncate"
              >
                Kandydaci z: {skillName}
              </h2>
              <p className="text-xs text-muted-foreground truncate">
                {total.toLocaleString("pl-PL")} osób z faktem dla tej technologii
                {preselectedSeniority
                  ? ` · start: ${SENIORITY_LABELS[preselectedSeniority] ?? preselectedSeniority}`
                  : ""}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted rounded-md flex-shrink-0"
            aria-label="Zamknij"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Filters */}
        <div className="px-5 py-3 border-b border-border space-y-2.5 bg-muted/30">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground mr-1">Seniority:</span>
            {SENIORITY_ORDER.map((s) => {
              const active = seniorities.includes(s);
              return (
                <button
                  key={s}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleSeniority(s)}
                  className={
                    active
                      ? "rounded-full border border-primary bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary"
                      : "rounded-full border border-border px-2.5 py-0.5 text-xs text-muted-foreground hover:bg-accent"
                  }
                >
                  {SENIORITY_LABELS[s]}
                </button>
              );
            })}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <select
              value={source}
              onChange={(e) => {
                resetPage();
                setSource(e.target.value);
              }}
              className="border border-border rounded-md bg-background px-2 py-1.5"
            >
              {SOURCE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <select
              value={employment}
              onChange={(e) => {
                resetPage();
                setEmployment(e.target.value);
              }}
              className="border border-border rounded-md bg-background px-2 py-1.5"
            >
              {EMPLOYMENT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <select
              value={minConfidence}
              onChange={(e) => {
                resetPage();
                setMinConfidence(e.target.value);
              }}
              className="border border-border rounded-md bg-background px-2 py-1.5"
            >
              {CONFIDENCE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            {activeFilterCount > 0 ? (
              <button
                type="button"
                onClick={() => {
                  resetPage();
                  setSeniorities([]);
                  setSource("");
                  setEmployment("");
                  setMinConfidence("");
                }}
                className="text-muted-foreground underline underline-offset-2 hover:text-foreground"
              >
                Wyczyść ({activeFilterCount})
              </button>
            ) : null}
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto p-5">
          {isError ? (
            <div className="space-y-3">
              <p className="flex items-center gap-2 text-sm text-destructive">
                <AlertTriangle className="w-4 h-4" />
                Nie udało się załadować kandydatów.
              </p>
              <p className="text-xs text-muted-foreground">
                {extractErrorMsg(error)}
              </p>
              <Button variant="outline" size="sm" onClick={() => refetch()}>
                <RefreshCw className="w-3.5 h-3.5" />
                Spróbuj ponownie
              </Button>
            </div>
          ) : isLoading || !data ? (
            <p className="text-sm text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
              Ładowanie kandydatów…
            </p>
          ) : data.candidates.length === 0 ? (
            <EmptyState
              icon={Users}
              title="Brak kandydatów"
              description="Żadna osoba nie pasuje do wybranych filtrów — poluzuj seniority, źródło lub próg pewności."
            />
          ) : (
            <ul className="space-y-2.5">
              {data.candidates.map((c) => (
                <CandidateRow key={c.id} candidate={c} />
              ))}
            </ul>
          )}
        </div>

        {/* Footer / pagination */}
        {!isError && total > 0 ? (
          <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-3 bg-card">
            <p className="text-xs text-muted-foreground tabular-nums">
              {rangeStart.toLocaleString("pl-PL")}–
              {rangeEnd.toLocaleString("pl-PL")} z{" "}
              {total.toLocaleString("pl-PL")}
              {isFetching ? " · odświeżanie…" : ""}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={!hasPrev || isFetching}
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
              >
                Poprzednia
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!hasNext || isFetching}
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
              >
                Następna
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function CandidateRow({ candidate }: { candidate: CortexSkillCandidate }) {
  const [expanded, setExpanded] = useState(false);
  const fullName =
    `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim() || "—";
  return (
    <li className="rounded-xl border border-border p-3 space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <a
            href={`/candidates/${candidate.id}`}
            className="font-medium text-sm text-foreground hover:text-primary hover:underline underline-offset-2 truncate"
          >
            {fullName}
          </a>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <SeniorityBadge seniority={candidate.seniority} />
            <AvailabilityBadge status={candidate.availability_status} />
            {candidate.at_client ? (
              <Badge variant="info" size="sm">
                <Building2 className="w-3 h-3" />U klienta
              </Badge>
            ) : null}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1 flex-shrink-0">
          <span
            className="text-sm font-semibold tabular-nums text-foreground"
            title="Pewność najsilniejszego faktu"
          >
            {confidencePct(candidate.confidence)}
          </span>
          <FreshnessBadge freshness={candidate.freshness} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {candidate.years != null ? (
          <span className="tabular-nums">{candidate.years} lat IT</span>
        ) : null}
        {candidate.level ? <span>poziom: {candidate.level}</span> : null}
        {candidate.sources.length ? (
          <span className="inline-flex items-center gap-1">
            źródła:
            {candidate.sources.map((s) => (
              <Badge key={s} variant="outline" size="sm">
                {s}
              </Badge>
            ))}
          </span>
        ) : null}
      </div>

      {candidate.evidence ? (
        <p
          className="text-xs text-muted-foreground line-clamp-2"
          title={candidate.evidence}
        >
          {candidate.evidence}
        </p>
      ) : null}

      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5" />
        )}
        Rozwiązane kompetencje
      </button>

      {expanded ? <ResolvedSkillsInline candidateId={candidate.id} /> : null}
    </li>
  );
}

/** Lazily-loaded resolved skills (one row per skill, precedence × freshness). */
function ResolvedSkillsInline({ candidateId }: { candidateId: number }) {
  const { data, isLoading, isError, error, refetch } =
    useQuery<CortexResolvedSkills>({
      queryKey: ["cortex-resolved-skills", candidateId],
      queryFn: async () =>
        (await cortexApi.resolvedSkills(candidateId)).data,
    });

  if (isError) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs text-destructive">
        <AlertTriangle className="w-3.5 h-3.5" />
        {extractErrorMsg(error)}
        <button
          type="button"
          onClick={() => refetch()}
          className="underline underline-offset-2 hover:text-foreground"
        >
          Spróbuj ponownie
        </button>
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <p className="text-xs text-muted-foreground">
        <Loader2 className="w-3.5 h-3.5 animate-spin inline mr-1.5" />
        Ładowanie kompetencji…
      </p>
    );
  }

  if (data.skills.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        Brak rozwiązanych kompetencji dla tego kandydata.
      </p>
    );
  }

  return (
    <ul className="flex flex-wrap gap-1.5">
      {data.skills.map((s) => (
        <li
          key={s.skill_id}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-0.5 text-xs"
          title={`źródło: ${s.source}${s.observed_at ? ` · ${new Date(s.observed_at).toLocaleDateString("pl-PL")}` : ""}`}
        >
          <span className="font-medium text-foreground">{s.skill}</span>
          <span className="text-muted-foreground tabular-nums">
            {confidencePct(s.effective_confidence)}
          </span>
          <Badge variant="outline" size="sm">
            {s.source}
          </Badge>
          {s.level ? (
            <span className="text-muted-foreground">{s.level}</span>
          ) : null}
          {s.years != null ? (
            <span className="text-muted-foreground tabular-nums">
              {s.years} lat
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
