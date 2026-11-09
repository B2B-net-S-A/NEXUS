"use client";

/**
 * Lista kandydatów: kropki wymagań z przesłanego CV, stawka, dostępność, stan.
 * Tabela przewija się w swoim kontenerze z przyklejoną pierwszą kolumną, strona
 * nie przewija się w poziomie.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { PanelView } from "@/lib/api/clientPanel";
import { WORK_MODE_LABELS, type WorkMode } from "@/lib/work-mode";
import { cn } from "@/lib/utils";

import {
  STATUS_LABELS,
  candidatesCountLabel,
  formatPanelDate,
  formatRate,
  shortRequirementLabel,
} from "./panel-logic";
import { PANEL_CARD, PanelTabs, Pill, StatePill, StatusDot } from "./parts";

const MAX_COMPARED = 3;
const LIST_TABS = [
  { id: "candidates", label: "Kandydaci" },
  { id: "request", label: "Twoje zapytanie" },
] as const;

type ListTab = (typeof LIST_TABS)[number]["id"];

function latestSentAt(view: PanelView): string | null {
  return view.candidates.reduce<string | null>(
    (latest, item) => (item.sent_at && (!latest || item.sent_at > latest) ? item.sent_at : latest),
    null,
  );
}

function RequestTab({
  view,
  onChangeRequirements,
}: {
  view: PanelView;
  onChangeRequirements: () => void;
}) {
  const { job, requirements, candidates } = view;
  const workMode = job.work_mode ? WORK_MODE_LABELS[job.work_mode as WorkMode] : null;
  const facts = [
    workMode ? ["Tryb pracy", workMode] : null,
    job.location ? ["Lokalizacja", job.location] : null,
    job.deadline ? ["Termin", formatPanelDate(job.deadline)] : null,
  ].filter((item): item is [string, string] => item != null);

  return (
    <div className="grid items-start gap-3 md:grid-cols-[minmax(0,1fr)_340px]">
      <div
        className={cn(PANEL_CARD, "max-h-[60dvh] overflow-auto whitespace-pre-wrap px-4 py-3 text-sm")}
        tabIndex={0}
      >
        {job.request_text?.trim() || (
          <span className="text-muted-foreground">
            Treści zapytania nie ma w panelu. Opiekun procesu prześle ją na prośbę.
          </span>
        )}
      </div>
      <div className={cn(PANEL_CARD, "grid gap-1.5 px-3.5 py-3")}>
        <h2 className="font-display text-sm font-semibold">Jak czytamy Twoje wymagania</h2>
        <p className="mb-1 text-xs text-muted-foreground">
          {job.added_at
            ? `Treść po lewej to zapytanie w brzmieniu, które dostaliśmy ${formatPanelDate(job.added_at)}. `
            : "Treść po lewej to zapytanie w brzmieniu, które dostaliśmy. "}
          Na tych {requirements.length} punktach opieramy kropki na liście.
        </p>
        {requirements.map((requirement) => {
          const inProjects = candidates.filter(
            (item) => item.statuses[requirement.key] === "project",
          ).length;
          return (
            <div key={requirement.key} className="flex items-center gap-2 text-sm">
              <Pill tone={inProjects > 0 ? "success" : "neutral"}>
                {inProjects}/{candidates.length}
              </Pill>
              <span className="min-w-0">{requirement.label}</span>
            </div>
          );
        })}
        {facts.length > 0 ? (
          <dl className="mt-2 grid gap-0.5 border-t border-border pt-2 text-xs">
            {facts.map(([label, value]) => (
              <div key={label} className="flex justify-between gap-3">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="text-right">{value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {view.panel.allow_actions ? (
          <Button variant="outline" className="mt-2" onClick={onChangeRequirements}>
            Coś się zmieniło? Popraw wymagania
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function CandidatesList({
  view,
  selected,
  onSelectedChange,
  onCompare,
  onOpen,
  onChangeRequirements,
}: {
  view: PanelView;
  selected: readonly string[];
  onSelectedChange: (ids: string[]) => void;
  onCompare: () => void;
  onOpen: (publicId: string) => void;
  onChangeRequirements: () => void;
}) {
  const [tab, setTab] = useState<ListTab>("candidates");
  const { job, requirements, candidates, panel } = view;
  const sentAt = latestSentAt(view);
  const canCompare = panel.show_other_candidates && candidates.length >= 2;
  const showRate = panel.show_rate;
  const meta = [
    job.client_name,
    job.reference,
    job.added_at ? `zapytanie z ${formatPanelDate(job.added_at)}` : null,
    sentAt ? `kandydaci wysłani ${formatPanelDate(sentAt)}` : null,
  ].filter(Boolean);

  const toggle = (publicId: string) => {
    onSelectedChange(
      selected.includes(publicId)
        ? selected.filter((id) => id !== publicId)
        : selected.length < MAX_COMPARED
          ? [...selected, publicId]
          : [...selected],
    );
  };

  return (
    <main className="min-h-0 flex-1 overflow-auto">
      <div className="px-4 py-3">
        <div className="mb-2 flex flex-wrap items-end gap-x-4 gap-y-2">
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{meta.join(" · ")}</p>
            <h1 className="font-display text-xl font-bold tracking-tight">
              {job.title}, {candidatesCountLabel(candidates.length)}
            </h1>
          </div>
          {canCompare ? (
            <div className="ml-auto">
              <Button variant="outline" disabled={selected.length < 2} onClick={onCompare}>
                Porównaj ({selected.length})
              </Button>
            </div>
          ) : null}
        </div>

        <PanelTabs tabs={LIST_TABS} active={tab} onChange={setTab} label="Widok panelu" />

        {tab === "request" ? (
          <RequestTab view={view} onChangeRequirements={onChangeRequirements} />
        ) : candidates.length === 0 ? (
          <div className={cn(PANEL_CARD, "p-4 text-sm text-muted-foreground")}>
            Nie ma tu jeszcze kandydatów do pokazania. Otwórz link z przesłanego CV albo napisz do
            opiekuna procesu.
          </div>
        ) : (
          <>
            <div className="mb-2 flex flex-wrap items-center gap-x-3.5 gap-y-1 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <StatusDot status="project" size="sm" />w opisie projektu w CV
              </span>
              <span className="inline-flex items-center gap-1.5">
                <StatusDot status="list" size="sm" />
                tylko na liście umiejętności lub w certyfikacie
              </span>
              <span className="inline-flex items-center gap-1.5">
                <StatusDot status="none" size="sm" />
                nie ma w CV
              </span>
              <span className="sm:ml-auto">Kliknij wiersz, żeby zobaczyć dowody w CV.</span>
            </div>
            <div className={cn(PANEL_CARD, "overflow-x-auto")}>
              <table className="w-full min-w-[720px] border-collapse text-sm" data-testid="client-panel-matrix">
                <thead>
                  <tr className="border-b border-border text-[11px] font-medium text-muted-foreground">
                    <th className="sticky left-0 z-10 bg-card px-2.5 py-1.5 text-left font-medium">
                      Kandydat
                    </th>
                    {requirements.map((requirement) => (
                      <th
                        key={requirement.key}
                        title={requirement.label}
                        className="whitespace-nowrap px-0.5 py-1.5 text-center font-medium"
                      >
                        {shortRequirementLabel(requirement.label)}
                      </th>
                    ))}
                    {showRate ? <th className="px-2 py-1.5 text-center font-medium">Stawka</th> : null}
                    <th className="px-1.5 py-1.5 text-center font-medium">Dostępny</th>
                    <th className="px-2.5 py-1.5 text-right font-medium">Stan</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((candidate) => {
                    const rate = showRate ? formatRate(candidate.rate) : null;
                    const dim = candidate.state === "not_fit";
                    return (
                      <tr
                        key={candidate.public_id}
                        onClick={() => onOpen(candidate.public_id)}
                        className={cn(
                          "group cursor-pointer border-b border-border last:border-b-0 hover:bg-muted",
                          dim && "text-muted-foreground",
                        )}
                        data-testid={`candidate-row-${candidate.public_id}`}
                      >
                        <td className="sticky left-0 z-10 min-w-[200px] bg-card px-2.5 py-1.5 group-hover:bg-muted">
                          <div className="flex items-start gap-2">
                            {canCompare ? (
                              <input
                                type="checkbox"
                                className="mt-1 h-3.5 w-3.5 shrink-0 accent-primary"
                                checked={selected.includes(candidate.public_id)}
                                disabled={
                                  !selected.includes(candidate.public_id) &&
                                  selected.length >= MAX_COMPARED
                                }
                                aria-label={`Porównaj: ${candidate.name}`}
                                onClick={(event) => event.stopPropagation()}
                                onChange={() => toggle(candidate.public_id)}
                              />
                            ) : null}
                            <div className="min-w-0">
                              <button
                                type="button"
                                className="text-left font-semibold underline-offset-2 hover:underline focus-visible:underline focus-visible:outline-hidden"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  onOpen(candidate.public_id);
                                }}
                              >
                                {candidate.name}
                              </button>
                              <div className="text-xs text-muted-foreground">
                                {candidate.title ? `${candidate.title} · ` : ""}
                                {candidate.in_projects} z {requirements.length}
                              </div>
                            </div>
                          </div>
                        </td>
                        {requirements.map((requirement) => {
                          const status = candidate.statuses[requirement.key] ?? "none";
                          return (
                            <td
                              key={requirement.key}
                              title={`${requirement.label}: ${STATUS_LABELS[status]}`}
                              className={cn("px-0.5 py-1.5 text-center", dim && "opacity-55")}
                            >
                              <StatusDot status={status} />
                            </td>
                          );
                        })}
                        {showRate ? (
                          <td className="whitespace-nowrap px-2 py-1.5 text-center tabular-nums">
                            {rate ?? "—"}
                          </td>
                        ) : null}
                        <td className="whitespace-nowrap px-1.5 py-1.5 text-center">
                          {candidate.available_label}
                        </td>
                        <td className="px-2.5 py-1.5 text-right">
                          <StatePill state={candidate.state} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Kropki pokazują wyłącznie to, co jest w przesłanym CV.
              {showRate && sentAt ? ` Stawka: netto, faktura B2B, stan na ${formatPanelDate(sentAt)}.` : ""}
            </p>
          </>
        )}
      </div>
    </main>
  );
}
