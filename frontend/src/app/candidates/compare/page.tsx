"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { AlertTriangle, ArrowLeft, RefreshCw, User2 } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { AVATAR_COLORS } from "@/lib/colors";
import { apiErrorMessage } from "@/lib/api-error";
import {
  formatCandidateLocation,
  getTagName,
} from "@/components/v2/pages/candidate-list-helpers";
import { formatExperienceDate } from "@/components/v2/pages/candidate-profile-helpers";
import { decodeCompareBackHref } from "@/lib/url-filters";
import { profileCompleteness, skillLevelLabel } from "./compare-helpers";

// ── Helpers ───────────────────────────────────────────────────────────────────

function getAvatarColor(name: string): string {
  const code = (name?.charCodeAt(0) ?? 0) + (name?.charCodeAt(1) ?? 0);
  return AVATAR_COLORS[code % AVATAR_COLORS.length];
}

function formatNoticePeriod(value: number | null | undefined, unit: string | null | undefined): string {
  if (value == null) return "—";
  const effectiveUnit = unit || "days";
  const labels: Record<string, [string, string, string]> = {
    days: ["dzień", "dni", "dni"],
    weeks: ["tydzień", "tygodnie", "tygodni"],
    months: ["miesiąc", "miesiące", "miesięcy"],
  };
  const forms = labels[effectiveUnit] ?? labels.days;
  const n = Math.abs(value);
  const mod10 = n % 10;
  const mod100 = n % 100;
  let label: string;
  if (n === 1) label = forms[0];
  else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) label = forms[1];
  else label = forms[2];
  return `${value} ${label}`;
}

function SkillRow({ name, level }: { name: string; level?: string | number }) {
  const label = skillLevelLabel(level);
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className="truncate text-foreground">{name}</span>
      <span className="shrink-0 text-muted-foreground">{label || "poziom nieznany"}</span>
    </div>
  );
}

function CompletenessBadge({ score }: { score: number }) {
  return (
    <div className="text-3xl font-extrabold text-foreground">
      {score}
      <span className="text-base font-normal text-muted-foreground">%</span>
    </div>
  );
}

// ── Candidate Card ────────────────────────────────────────────────────────────

