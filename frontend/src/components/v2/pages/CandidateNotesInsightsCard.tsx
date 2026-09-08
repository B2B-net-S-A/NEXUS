"use client";

/**
 * CandidateNotesInsightsCard — strukturalne fakty wyciągnięte AI z notatek
 * rekruterskich (`cv_extracted_data._notes_insights`, import 08.2026, ~14k
 * kandydatów). Karta renderuje wyłącznie niepuste grupy i znika całkiem, gdy
 * kandydat nie ma ekstrakcji — to opcjonalne wzbogacenie profilu, nie osobne
 * pobranie (dane przychodzą z już załadowanego kandydata, więc nie ma tu
 * własnej gałęzi błędu).
 *
 * Świadomie POMIJA `client_vetoes` i `matching_facts`: wzmianki o wetach
 * czekają na ręczny przegląd (weryfikacja człowieka przed jakąkolwiek
 * ekspozycją), a matching_facts to surowy wsad dla scoringu, nie treść dla
 * rekrutera. Stawki (`expected_rate`, `rate_flexibility`) są tu tą samą klasą
 * danych co treść notatek, z których pochodzą — czyta je ta sama publiczność
 * (role operacyjne z dostępem do profilu i zakładki Notatki).
 */

import React, { useState } from "react";
import { NotebookPen } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface EvidencedSkill {
  name?: string | null;
  evidence?: string | null;
  level?: string | null;
  years?: number | null;
}

interface NotesInsights {
  _rate_requires_verification?: boolean;
  skills_evidenced?: EvidencedSkill[] | null;
  skills_gaps_observed?: EvidencedSkill[] | null;
  expected_rate?: {
    raw?: string | null;
    value?: number | null;
    currency?: string | null;
    period?: string | null;
    as_of?: string | null;
  } | null;
  rate_flexibility?: string | null;
  availability?: {
    available_from?: string | null;
    notice_period?: string | null;
    raw?: string | null;
  } | null;
  not_looking_until?: string | null;
  current_engagement?: {
    project?: string | null;
    employer?: string | null;
    ends_at?: string | null;
    raw?: string | null;
  } | null;
  contract_form_preference?: string | null;
  relocation?: { willing?: boolean | null; targets?: string[] | null } | null;
  preferences?: {
    remote_only?: boolean | null;
    locations?: string[] | null;
    sectors_prefer?: string[] | null;
    sectors_avoid?: string[] | null;
    other?: string | null;
  } | null;
  languages_observed?: Array<{
    name?: string | null;
    level?: string | null;
  }> | null;
  years_confirmed?: number | null;
  certifications?: string[] | null;
  work_permit_status?: string | null;
  security_clearance?: string | null;
  _extracted_at?: string | null;
  _v2_extracted_at?: string | null;
}

const SKILL_PREVIEW_COUNT = 12;

function cleanList<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value.filter(Boolean) : [];
}

function cleanStrings(value: string[] | null | undefined): string[] {
  return cleanList(value).filter(
    (v): v is string => typeof v === "string" && v.trim() !== "",
  );
}

function hasText(value: string | null | undefined): value is string {
  return typeof value === "string" && value.trim() !== "";
}

function formatRate(rate: NonNullable<NotesInsights["expected_rate"]>): string | null {
  if (hasText(rate.raw)) return rate.raw;
  if (typeof rate.value === "number") {
    const currency = hasText(rate.currency) ? rate.currency : "(waluta niepodana)";
    const period = hasText(rate.period) ? `/${rate.period}` : "";
    return `${rate.value} ${currency}${period}`;
  }
  return null;
}

function formatAvailability(
  a: NonNullable<NotesInsights["availability"]>,
): string | null {
  if (hasText(a.available_from)) return `od ${a.available_from}`;
  if (hasText(a.notice_period)) return `wypowiedzenie ${a.notice_period}`;
  if (hasText(a.raw)) return a.raw;
  return null;
}

function formatEngagement(
  e: NonNullable<NotesInsights["current_engagement"]>,
): string | null {
  const parts: string[] = [];
  if (hasText(e.project)) parts.push(e.project);
  if (hasText(e.employer)) parts.push(`u ${e.employer}`);
  if (parts.length === 0 && hasText(e.raw)) parts.push(e.raw);
  if (parts.length === 0) return null;
  if (hasText(e.ends_at)) parts.push(`(do ${e.ends_at})`);
  return parts.join(" ");
}

function SkillChips({
  skills,
  variant,
}: {
  skills: EvidencedSkill[];
  variant: "success" | "warning";
}) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? skills : skills.slice(0, SKILL_PREVIEW_COUNT);
  const hiddenCount = skills.length - visible.length;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {visible.map((skill, i) => {
        const label = hasText(skill.name) ? skill.name : null;
        if (!label) return null;
        const chip = (
          <Badge size="sm" variant={variant} className="cursor-default">
            {label}
          </Badge>
        );
        return hasText(skill.evidence) ? (
          <Tooltip key={`${label}-${i}`}>
            <TooltipTrigger asChild>
              <span tabIndex={0}>{chip}</span>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs text-xs">
              {skill.evidence}
            </TooltipContent>
          </Tooltip>
        ) : (
          <span key={`${label}-${i}`}>{chip}</span>
        );
      })}
      {hiddenCount > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="text-xs font-medium text-primary hover:underline"
        >
          +{hiddenCount} więcej
        </button>
      )}
    </div>
  );
}

function InsightRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex gap-2 text-xs">
      <span className="w-36 shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 flex-1 text-foreground">{children}</span>
    </div>
  );
}

