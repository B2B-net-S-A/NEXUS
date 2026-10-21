"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";

import JobBoardsCard, { STATUS_LABEL, STATUS_TONE } from "@/components/settings/JobBoardsCard";
import {
  TEAMS_PREP_HEALTH_KEY,
  TEAMS_PREP_LABELS,
  TeamsPrepStatusCard,
  fetchTeamsPrepHealth,
} from "@/components/settings/TeamsPrepStatusCard";
import { Button } from "@/components/ui/button";
import { EsignSettingsCard } from "@/components/v2/b2b-generator/esign/EsignSettingsCard";
import { JOB_BOARD_CONNECTION_KEY, fetchJobBoardConnection } from "@/lib/api/jobPortals";
import { cn } from "@/lib/utils";

interface StateBadge {
  text: string;
  className: string;
}

const CHECKING: StateBadge = { text: "Sprawdzanie…", className: "bg-muted text-muted-foreground" };
const UNKNOWN: StateBadge = { text: "Nie udało się sprawdzić", className: "bg-muted text-muted-foreground" };

function Row({
  title,
  description,
  badge,
  action,
  children,
}: {
  title: string;
  description: string;
  badge?: StateBadge;
  action?: ReactNode;
  /** Szczegóły rozwijane w wierszu (karta dotychczasowego ekranu). */
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-border last:border-b-0">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <div className="min-w-0 flex-1 basis-64">
          <p className="text-sm font-semibold text-foreground">{title}</p>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
        {badge ? (
          <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", badge.className)}>{badge.text}</span>
        ) : null}
        {children ? (
          <Button variant="outline" size="sm" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            {open ? (
              <ChevronDown className="mr-1 h-4 w-4" aria-hidden />
            ) : (
              <ChevronRight className="mr-1 h-4 w-4" aria-hidden />
            )}
            Szczegóły
          </Button>
        ) : null}
        {action}
      </div>
      {children && open ? <div className="px-4 pb-4">{children}</div> : null}
    </li>
  );
}

/**
 * Ustawienia → System → Integracje (runda 2, 21.10.2026): jedna lista
 * połączeń ze stanem i następnym krokiem. Dotąd trzy pozycje menu w trzech
 * różnych układach — żeby sprawdzić, czy wszystko się łączy, trzeba było
 * wejść w każdą. Szczegóły to dotychczasowe karty, rozwijane w wierszu;
 * klucze API zostają osobnym ekranem (`/settings/api-keys`).
 */
export function IntegrationsSettings() {
  const teams = useQuery({ queryKey: TEAMS_PREP_HEALTH_KEY, queryFn: fetchTeamsPrepHealth, staleTime: 60_000 });
  const boards = useQuery({ queryKey: JOB_BOARD_CONNECTION_KEY, queryFn: fetchJobBoardConnection, staleTime: 30_000 });

  const teamsBadge: StateBadge = teams.isPending
    ? CHECKING
    : teams.isError || !teams.data
      ? UNKNOWN
      : TEAMS_PREP_LABELS[teams.data];
  const boardStatus = boards.data?.status ?? "not_connected";
  const boardsBadge: StateBadge = boards.isPending
    ? CHECKING
    : boards.isError
      ? UNKNOWN
      : { text: STATUS_LABEL[boardStatus], className: STATUS_TONE[boardStatus] };

  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card" aria-label="Połączenia">
      <ul>
        <Row
          title="Prepy w Teams"
          description="Transkrypt Prepu 1 i 2 → notatka u kandydata i ocena prepu."
          badge={teamsBadge}
        >
          <TeamsPrepStatusCard />
        </Row>
        <Row
          title="RocketJobs i JustJoin.IT"
          description="Publikacja ogłoszeń z okna rekrutacji — jedno konto firmy u dostawcy obu portali."
          badge={boardsBadge}
        >
          <JobBoardsCard />
        </Row>
        <Row
          title="Podpis umów B2B w NEXUSIE"
          description="Druga droga obok maila: kontraktor i reprezentant podpisują kwalifikowanie, plik zostaje przy kontrakcie."
        >
          <EsignSettingsCard />
        </Row>
        <Row
          title="Klucze API"
          description="Konta serwisowe i klucze X-API-Key dla automatyzacji (np. rozliczeń w n8n)."
          action={
            <Button asChild variant="outline" size="sm">
              <Link href="/settings/api-keys">Zarządzaj</Link>
            </Button>
          }
        />
      </ul>
    </section>
  );
}
