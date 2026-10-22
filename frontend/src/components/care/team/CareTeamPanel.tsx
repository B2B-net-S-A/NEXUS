"use client";

import { useState } from "react";
import Link from "next/link";
import { Settings2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useCareAssignment, useCareAutoAssignment, useCareConsultants, type CareAssignment } from "@/lib/api/care";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { HEALTH_BAR, HEALTH_LABELS, healthSegments } from "../health-format";
import { AutoAssignBar } from "../OwnerPoolPanel";
import { AssignmentSettingsDialog } from "./AssignmentSettingsDialog";
import {
  consultantsOfHref,
  doneText,
  inMonthPl,
  loadText,
  ownerRoleText,
  portfolioText,
  settingsSummary,
  teamRows,
} from "./team-format";

/**
 * Tabela zespołu (makieta P6): rozmowy w następnym miesiącu z progiem,
 * podopieczni, zaległe dziś, zrobione w bieżącym miesiącu, stan portfela
 * i link do „Konsultantów” tego opiekuna (tam hurtowe przepinanie).
 */
function TeamTable({ assignment }: { assignment: CareAssignment }) {
  const consultants = useCareConsultants();
  if (consultants.isError) {
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się wczytać podopiecznych zespołu."
        onRetry={() => consultants.refetch()}
      />
    );
  }
  if (!consultants.isSuccess) {
    return <p className="text-sm text-muted-foreground">Wczytywanie zespołu…</p>;
  }
  const rows = teamRows(consultants.data.items, assignment.owners);
  const healthVisible = consultants.data.items.some((row) => row.health != null);
  if (!rows.length) {
    return <p className="text-sm text-muted-foreground">Nikt nie jest jeszcze opiekunem.</p>;
  }
  const threshold = assignment.threshold.monthly_conversations;
  const nextMonth = inMonthPl(assignment.month.from);
  const thisMonth = inMonthPl(assignment.this_month?.from ?? assignment.today);
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full min-w-[860px] text-sm" aria-label="Opiekunowie, zaległe i portfel">
        <thead>
          <tr className={CALM_ROW}>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Opiekun</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>
              Rozmowy {nextMonth}
              {threshold ? ` · próg ${threshold}` : ""}
            </th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Podopieczni</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Zaległe dziś</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Zrobione {thisMonth}</th>
            {healthVisible ? <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Stan portfela</th> : null}
            <th className={cn(CALM_HEAD, "px-3 py-2 text-right")}>
              <span className="sr-only">Konsultanci opiekuna</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const segments = healthSegments(row.health);
            const load = loadText(row);
            const done = doneText(row);
            const portfolio = portfolioText(row.health);
            return (
              <tr key={row.id} className={CALM_ROW}>
                <td className="px-3 py-1.5 align-top">
                  <span className="font-medium">{row.name}</span>
                  <span className={CALM_SUBLINE}>{ownerRoleText(row) || " "}</span>
                </td>
                <td className="px-3 py-1.5 align-top">
                  {load ? (
                    <span className={cn(row.overThreshold && "font-medium text-warning-muted-foreground")}>{load}</span>
                  ) : (
                    <span className={CALM_EMPTY}>—</span>
                  )}
                </td>
                <td className="px-3 py-1.5 align-top tabular-nums">{row.consultants}</td>
                <td className="px-3 py-1.5 align-top">
                  {!row.consultants ? (
                    <span className={CALM_EMPTY}>—</span>
                  ) : row.overdue ? (
                    <Badge variant="danger" size="md">
                      {row.overdue}
                    </Badge>
                  ) : (
                    <span className={CALM_EMPTY}>0</span>
                  )}
                </td>
                <td className="px-3 py-1.5 align-top tabular-nums">
                  {done ?? <span className={CALM_EMPTY}>—</span>}
                </td>
                {healthVisible ? (
                  <td className="min-w-40 px-3 py-1.5 align-top">
                    {segments.length ? (
                      <>
                        <span
                          className="flex h-1.5 w-32 overflow-hidden rounded-full bg-muted"
                          role="img"
                          aria-label={segments.map((s) => `${HEALTH_LABELS[s.level]}: ${s.count}`).join(", ")}
                        >
                          {segments.map((segment) => (
                            <span
                              key={segment.level}
                              className={HEALTH_BAR[segment.level]}
                              style={{ width: `${segment.percent}%` }}
                            />
                          ))}
                        </span>
                        {portfolio ? <span className={CALM_SUBLINE}>{portfolio}</span> : null}
                      </>
                    ) : (
                      <span className={CALM_EMPTY}>—</span>
                    )}
                  </td>
                ) : null}
                <td className="px-3 py-1.5 text-right align-top">
                  <Link
                    href={consultantsOfHref(row.id)}
                    className="text-xs font-medium text-primary hover:underline"
                    aria-label={`Konsultanci: ${row.name}`}
                  >
                    Konsultanci
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * „Opieka · Zespół opiekunów” (head back office i admin, makieta P6): w
 * nagłówku zwinięty opis ustawień przydziału i przycisk „Ustawienia
 * przydziału” (jedno okno: pula, „Nie przypisuj”, próg, automat dla nowych,
 * domyślni opiekunowie klientów), pod nim pasek „bez opiekuna” z „Przypisz
 * wg obłożenia” i tabela zespołu. Hurtowe przepinanie — w „Konsultantach”
 * po zaznaczeniu (link „Konsultanci” przy opiekunie).
 */
export function CareTeamPanel() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const assignment = useCareAssignment();
  const auto = useCareAutoAssignment();
  const state = resolveViewState({
    isLoading: assignment.isLoading,
    isError: assignment.isError,
    error: assignment.error,
    isSuccess: assignment.isSuccess,
  });
  if (state === "loading") return <p className="text-sm text-muted-foreground">Wczytywanie zespołu…</p>;
  if (state !== "ready" || !assignment.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        description={state === "error" ? "Nie udało się wczytać zespołu opiekunów." : undefined}
        onRetry={() => assignment.refetch()}
      />
    );
  }
  const data = assignment.data;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2">
        <p className="min-w-0 text-xs text-muted-foreground" data-assignment-settings-summary>
          <span className="font-medium text-foreground">Ustawienia przydziału: </span>
          {settingsSummary(data, auto.data ?? null)}
        </p>
        <Button size="sm" variant="outline" onClick={() => setSettingsOpen(true)}>
          <Settings2 className="size-3.5" aria-hidden />
          Ustawienia przydziału
        </Button>
      </div>
      {data.can_assign ? <AutoAssignBar /> : null}
      <TeamTable assignment={data} />
      {settingsOpen ? (
        <AssignmentSettingsDialog data={data} open onOpenChange={setSettingsOpen} />
      ) : null}
    </div>
  );
}
