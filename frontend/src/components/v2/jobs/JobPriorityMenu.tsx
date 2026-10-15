"use client";

import { ChevronDown, Pause } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  isPriorityLevel,
  PRIORITY_LEVEL_HINT,
  PRIORITY_LEVEL_LABEL,
  PRIORITY_LEVEL_SHORT_LABEL,
  PRIORITY_LEVELS,
  PRIORITY_PAUSED_HINT,
  type PriorityLevel,
} from "@/lib/request-priority";
import { cn } from "@/lib/utils";
import { useJobPriorityChange, type JobPriorityTeam } from "./useJobPriorityChange";

/** Wygląd plakietki per poziom: P1 w tonie alarmu, „Przyjmujemy” przygaszone. */
const TONE: Record<PriorityLevel, string> = {
  p1: "border-destructive/20 bg-destructive-muted text-destructive-muted-foreground",
  p2: "border-border bg-card text-foreground",
  accepting: "border-border bg-card text-muted-foreground",
};

/** P1 wstrzymany przez championa (D6): szara plakietka z przerywaną ramką. */
const PAUSED_TONE = "border-dashed border-border bg-card text-muted-foreground";

const CHIP_CLASS =
  "inline-flex h-6 shrink-0 items-center gap-0.5 whitespace-nowrap rounded-md border px-2 text-xs font-semibold";

export const PRIORITY_READ_ONLY_HINT =
  "Priorytet zmienia Delivery Lead albo Head of Recruitment.";

function PriorityChipLabel({ level, paused = false }: { level: PriorityLevel; paused?: boolean }) {
  return (
    <>
      {paused ? <Pause className="h-3 w-3 shrink-0" aria-hidden="true" /> : null}
      <span aria-hidden="true">{PRIORITY_LEVEL_SHORT_LABEL[level]}</span>
      <span className="sr-only">
        Priorytet: {PRIORITY_LEVEL_LABEL[level]}
        {paused ? " (wstrzymany)" : ""}
      </span>
    </>
  );
}

export interface JobPriorityMenuProps {
  jobId: number;
  level: PriorityLevel;
  /** `useJobTeamPermissions(job).canSetPriority`. */
  canSet: boolean;
  /**
   * Zespół rekrutacji: zejście z P1 przenosi go do „Poprzedni rekruter”
   * (14.10.2026), więc menu pyta wtedy o potwierdzenie. Brak = bez pytania.
   */
  team?: JobPriorityTeam;
  /**
   * P1 wstrzymany, bo mamy championa (`job.priority_paused`, D6, 15.10.2026):
   * poziom zostaje P1, plakietka szara z pauzą, w menu zdanie dlaczego.
   */
  paused?: boolean;
}

/**
 * Priorytet przed tytułem rekrutacji (14.10.2026, makiety A2/A4/K1): ta sama
 * krótka plakietka co w wierszu listy — „P1”, „Bez priorytetu”, „Przyjmujemy”.
 * W nagłówku stoi też „Bez priorytetu”: widać, że pole jest i gdzie je
 * ustawić (na liście P2 nadal nie ma plakietki).
 *
 * Delivery Lead (w swoim zakresie), Head of Recruitment i administrator
 * zmieniają poziom z menu — zapis od razu, jak w panelu „Zespół”. Pozostali
 * widzą samą plakietkę z dymkiem, kto ją zmienia.
 */
export function JobPriorityMenu({
  jobId,
  level,
  canSet,
  team,
  paused = false,
}: JobPriorityMenuProps) {
  const { value, change, confirmDialog } = useJobPriorityChange(jobId, level, team);
  // Wstrzymanie dotyczy P1 — po zmianie poziomu w menu plakietka od razu
  // pokazuje nowy poziom.
  const levelPaused = paused && level === "p1";
  const valuePaused = paused && value === "p1";

  if (!canSet) {
    return (
      <span
        className={cn(CHIP_CLASS, levelPaused ? PAUSED_TONE : TONE[level])}
        title={
          levelPaused
            ? `${PRIORITY_PAUSED_HINT} ${PRIORITY_READ_ONLY_HINT}`
            : `${PRIORITY_LEVEL_LABEL[level]}. ${PRIORITY_READ_ONLY_HINT}`
        }
        data-testid="job-header-priority"
        data-priority={level}
        data-paused={levelPaused ? "true" : undefined}
      >
        <PriorityChipLabel level={level} paused={levelPaused} />
      </span>
    );
  }

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            CHIP_CLASS,
            valuePaused ? PAUSED_TONE : TONE[value],
            "hit-area hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          )}
          title={
            valuePaused
              ? `${PRIORITY_PAUSED_HINT} — zmień priorytet`
              : `${PRIORITY_LEVEL_LABEL[value]} — zmień priorytet`
          }
          data-testid="job-header-priority"
          data-priority={value}
          data-paused={valuePaused ? "true" : undefined}
        >
          <PriorityChipLabel level={value} paused={valuePaused} />
          <ChevronDown className="h-3 w-3" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-80" data-testid="job-priority-menu">
        <DropdownMenuLabel>Priorytet rekrutacji</DropdownMenuLabel>
        {valuePaused ? (
          <p
            className="mx-2 mb-1 flex items-start gap-1.5 rounded-md border border-dashed border-border px-2 py-1.5 text-xs leading-snug text-muted-foreground"
            data-testid="job-priority-paused-note"
          >
            <Pause className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
            {PRIORITY_PAUSED_HINT}
          </p>
        ) : null}
        <DropdownMenuRadioGroup
          value={value}
          onValueChange={(next) => {
            if (isPriorityLevel(next) && next !== value) change(next);
          }}
        >
          {PRIORITY_LEVELS.map((option) => (
            <DropdownMenuRadioItem
              key={option}
              value={option}
              className="items-start"
              data-testid={`job-priority-option-${option}`}
            >
              <span className="min-w-0">
                <span className={cn(CHIP_CLASS, TONE[option])}>
                  {PRIORITY_LEVEL_LABEL[option]}
                </span>
                <span className="mt-1 block text-xs leading-snug text-muted-foreground">
                  {PRIORITY_LEVEL_HINT[option]}
                </span>
              </span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <p className="mt-1 border-t border-border px-2 pb-1 pt-2 text-xs leading-snug text-muted-foreground">
          Zapis od razu po kliknięciu. Zmienia Delivery Lead, Head of Recruitment
          i administrator.
        </p>
      </DropdownMenuContent>
      {confirmDialog}
    </DropdownMenu>
  );
}