function CandidateCompareCard({ candidate }: { candidate: any }) {
  const fullName = `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim();
  const initials = fullName.split(" ").map((w: string) => w[0]).slice(0, 2).join("").toUpperCase();
  const avatarColor = getAvatarColor(fullName);
  const score = profileCompleteness(candidate);
  const formattedLocation = formatCandidateLocation(candidate.location);

  const skills: any[] = Array.isArray(candidate.skills) ? candidate.skills : [];
  const experience: any[] = Array.isArray(candidate.experience) ? candidate.experience : [];
  const languages: any[] = Array.isArray(candidate.languages) ? candidate.languages : [];
  // Kolumna `tags` miesza napisy z obiektami importu (`{type:"traffit_source",…}`);
  // obiekt wstawiony wprost do JSX wywracał całe porównanie (React #31).
  const tags: string[] = (Array.isArray(candidate.tags) ? candidate.tags : [])
    .map(getTagName)
    .filter((t: string | null): t is string => Boolean(t));

  return (
    <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border overflow-hidden flex flex-col">
      {/* Header */}
      <div className="p-5 border-b border-border dark:border-border text-center">
        <div className={cn("w-16 h-16 rounded-full flex items-center justify-center text-white font-bold text-xl mx-auto mb-3", avatarColor)}>
          {initials || <User2 className="w-7 h-7" />}
        </div>
        <h2 className="font-bold text-foreground dark:text-foreground text-lg">{fullName || "Brak nazwy"}</h2>
        {candidate.competence_category && (
          <p className="text-sm text-muted-foreground mt-0.5">{candidate.competence_category}</p>
        )}
        {formattedLocation && (
          <p className="text-xs text-muted-foreground mt-1">📍 {formattedLocation}</p>
        )}
        <div className="mt-3">
          <CompletenessBadge score={score} />
          <p className="text-xs text-muted-foreground mt-0.5">
            Kompletność profilu (wypełnione pola, nie dopasowanie do rekrutacji)
          </p>
        </div>
      </div>

      {/* Status & tags */}
      <div className="px-5 py-3 border-b border-border dark:border-border">
        <div className="flex flex-wrap gap-1.5 justify-center">
          {candidate.status && (
            <span className={cn("text-[10px] px-2 py-0.5 rounded-full font-medium", {
              "bg-green-100 text-green-700": candidate.status === "active",
              "bg-yellow-100 text-yellow-700": candidate.status === "passive",
              "bg-destructive/15 text-destructive": candidate.status === "blacklisted",
            })}>
              {candidate.status === "active" ? "Aktywny" : candidate.status === "passive" ? "Pasywny" : "Zablokowany"}
            </span>
          )}
          {tags.slice(0, 5).map((t: string, i: number) => (
            <span key={`${i}-${t}`} className="text-[10px] px-2 py-0.5 bg-muted dark:bg-muted text-muted-foreground dark:text-muted-foreground rounded-full">{t}</span>
          ))}
        </div>
      </div>

      {/* Info rows */}
      <div className="px-5 py-3 space-y-2 border-b border-border dark:border-border text-sm">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Dostępność:</span>
          <span className="font-medium">
            {candidate.availability_date
              ? new Date(candidate.availability_date).toLocaleDateString("pl-PL")
              : "—"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Źródło:</span>
          <span className="font-medium capitalize">{candidate.source || "—"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Wypowiedzenie:</span>
          <span className="font-medium">
            {formatNoticePeriod(candidate.notice_period, candidate.notice_period_unit)}
          </span>
        </div>
      </div>

      {/* Languages */}
      {languages.length > 0 && (
        <div className="px-5 py-3 border-b border-border dark:border-border">
          <h4 className="text-xs font-semibold text-muted-foreground uppercase mb-2">Języki</h4>
          <div className="space-y-1">
            {languages.slice(0, 4).map((l: any, i: number) => (
              <div key={i} className="flex justify-between text-xs">
                <span>{typeof l === "string" ? l : l.lang || l.language || l.name || "—"}</span>
                <span className="text-muted-foreground">{l.level || ""}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Skills */}
      {skills.length > 0 && (
        <div className="px-5 py-3 border-b border-border dark:border-border">
          <h4 className="text-xs font-semibold text-muted-foreground uppercase mb-2">Umiejętności</h4>
          <div className="space-y-1.5">
            {skills.slice(0, 8).map((s: any, i: number) => {
              const name = typeof s === "string" ? s : s.name || "—";
              const level = typeof s === "object" ? s.level : undefined;
              return <SkillRow key={i} name={name} level={level} />;
            })}
          </div>
        </div>
      )}

      {/* Experience */}
      {experience.length > 0 && (
        <div className="px-5 py-3 border-b border-border dark:border-border">
          <h4 className="text-xs font-semibold text-muted-foreground uppercase mb-2">Doświadczenie</h4>
          <div className="space-y-2">
            {experience.slice(0, 4).map((e: any, i: number) => (
              <div key={i} className="text-xs">
                <div className="font-medium text-foreground dark:text-muted-foreground">{e.role || e.position || "—"}</div>
                <div className="text-muted-foreground">{e.company || ""}</div>
                {(e.start || e.end) && (
                  <div className="text-muted-foreground">
                    {formatExperienceDate(e.start) || "?"} –{" "}
                    {formatExperienceDate(e.end) || "obecnie"}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* AI Summary */}
      {candidate.ai_summary && (
        <div className="px-5 py-3 border-b border-border dark:border-border">
          <h4 className="text-xs font-semibold text-muted-foreground uppercase mb-2">AI Podsumowanie</h4>
          <p className="text-xs text-muted-foreground dark:text-muted-foreground line-clamp-4">{candidate.ai_summary}</p>
        </div>
      )}

      {/* Footer link */}
      <div className="px-5 py-3 mt-auto">
        <Link
          href={`/candidates/${candidate.id}`}
          className="block text-center text-xs text-primary hover:underline"
        >
          Otwórz pełny profil →
        </Link>
      </div>
    </div>
  );
}

/** Karta w miejscu profilu, którego nie udało się pobrać — z powodem i „Ponów”.
 *  Wcześniej nieudany profil znikał po cichu (`filter(Boolean)`), a nagłówek
 *  liczył tylko te, które dojechały. */
function CandidateErrorCard({
  candidateId,
  error,
  onRetry,
  retrying,
}: {
  candidateId: number;
  error: unknown;
  onRetry: () => void;
  retrying: boolean;
}) {
  return (
    <div
      role="alert"
      className="bg-card rounded-xl border border-destructive/30 p-5 flex flex-col items-center gap-3 text-center"
    >
      <AlertTriangle className="w-8 h-8 text-destructive" aria-hidden="true" />
      <p className="text-sm font-medium text-foreground">
        Nie udało się pobrać kandydata #{candidateId}
      </p>
      <p className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
        {apiErrorMessage(error, "Nie udało się pobrać profilu kandydata.")}
      </p>
      <button
        type="button"
        onClick={onRetry}
        disabled={retrying}
        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-50"
      >
        <RefreshCw className={cn("w-3.5 h-3.5", retrying && "animate-spin")} aria-hidden="true" />
        Ponów
      </button>
    </div>
  );
}

function CandidateLoadingCard() {
  return (
    <div
      role="status"
      aria-label="Ładowanie profilu kandydata"
      className="bg-card rounded-xl border border-border p-5 flex justify-center py-16"
    >
      <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

function CompareCandidatesInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const ids = searchParams.get("ids")?.split(",").map(Number).filter(Boolean) ?? [];
  // Powrót oddaje liście jej kontekst (filtry, strona) i zaznaczenie użyte
  // do porównania — gołe `/candidates` kasowało jedno i drugie (UAT B21).
  const backHref = decodeCompareBackHref(new URLSearchParams(searchParams.toString()));

  const queries = ids.map((id) =>
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useQuery({
      queryKey: ["candidate", id],
      queryFn: () => api.get(`/api/candidates/${id}`).then((r) => r.data),
      enabled: !!id,
    })
  );

  // Każdy profil renderuje się osobno: 403 na jednym z nich nie chowa reszty
  // i nie zmienia licznika w nagłówku (ten liczy osoby wybrane do porównania).
  const slots = ids.map((id, i) => ({ id, query: queries[i] }));

  if (ids.length < 2) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-muted-foreground gap-4">
        <User2 className="w-16 h-16 opacity-30" />
        <p className="text-lg font-medium">Brak kandydatów do porównania</p>
        <p className="text-sm">Zaznacz 2–3 kandydatów na liście i kliknij "Porównaj"</p>
        <Link href={backHref} className="text-primary hover:underline text-sm mt-2">
          ← Wróć do listy kandydatów
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link href={backHref} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-4 h-4" /> Wróć do kandydatów
        </Link>
        <h1 className="text-2xl font-bold text-foreground dark:text-foreground">
          Porównanie kandydatów
        </h1>
        <span className="text-sm text-muted-foreground">({ids.length} kandydatów)</span>
      </div>

      <div
        className={cn("grid gap-6", {
          "grid-cols-1 md:grid-cols-2": ids.length === 2,
          "grid-cols-1 md:grid-cols-3": ids.length >= 3,
        })}
      >
        {slots.map(({ id, query }) =>
          query.data ? (
            <CandidateCompareCard key={id} candidate={query.data} />
          ) : query.isError ? (
            <CandidateErrorCard
              key={id}
              candidateId={id}
              error={query.error}
              onRetry={() => void query.refetch()}
              retrying={query.isFetching}
            />
          ) : (
            <CandidateLoadingCard key={id} />
          ),
        )}
      </div>
    </div>
  );
}

export default function CompareCandidatesPage() {
  return (
    <Suspense>
      <CompareCandidatesInner />
    </Suspense>
  );
}
