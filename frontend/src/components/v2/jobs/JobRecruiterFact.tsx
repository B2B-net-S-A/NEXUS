"use client";

import { useState } from "react";
import { ArrowRight, ChevronDown } from "lucide-react";

import { shortenPersonName } from "@/lib/job-header-subtitle";
import {
  pinRecruiters,
  proposedRecruiters,
  recruitersOf,
  recruitersSummary,
  workingRecruiters,
  type JobRecruiter,
} from "@/lib/job-team";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { JobOwnershipPanel, type JobOwnershipJob } from "./JobOwnershipPanel";
import { RecruiterAvatar } from "./RecruiterChips";

export interface JobRecruiterFactJob extends JobOwnershipJob {
  /** Delivery Lead rekrutacji (`GET /api/jobs/{id}`). */
  delivery_lead_user?: { name?: string | null } | null;
}

export interface JobRecruiterFactProps {
  jobId: number;
  jobTitle: string;
  job: JobRecruiterFactJob;
  /** `useJobTeamPermissions(job).editScope !== "none"` — jak w panelu „Zespół”. */
  canEdit: boolean;
  /** „Kategoria i termin” — zakładka „Zespół” Profilu Championa. */
  onOpenTeam?: () => void;
  /** Zwinięty nagłówek: same awatary, bez napisu. */
  compact?: boolean;
}

/** Co pokazuje fakt: osoby, które pracują, sama propozycja automatu albo nikt. */
interface FactView {
  kind: "working" | "proposal" | "none";
  /** „Marta N.”, „Ty”, „propozycja: Jan P.”, „Bez rekrutera”. */
  text: string;
  more: number;
  avatars: readonly JobRecruiter[];
}

export function recruiterFactView(
  people: readonly JobRecruiter[],
  viewerId: number | null,
): FactView {
  const working = workingRecruiters(people);
  if (working.length > 0) {
    // Zalogowana osoba pierwsza — jak kolumna „Rekruter” na liście.
    const pinned = workingRecruiters(pinRecruiters(people, [viewerId]));
    const lead = pinned[0];
    return {
      kind: "working",
      text:
        lead.user_id === viewerId ? "Ty" : (shortenPersonName(lead.name) ?? lead.name),
      more: pinned.length - 1,
      avatars: pinned.slice(0, 2),
    };
  }
  const proposed = proposedRecruiters(people);
  if (proposed.length > 0) {
    const first = proposed[0];
    return {
      kind: "proposal",
      text: `propozycja: ${shortenPersonName(first.name) ?? first.name}`,
      more: 0,
      avatars: [first],
    };
  }
  return { kind: "none", text: "Bez rekrutera", more: 0, avatars: [] };
}

/** Cel zdarzenia leży w oknie albo w zagnieżdżonym okienku (portal Radixa). */
function insideLayer(target: EventTarget | null): boolean {
  return (
    target instanceof Element &&
    target.closest('[role="dialog"],[role="alertdialog"]') != null
  );
}

/**
 * Czwarty fakt nagłówka rekrutacji — „Rekruter” (14.10.2026, makiety A3/A4/K1).
 * Osoby z tej samej reguły co lista i pulpit (`recruitersOf`); brak rekrutera
 * to bursztynowe ostrzeżenie, sama propozycja automatu — przerywana ramka.
 *
 * Klik otwiera okienko z panelem zespołu (`JobOwnershipPanel`: Zmień, Zdejmij,
 * Dodaj osobę, Biorę, Dołącz, propozycje) i Delivery Leadem — bez wychodzenia
 * z Tablicy. Kategoria i termin zostają w zakładce „Zespół” Profilu Championa.
 */
export function JobRecruiterFact({
  jobId,
  jobTitle,
  job,
  canEdit,
  onOpenTeam,
  compact = false,
}: JobRecruiterFactProps) {
  const viewerId = useAuthStore((s) => s.user?.id ?? null);
  const [open, setOpen] = useState(false);
  // Panel otworzył własne okno (potwierdzenie, „Zmień rekrutera”) — okienko
  // znika na ten czas, żeby go nie zasłaniać (jak edytor w kolumnie listy).
  const [layerOpen, setLayerOpen] = useState(false);
  const people = recruitersOf(job);
  const view = recruiterFactView(people, viewerId);
  const staffed = recruitersSummary(people).tooltip || "Bez rekrutera";
  const deliveryLead = job.delivery_lead_user?.name?.trim() || null;
  const keepOpen = (event: { target: EventTarget | null; preventDefault: () => void }) => {
    if (insideLayer(event.target)) event.preventDefault();
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Rekruter: ${staffed} — zespół rekrutacji`}
          title={staffed}
          data-testid="job-header-recruiter"
          data-state-kind={view.kind}
          className={cn(
            "inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border text-[13px] font-semibold transition-colors",
            "hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-9",
            compact ? "px-1.5" : "px-2.5",
            view.kind === "none"
              ? "border-warning/40 bg-warning-muted text-warning-muted-foreground"
              : view.kind === "proposal"
                ? "border-dashed border-primary/60 bg-card text-foreground"
                : "border-primary/20 bg-primary/5 text-foreground",
          )}
        >
          {compact ? null : (
            <span
              className={cn(
                "text-xs font-medium",
                view.kind === "none" ? "text-warning-muted-foreground" : "text-muted-foreground",
              )}
            >
              Rekruter
            </span>
          )}
          {view.avatars.length > 0 ? (
            // Awatary obok siebie, nie na zakładkę: tło awatara jest
            // półprzezroczyste i inicjały zlewały się (zrzut 1280 px). W linii
            // faktów jeden awatar osoby z napisem, w zwiniętym — do dwóch.
            <span className="inline-flex gap-0.5" aria-hidden="true">
              {(compact ? view.avatars : view.avatars.slice(0, 1)).map((person) => (
                <RecruiterAvatar key={person.user_id} name={person.name} className="h-5 w-5" />
              ))}
            </span>
          ) : null}
          {compact && view.kind === "working" ? null : (
            <span aria-hidden="true">{view.text}</span>
          )}
          {view.more > 0 && !compact ? (
            <span aria-hidden="true" className="font-medium text-muted-foreground">
              +{view.more}
            </span>
          ) : null}
          <ChevronDown className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        collisionPadding={8}
        data-testid="job-recruiter-popover"
        className={cn(
          "w-[min(380px,calc(100vw-2rem))] space-y-3",
          layerOpen && "invisible",
        )}
        onInteractOutside={keepOpen}
        onFocusOutside={keepOpen}
      >
        <p className="text-[11px] font-semibold uppercase tracking-eyebrow text-muted-foreground">
          Zespół rekrutacji
        </p>
        <JobOwnershipPanel
          jobId={jobId}
          jobTitle={jobTitle}
          job={job}
          canEdit={canEdit}
          onLayerOpenChange={setLayerOpen}
        />
        <div className="flex items-baseline gap-2 border-t border-border pt-2 text-sm">
          <span className="shrink-0 text-[11px] font-semibold uppercase tracking-eyebrow text-muted-foreground">
            Delivery Lead
          </span>
          <span
            className={cn("min-w-0 truncate", deliveryLead ? "font-medium" : "text-muted-foreground")}
            data-testid="job-recruiter-popover-dl"
          >
            {deliveryLead ?? "nie przypisano"}
          </span>
        </div>
        {onOpenTeam ? (
          <button
            type="button"
            className="hit-area inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            onClick={() => {
              setOpen(false);
              onOpenTeam();
            }}
          >
            Kategoria i termin — Profil Championa › Zespół
            <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
