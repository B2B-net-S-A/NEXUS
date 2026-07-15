import * as React from "react";
import {
  Briefcase,
  FileText,
  Mail,
  MapPin,
  Maximize2,
  MoreHorizontal,
  Phone,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { avatarTone } from "@/components/v2/pages/candidate-list-helpers";
import { StagePill } from "@/components/v2/candidates/StagePill";

/** A label/value pair rendered in the details grids. */
export interface CandidateDetailPair {
  label: string;
  value: string;
}

/** Presentational view-model shared by the expandable row (1a) and the docked
 *  side panel (1b). Both the auth-free preview fixtures and the production list
 *  rows map into this shape, so the two surfaces render identically. */
export interface CandidateDetailData {
  id: string | number;
  name: string;
  initials: string;
  role: string | null;
  location: string | null;
  phone?: string | null;
  email?: string | null;
  /** Canonical pipeline stage key. */
  stage: string;
  stageDate?: string | null;
  rateLabel?: string | null;
  owner?: string | null;
  recruitments?: number;
  headline?: string | null;
  skills: string[];
  lastNote?: string | null;
  rejectionReason?: string | null;
  detailPairs: CandidateDetailPair[];
}

/** Small caps section label reused across the panel. */
function SectionLabel({
  children,
  tone = "muted",
}: {
  children: React.ReactNode;
  tone?: "muted" | "danger";
}) {
  return (
    <p
      className={cn(
        "text-[11px] font-semibold uppercase tracking-[0.08em]",
        tone === "danger"
          ? "text-destructive-muted-foreground"
          : "text-muted-foreground",
      )}
    >
      {children}
    </p>
  );
}

/** A single skill token — bordered card chip, shared by row + panel. */
export function SkillChip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-lg border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground/80">
      {children}
    </span>
  );
}

/** Polish plural for "rekrutacja" (1 / 2–4 / 5+). */
function recruitmentsLabel(n: number): string {
  const abs = Math.abs(n);
  const one = abs % 10;
  const two = abs % 100;
  if (abs === 1) return "aktywna rekrutacja";
  if (one >= 2 && one <= 4 && (two < 10 || two >= 20)) return "aktywne rekrutacje";
  return "aktywnych rekrutacji";
}

export interface CandidateDetailPanelProps {
  candidate: CandidateDetailData;
  onClose?: () => void;
  onOpenProfile?: () => void;
  onCall?: () => void;
  onEmail?: () => void;
  onOpenCv?: () => void;
  className?: string;
}

/** The docked profile panel (design option 1b). Pure presentation — no data
 *  fetching — so it renders in the preview harness and in production alike. */
