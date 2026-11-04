"use client";

/** Porównanie 2–3 osób: dostępność, stawka i po jednym wierszu na wymaganie. */

import { useQueries } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { panelCandidateKey, type PanelCandidate, type PanelView } from "@/lib/api/clientPanel";
import { cn } from "@/lib/utils";

import { usePanelContext } from "./panel-context";
import { STATUS_LABELS, formatRate } from "./panel-logic";
import { PANEL_CARD, StatePill, StatusDot } from "./parts";

export function CompareView({
  view,
  candidates,
  onBack,
  onOpen,
}: {
  view: PanelView;
  candidates: readonly PanelCandidate[];
  onBack: () => void;
  onOpen: (publicId: string) => void;
}) {
  const { token, transport } = usePanelContext();
  const details = useQueries({
    queries: candidates.map((candidate) => ({
      queryKey: panelCandidateKey(token, candidate.public_id),
      queryFn: () => transport.fetchCandidate(candidate.public_id),
      staleTime: 30_000,
    })),
  });
  const showRate = view.panel.show_rate;
  const cell = "border-b border-border px-3.5 py-2 text-left align-top";

  return (
    <main className="min-h-0 flex-1 overflow-auto px-4 py-3" data-testid="client-panel-compare">
      <div className="mb-2 flex items-center gap-3">
        <Button variant="outline" size="sm" onClick={onBack}>
          <ChevronLeft className="h-3.5 w-3.5" />
          Wszyscy
        </Button>
        <h1 className="font-display text-lg font-bold tracking-tight">Porównanie</h1>
      </div>
      <div className={cn(PANEL_CARD, "overflow-x-auto")}>
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            <tr>
              <th className={cn(cell, "sticky left-0 z-10 bg-card")} />
              {candidates.map((candidate) => (
                <th key={candidate.public_id} className={cn(cell, "font-medium")}>
                  <button
                    type="button"
                    className="font-semibold underline-offset-2 hover:underline"
                    onClick={() => onOpen(candidate.public_id)}
                  >
                    {candidate.name}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {showRate ? (
              <tr>
                <td className={cn(cell, "sticky left-0 z-10 bg-card")}>Stawka</td>
                {candidates.map((candidate) => (
                  <td key={candidate.public_id} className={cn(cell, "tabular-nums")}>
                    {formatRate(candidate.rate) ?? "—"}
                  </td>
                ))}
              </tr>
            ) : null}
            <tr>
              <td className={cn(cell, "sticky left-0 z-10 bg-card")}>Dostępny</td>
              {candidates.map((candidate) => (
                <td key={candidate.public_id} className={cell}>
                  {candidate.available_label}
                </td>
              ))}
            </tr>
            <tr>
              <td className={cn(cell, "sticky left-0 z-10 bg-card")}>Stan</td>
              {candidates.map((candidate) => (
                <td key={candidate.public_id} className={cell}>
                  <StatePill state={candidate.state} />
                </td>
              ))}
            </tr>
            {view.requirements.map((requirement) => (
              <tr key={requirement.key}>
                <td className={cn(cell, "sticky left-0 z-10 bg-card")}>{requirement.label}</td>
                {candidates.map((candidate, index) => {
                  const status = candidate.statuses[requirement.key] ?? "none";
                  const first = details[index].data?.evidence[requirement.key]?.items[0];
                  return (
                    <td key={candidate.public_id} className={cell}>
                      <span className="inline-flex items-baseline gap-1.5">
                        <StatusDot status={status} size="sm" className="self-center" />
                        <span
                          className={cn("text-xs", status === "none" && "text-muted-foreground")}
                        >
                          {first?.where ?? STATUS_LABELS[status]}
                        </span>
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
