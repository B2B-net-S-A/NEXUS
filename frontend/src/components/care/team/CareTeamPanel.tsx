"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { useCareAssignment, useCareConsultants } from "@/lib/api/care";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { AssignmentPanel } from "../AssignmentPanel";
import { peopleText, talksText } from "../cadence-format";
import { HEALTH_BAR, HEALTH_LABELS, healthSegments } from "../health-format";
import { OwnerPoolPanel } from "../OwnerPoolPanel";
import { teamRows, withoutOwner } from "./team-format";

/** Tabela opiekunów: podopieczni, zaległe rozmowy, stan portfela, rozmowy w następnym miesiącu. */
function TeamTable() {
  const consultants = useCareConsultants();
  const assignment = useCareAssignment();
  if (!consultants.isSuccess || !assignment.isSuccess) {
    // Błędy obu zapytań pokazuje „Przydział” niżej (to samo zapytanie) i lista „Konsultanci”.
    return consultants.isLoading || assignment.isLoading ? (
      <p className="text-sm text-muted-foreground">Wczytywanie zespołu…</p>
    ) : null;
  }
  const rows = teamRows(consultants.data.items, assignment.data.owners);
  const orphans = withoutOwner(consultants.data.items);
  const healthVisible = consultants.data.items.some((row) => row.health != null);
  if (!rows.length) {
    return <p className="text-sm text-muted-foreground">Nikt nie jest jeszcze opiekunem.</p>;
  }
  return (
    <section aria-label="Opiekunowie" className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Opiekunowie</h3>
        {orphans ? (
          <span className="text-xs text-muted-foreground">Bez opiekuna: {peopleText(orphans)}</span>
        ) : null}
      </div>
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <table className="w-full min-w-[640px] text-sm" aria-label="Opiekunowie, zaległe i portfel">
          <thead>
            <tr className={CALM_ROW}>
              <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Opiekun</th>
              <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Podopieczni</th>
              <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Zaległe rozmowy</th>
              {healthVisible ? <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Stan portfela</th> : null}
              <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Rozmowy w następnym miesiącu</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const segments = healthSegments(row.health);
              return (
                <tr key={row.id} className={CALM_ROW}>
                  <td className="px-3 py-1.5 align-top font-medium">
                    {row.name}
                    {row.isDeliveryLead ? <span className="font-normal text-muted-foreground"> (DL)</span> : null}
                  </td>
                  <td className="px-3 py-1.5 align-top tabular-nums">{row.consultants}</td>
                  <td className="px-3 py-1.5 align-top">
                    {row.overdue ? (
                      <Badge variant="danger" size="md">
                        {row.overdue}
                      </Badge>
                    ) : (
                      <span className={CALM_EMPTY}>0</span>
                    )}
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
                          <span className={CALM_SUBLINE}>
                            {[
                              row.health.risk ? `${row.health.risk} ryzyko` : null,
                              row.health.watch ? `${row.health.watch} uwaga` : null,
                              `${row.health.ok} dobrze`,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                        </>
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                    </td>
                  ) : null}
                  <td className="px-3 py-1.5 align-top">
                    {row.conversations != null ? talksText(row.conversations) : <span className={CALM_EMPTY}>—</span>}
                    {row.overThreshold ? <span className={CALM_SUBLINE}>powyżej progu</span> : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/**
 * „Opieka · Zespół opiekunów” (head back office i admin): opiekunowie
 * z zaległymi i stanem portfela, „Ustawienia przydziału” (pula opiekunów
 * i automat „wg obłożenia”) zwinięte, pod nimi dawny „Przydział”.
 */
export function CareTeamPanel() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  return (
    <div className="space-y-4">
      <TeamTable />
      <Collapsible
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        className="rounded-lg border border-border bg-card"
      >
        <CollapsibleTrigger className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-sm font-medium text-foreground hover:bg-muted/50">
          <ChevronRight
            aria-hidden
            className={cn("size-4 text-muted-foreground transition-transform", settingsOpen && "rotate-90")}
          />
          Ustawienia przydziału
          <span className="text-xs font-normal text-muted-foreground">
            pula opiekunów, „nie przypisuj”, automat dla nowych kontraktów
          </span>
        </CollapsibleTrigger>
        <CollapsibleContent className="border-t border-border p-3">
          {settingsOpen ? <OwnerPoolPanel /> : null}
        </CollapsibleContent>
      </Collapsible>
      <AssignmentPanel withPool={false} />
    </div>
  );
}