export function CandidateDetailPanel({
  candidate: c,
  onClose,
  onOpenProfile,
  onCall,
  onEmail,
  onOpenCv,
  className,
}: CandidateDetailPanelProps) {
  return (
    <aside
      className={cn(
        "flex h-full min-h-0 flex-col bg-muted/30",
        className,
      )}
      aria-label={`Profil: ${c.name}`}
    >
      {/* Sticky header row with close / expand controls */}
      <div className="flex items-center justify-between border-b border-border bg-background/60 px-4 py-2.5 backdrop-blur">
        <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
          Podgląd kandydata
        </span>
        <div className="flex items-center gap-1">
          {onOpenProfile ? (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Pełny profil"
              onClick={onOpenProfile}
            >
              <Maximize2 aria-hidden className="size-4" />
            </Button>
          ) : null}
          {onClose ? (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Zamknij panel"
              onClick={onClose}
            >
              <X aria-hidden className="size-4" />
            </Button>
          ) : null}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-6">
        {/* Identity */}
        <div className="flex items-start gap-4">
          <div
            className={cn(
              "flex size-14 shrink-0 items-center justify-center rounded-2xl text-lg font-bold",
              avatarTone(String(c.id)),
            )}
          >
            {c.initials}
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-xl font-bold tracking-tight text-foreground">
              {c.name}
            </h2>
            {c.role ? (
              <p className="mt-0.5 truncate text-sm text-muted-foreground">
                {c.role}
              </p>
            ) : null}
            {c.location ? (
              <p className="mt-1.5 flex items-center gap-1 text-xs text-muted-foreground">
                <MapPin aria-hidden className="size-3.5" />
                {c.location}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col items-end gap-2">
            {c.stage ? <StagePill stage={c.stage} /> : null}
            {c.rateLabel ? (
              <div className="text-base font-bold tabular-nums text-success">
                {c.rateLabel}
              </div>
            ) : null}
          </div>
        </div>

        {/* Quick actions */}
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={onCall}>
            <Phone aria-hidden className="size-4 text-success" />
            {c.phone ?? "Zadzwoń"}
          </Button>
          <Button variant="outline" size="sm" onClick={onEmail}>
            <Mail aria-hidden className="size-4 text-success" />
            E-mail
          </Button>
          <Button variant="outline" size="sm" onClick={onOpenCv}>
            <FileText aria-hidden className="size-4 text-success" />
            Otwórz CV
          </Button>
          <Button variant="outline" size="icon-sm" aria-label="Więcej akcji">
            <MoreHorizontal aria-hidden className="size-4" />
          </Button>
        </div>

        {/* Headline */}
        {c.headline ? (
          <div className="rounded-xl border border-border bg-card p-4 text-sm leading-relaxed text-foreground/80">
            {c.headline}
          </div>
        ) : null}

        {/* Skills */}
        {c.skills.length > 0 ? (
          <section className="space-y-3">
            <SectionLabel>Umiejętności</SectionLabel>
            <div className="flex flex-wrap gap-1.5">
              {c.skills.map((s) => (
                <SkillChip key={s}>{s}</SkillChip>
              ))}
            </div>
          </section>
        ) : null}

        {/* Details grid */}
        {c.detailPairs.length > 0 ? (
          <section className="space-y-3">
            <SectionLabel>Szczegóły</SectionLabel>
            <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              {c.detailPairs.map((p) => (
                <div key={p.label}>
                  <dt className="text-[10px] font-semibold uppercase tracking-[0.05em] text-muted-foreground/70">
                    {p.label}
                  </dt>
                  <dd className="mt-1 text-sm text-foreground">{p.value}</dd>
                </div>
              ))}
            </dl>
          </section>
        ) : null}

        {/* Recruitment process */}
        {typeof c.recruitments === "number" ? (
          <section className="space-y-3">
            <SectionLabel>Proces rekrutacyjny</SectionLabel>
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card p-4">
              <div className="flex items-center gap-3">
                <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-success-muted text-success">
                  <Briefcase aria-hidden className="size-4" />
                </div>
                <div>
                  <div className="text-sm font-semibold text-foreground">
                    {c.recruitments} {recruitmentsLabel(c.recruitments)}
                  </div>
                  {c.owner ? (
                    <div className="text-xs text-muted-foreground">
                      Opiekun: {c.owner}
                    </div>
                  ) : null}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {c.stage ? <StagePill stage={c.stage} /> : null}
                {c.stageDate ? (
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {c.stageDate}
                  </span>
                ) : null}
              </div>
            </div>
          </section>
        ) : null}

        {/* Last note */}
        {c.lastNote ? (
          <section className="space-y-3">
            <SectionLabel>Ostatnia notatka</SectionLabel>
            <div className="rounded-xl border border-border bg-card p-4 text-sm leading-relaxed text-foreground/80">
              {c.lastNote}
            </div>
          </section>
        ) : null}

        {/* Rejection reason */}
        {c.rejectionReason ? (
          <section className="space-y-3">
            <SectionLabel tone="danger">Powód odrzucenia</SectionLabel>
            <div className="rounded-xl border border-destructive/20 bg-destructive-muted p-4 text-sm leading-relaxed text-destructive-muted-foreground">
              {c.rejectionReason}
            </div>
          </section>
        ) : null}
      </div>
    </aside>
  );
}