export function CandidateNotesInsightsCard({
  insights,
}: {
  insights: NotesInsights | null | undefined;
}) {
  if (!insights || typeof insights !== "object") return null;

  const skills = cleanList(insights.skills_evidenced).filter((s) =>
    hasText(s?.name),
  );
  const gaps = cleanList(insights.skills_gaps_observed).filter((s) =>
    hasText(s?.name),
  );
  const rate = insights.expected_rate ? formatRate(insights.expected_rate) : null;
  const availability = insights.availability
    ? formatAvailability(insights.availability)
    : null;
  const engagement = insights.current_engagement
    ? formatEngagement(insights.current_engagement)
    : null;
  const languages = cleanList(insights.languages_observed).filter((l) =>
    hasText(l?.name),
  );
  const certifications = cleanStrings(insights.certifications);
  const relocationTargets = cleanStrings(insights.relocation?.targets);
  const relocation =
    insights.relocation?.willing === true
      ? relocationTargets.length > 0
        ? `tak — ${relocationTargets.join(", ")}`
        : "tak"
      : insights.relocation?.willing === false
        ? "nie"
        : null;
  const prefs = insights.preferences ?? null;
  const prefLocations = cleanStrings(prefs?.locations);
  const sectorsPrefer = cleanStrings(prefs?.sectors_prefer);
  const sectorsAvoid = cleanStrings(prefs?.sectors_avoid);

  const rows: Array<{ label: string; value: React.ReactNode }> = [];
  if (rate) {
    rows.push({
      label: "Oczekiwana stawka",
      value: (
        <>
          {rate}
          {insights._rate_requires_verification && <span className="text-muted-foreground"> — do weryfikacji, bez zmiany stawki profilu</span>}
          {hasText(insights.expected_rate?.as_of) && (
            <span className="text-muted-foreground">
              {" "}
              (stan: {insights.expected_rate?.as_of})
            </span>
          )}
        </>
      ),
    });
  }
  if (hasText(insights.rate_flexibility)) {
    rows.push({ label: "Elastyczność stawki", value: insights.rate_flexibility });
  }
  if (availability) rows.push({ label: "Dostępność", value: availability });
  if (hasText(insights.not_looking_until)) {
    rows.push({ label: "Nie szuka do", value: insights.not_looking_until });
  }
  if (engagement) rows.push({ label: "Obecne zaangażowanie", value: engagement });
  if (hasText(insights.contract_form_preference)) {
    rows.push({
      label: "Forma współpracy",
      value: insights.contract_form_preference,
    });
  }
  if (typeof insights.years_confirmed === "number") {
    rows.push({
      label: "Lata dośw. (potwierdzone)",
      value: `${insights.years_confirmed}`,
    });
  }
  if (relocation) rows.push({ label: "Relokacja", value: relocation });
  if (prefs?.remote_only === true) {
    rows.push({ label: "Tryb pracy", value: "tylko zdalnie" });
  }
  if (prefLocations.length > 0) {
    rows.push({ label: "Preferowane lokalizacje", value: prefLocations.join(", ") });
  }
  if (sectorsPrefer.length > 0) {
    rows.push({ label: "Sektory preferowane", value: sectorsPrefer.join(", ") });
  }
  if (sectorsAvoid.length > 0) {
    rows.push({ label: "Sektory unikane", value: sectorsAvoid.join(", ") });
  }
  if (hasText(prefs?.other)) {
    rows.push({ label: "Inne preferencje", value: prefs?.other });
  }
  if (languages.length > 0) {
    rows.push({
      label: "Języki (z rozmów)",
      value: languages
        .map((l) => (hasText(l.level) ? `${l.name} (${l.level})` : l.name))
        .join(", "),
    });
  }
  if (certifications.length > 0) {
    rows.push({ label: "Certyfikaty", value: certifications.join(", ") });
  }
  if (hasText(insights.work_permit_status)) {
    rows.push({ label: "Pozwolenie na pracę", value: insights.work_permit_status });
  }
  if (hasText(insights.security_clearance)) {
    rows.push({
      label: "Poświadczenie bezp.",
      value: insights.security_clearance,
    });
  }

  if (skills.length === 0 && gaps.length === 0 && rows.length === 0) return null;

  const extractedAt =
    insights._v2_extracted_at ?? insights._extracted_at ?? null;
  const extractedDate = hasText(extractedAt) ? extractedAt.slice(0, 10) : null;

  return (
    <TooltipProvider delayDuration={150}>
      <section>
        <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          <NotebookPen className="h-3.5 w-3.5" />
          Z notatek rekruterskich
          <Badge size="sm" variant="info">
            AI
          </Badge>
          {extractedDate && (
            <span className="ml-auto text-[11px] font-normal normal-case tracking-normal">
              ekstrakcja {extractedDate}
            </span>
          )}
        </h3>
        <div className="space-y-3 rounded-lg border border-border bg-background/40 p-3">
          {skills.length > 0 && (
            <div>
              <div className="mb-1.5 text-[11px] font-medium text-muted-foreground">
                Potwierdzone umiejętności ({skills.length}) — najedź, by
                zobaczyć dowód z notatki
              </div>
              <SkillChips skills={skills} variant="success" />
            </div>
          )}
          {gaps.length > 0 && (
            <div>
              <div className="mb-1.5 text-[11px] font-medium text-muted-foreground">
                Zaobserwowane braki ({gaps.length})
              </div>
              <SkillChips skills={gaps} variant="warning" />
            </div>
          )}
          {rows.length > 0 && (
            <div className="space-y-1.5">
              {rows.map((row) => (
                <InsightRow key={row.label} label={row.label}>
                  {row.value}
                </InsightRow>
              ))}
            </div>
          )}
        </div>
      </section>
    </TooltipProvider>
  );
}

export default CandidateNotesInsightsCard;
