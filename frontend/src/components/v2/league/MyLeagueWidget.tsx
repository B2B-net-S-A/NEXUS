"use client";

import { useEffect, useState } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useMyLeague } from "@/hooks/useMyLeague";
import { warsawToday } from "@/lib/warsaw-date";
import { useAuthStore } from "@/store/auth";

import { LeaguePanel } from "./LeaguePanel";
import { LeagueTopbarButton } from "./LeagueTopbarButton";
import { buildLeagueTopbarModel, leagueErrorModel, type LeagueTopbarModel } from "./league-topbar-model";
import { dayBaselineRank, leagueRankStorage } from "./league-rank-memory";

/**
 * Przycisk z panelem otwieranym kliknięciem — bez zapytań, więc harness
 * `/preview/kpi-topbar` klika ten sam komponent co pasek.
 */
export function LeagueTopbarPopover({
  model,
  className,
  onRetry,
}: {
  model: LeagueTopbarModel;
  className?: string;
  onRetry?: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    // Opakowanie niesie `hidden md:block` z TopbarV2. Bez `data-topbar-shrinks`:
    // w grupie akcji ściska się tylko licznik celów (`shell/topbar-layout.ts`).
    <div className={className}>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <LeagueTopbarButton model={model} open={open} />
        </PopoverTrigger>
        <PopoverContent align="end" aria-label={model.panel.title} className="w-[360px] overflow-hidden p-0">
          <LeaguePanel model={model} onNavigate={() => setOpen(false)} onRetry={onRetry} />
        </PopoverContent>
      </Popover>
    </div>
  );
}

/**
 * Liga Mistrzów w górnym pasku: miejsce i punkty (rekruter), miejsce
 * i placementy (Delivery Lead) albo prowadzący ligę (kto nie gra).
 *
 * - Pojawia się po pierwszej udanej odpowiedzi; ładowanie nie rysuje nic.
 * - Awaria bez wcześniejszych danych = „—” z „Ponów”, nigdy „0 pkt”.
 * - Strzałka awansu porównuje z miejscem z pierwszego widoku dnia.
 *
 * Reguły: docs/claude/ui/liga-w-gornym-pasku.md.
 */
export function MyLeagueWidget({ className }: { className?: string }) {
  const query = useMyLeague();
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const data = query.data;
  const [baselineRank, setBaselineRank] = useState<number | null>(null);

  const rank = data?.standing?.rank ?? null;
  const league = data && data.kind !== "spectator" ? `${data.type}:${data.period}` : null;
  // Dzień liczony przy każdym odświeżeniu (co 5 min): karta otwarta przez noc
  // nie trzyma wczorajszej strzałki, a dzisiejszy awans liczy się od rana.
  const today = warsawToday();
  const refreshedAt = query.dataUpdatedAt;
  useEffect(() => {
    if (league === null || userId === null) return;
    setBaselineRank(dayBaselineRank(leagueRankStorage(), userId, league, rank, today));
  }, [league, rank, userId, today, refreshedAt]);

  if (!data) {
    if (!query.isError) return null;
    return (
      <LeagueTopbarPopover model={leagueErrorModel()} className={className} onRetry={() => void query.refetch()} />
    );
  }
  const model = buildLeagueTopbarModel(data, { baselineRank });
  if (!model) return null;
  return <LeagueTopbarPopover model={model} className={className} />;
}
