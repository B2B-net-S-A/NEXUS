"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { ArrowLeft, User2 } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

const AVATAR_COLORS = [
  "bg-primary", "bg-violet-600", "bg-emerald-600",
  "bg-rose-500", "bg-amber-500", "bg-cyan-600",
];

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

function calcScore(c: any): number {
  let score = 0;
  const fields = [
    c.name, c.lastname, c.email, c.phone, c.location,
    c.competence_category, c.ai_summary, c.salary_expectation,
  ];
  score += fields.filter(Boolean).length * 5;
  if (Array.isArray(c.skills) && c.skills.length > 0) score += Math.min(c.skills.length * 3, 30);
  if (Array.isArray(c.experience) && c.experience.length > 0) score += Math.min(c.experience.length * 5, 20);
  if (Array.isArray(c.languages) && c.languages.length > 0) score += 5;
  if (c.linkedin) score += 5;
  return Math.min(score, 100);
}

function SkillBar({ name, level }: { name: string; level?: string | number }) {
  let pct = 60;
  if (typeof level === "number") pct = Math.min(level * 10, 100);
  else if (level === "expert" || level === "advanced") pct = 90;
  else if (level === "intermediate") pct = 65;
  else if (level === "beginner" || level === "basic") pct = 35;

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-28 truncate text-muted-foreground dark:text-muted-foreground flex-shrink-0">{name}</span>
      <div className="flex-1 bg-muted dark:bg-muted rounded-full h-1.5">
        <div className="bg-primary h-1.5 rounded-full" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right text-muted-foreground">{pct}%</span>
    </div>
  );
}

function ScoreRing({ score }: { score: number }) {
  const color = score >= 70 ? "text-green-600" : score >= 50 ? "text-yellow-600" : "text-destructive";
  return (
    <div className={cn("text-3xl font-extrabold", color)}>
      {score}<span className="text-base font-normal text-muted-foreground">/100</span>
    </div>
  );
}

// ── Candidate Card ────────────────────────────────────────────────────────────

function CandidateCompareCard({ candidate }: { candidate: any }) {
  const fullName = `${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim();
  const initials = fullName.split(" ").map((w: string) => w[0]).slice(0, 2).join("").toUpperCase();
  const avatarColor = getAvatarColor(fullName);
  const score = calcScore(candidate);

  const skills: any[] = Array.isArray(candidate.skills) ? candidate.skills : [];
  const experience: any[] = Array.isArray(candidate.experience) ? candidate.experience : [];
  const languages: any[] = Array.isArray(candidate.languages) ? candidate.languages : [];
  const tags: string[] = Array.isArray(candidate.tags) ? candidate.tags : [];

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
        {candidate.location && (
          <p className="text-xs text-muted-foreground mt-1">📍 {candidate.location}</p>
        )}
        <div className="mt-3">
          <ScoreRing score={score} />
          <p className="text-xs text-muted-foreground mt-0.5">Profil kompletny</p>
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
          {tags.slice(0, 5).map((t: string) => (
            <span key={t} className="text-[10px] px-2 py-0.5 bg-muted dark:bg-muted text-muted-foreground dark:text-muted-foreground rounded-full">{t}</span>
          ))}
        </div>
      </div>

      {/* Info rows */}
      <div className="px-5 py-3 space-y-2 border-b border-border dark:border-border text-sm">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Wynagrodzenie:</span>
          <span className="font-medium">
            {candidate.salary_expectation
              ? `${candidate.salary_expectation.toLocaleString()} ${candidate.salary_currency || "PLN"}`
              : "—"}
          </span>
        </div>
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
              return <SkillBar key={i} name={name} level={level} />;
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
                  <div className="text-muted-foreground">{e.start || "?"} – {e.end || "nadal"}</div>
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

// ── Main Page ─────────────────────────────────────────────────────────────────

function CompareCandidatesInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const ids = searchParams.get("ids")?.split(",").map(Number).filter(Boolean) ?? [];

  const queries = ids.map((id) =>
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useQuery({
      queryKey: ["candidate", id],
      queryFn: () => api.get(`/api/candidates/${id}`).then((r) => r.data),
      enabled: !!id,
    })
  );

  const loading = queries.some((q) => q.isLoading);
  const candidates = queries.map((q) => q.data).filter(Boolean);

  if (ids.length < 2) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-muted-foreground gap-4">
        <User2 className="w-16 h-16 opacity-30" />
        <p className="text-lg font-medium">Brak kandydatów do porównania</p>
        <p className="text-sm">Zaznacz 2–3 kandydatów na liście i kliknij "Porównaj"</p>
        <Link href="/candidates" className="text-primary hover:underline text-sm mt-2">
          ← Wróć do listy kandydatów
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/candidates" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-4 h-4" /> Wróć do kandydatów
        </Link>
        <h1 className="text-2xl font-bold text-foreground dark:text-foreground">
          Porównanie kandydatów
        </h1>
        <span className="text-sm text-muted-foreground">({candidates.length} kandydatów)</span>
      </div>

      {loading ? (
        <div className="flex justify-center py-16">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div
          className={cn("grid gap-6", {
            "grid-cols-1 md:grid-cols-2": candidates.length === 2,
            "grid-cols-1 md:grid-cols-3": candidates.length === 3,
          })}
        >
          {candidates.map((c: any) => (
            <CandidateCompareCard key={c.id} candidate={c} />
          ))}
        </div>
      )}
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
