"use client";

/**
 * Warunki: zapytanie klienta obok tej osoby. Wiersz powstaje tylko z pola, które
 * oddało API; bez danych po stronie zapytania stoi „—”, nie zgadujemy.
 */

import type { ReactNode } from "react";

import type { PanelCandidate, PanelCandidateDetail, PanelView } from "@/lib/api/clientPanel";
import { WORK_MODE_LABELS, type WorkMode } from "@/lib/work-mode";
import { cn } from "@/lib/utils";
import { warsawDateOf, warsawToday } from "@/lib/warsaw-date";

import { formatPanelDate, formatRate, type PillTone } from "./panel-logic";
import { PANEL_CARD, Pill } from "./parts";

const STALE_AVAILABILITY_DAYS = 14;
const DAY_MS = 86_400_000;

interface TermsRow {
  label: string;
  requested: string;
  value: ReactNode;
  match: { tone: PillTone; text: string } | null;
}

/** Czy potwierdzenie dostępności ma ponad 14 dni; brak daty to też „stare”. */
function availabilityStale(confirmedAt: string | null, today = warsawToday()): boolean {
  const day = warsawDateOf(confirmedAt);
  if (!day) return true;
  return Date.parse(today) - Date.parse(day) > STALE_AVAILABILITY_DAYS * DAY_MS;
}

function sameCity(a: string, b: string): boolean {
  return a.trim().toLocaleLowerCase("pl") === b.trim().toLocaleLowerCase("pl");
}

function workModeRow(view: PanelView, city: string | null): TermsRow | null {
  const { work_mode: mode, location } = view.job;
  if (!mode && !location) return null;
  const modeLabel = mode ? (WORK_MODE_LABELS[mode as WorkMode] ?? mode) : null;
  const requested = [modeLabel, location].filter(Boolean).join(", ");
  if (mode === "remote") {
    return { label: "Tryb pracy", requested, value: "zdalnie", match: { tone: "success", text: "zgodne" } };
  }
  if (!city) {
    return { label: "Tryb pracy", requested, value: "—", match: { tone: "warning", text: "dopytaj" } };
  }
  const differs = location ? !sameCity(city, location) : false;
  return {
    label: "Tryb pracy",
    requested,
    value: differs ? `dojazd z: ${city}` : city,
    match: differs
      ? { tone: "warning", text: "dopytaj o częstotliwość" }
      : { tone: "success", text: "zgodne" },
  };
}

function englishRow(view: PanelView, detail: PanelCandidateDetail): TermsRow | null {
  const requirement = view.requirements.find((item) => /angielsk|english/i.test(item.label));
  if (!requirement) return null;
  const entry = detail.evidence[requirement.key];
  const quote = entry?.items[0]?.quote;
  return {
    label: "Angielski",
    requested: requirement.label,
    value: quote ?? "nie ma w CV",
    match: quote ? { tone: "success", text: "w CV" } : { tone: "warning", text: "dopytaj" },
  };
}

export function TermsTab({
  view,
  candidate,
  detail,
}: {
  view: PanelView;
  candidate: PanelCandidate;
  detail: PanelCandidateDetail;
}) {
  const { terms } = detail;
  const rate = view.panel.show_rate ? formatRate(terms.rate) : null;
  const rows: TermsRow[] = [];
  if (rate) {
    rows.push({
      label: "Stawka",
      requested: "—",
      value: (
        <>
          <b className="tabular-nums">{rate}</b> netto, faktura B2B
        </>
      ),
      match: candidate.sent_at
        ? { tone: "neutral", text: `stan na ${formatPanelDate(candidate.sent_at)}` }
        : null,
    });
  }
  rows.push({
    label: "Start",
    requested: "—",
    value: terms.available_label,
    match:
      terms.available_label === "do ustalenia"
        ? { tone: "warning", text: "do ustalenia" }
        : null,
  });
  const modeRow = workModeRow(view, terms.city);
  if (modeRow) rows.push(modeRow);
  const english = englishRow(view, detail);
  if (english) rows.push(english);

  return (
    <div className="overflow-auto">
      <div className={cn(PANEL_CARD, "overflow-x-auto")}>
        <table className="w-full min-w-[560px] border-collapse text-sm" data-testid="terms-table">
          <thead>
            <tr className="border-b border-border text-xs text-muted-foreground">
              <th className="px-3.5 py-2 text-left font-medium">Pozycja</th>
              <th className="px-3.5 py-2 text-left font-medium">Twoje zapytanie</th>
              <th className="px-3.5 py-2 text-left font-medium">Ten kandydat</th>
              <th className="px-3.5 py-2 text-left font-medium">Zgodność</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-b border-border align-top last:border-b-0">
                <td className="px-3.5 py-2">{row.label}</td>
                <td className="px-3.5 py-2 text-muted-foreground">{row.requested}</td>
                <td className="px-3.5 py-2">{row.value}</td>
                <td className="px-3.5 py-2">
                  {row.match ? <Pill tone={row.match.tone}>{row.match.text}</Pill> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Dostępność potwierdzona z kandydatem:{" "}
        {terms.available_confirmed_at ? formatPanelDate(terms.available_confirmed_at) : "brak daty"}.
        {availabilityStale(terms.available_confirmed_at)
          ? " Dane mają ponad 14 dni albo nie mają daty, dopytaj opiekuna procesu przed decyzją."
          : ""}
      </p>
    </div>
  );
}
