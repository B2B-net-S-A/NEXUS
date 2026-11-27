"use client";

/**
 * Przegląd (makieta 1 raportu „Tarcza NEXUSA”, 27.11.2026): cztery kafelki,
 * „Czeka na reakcję” po wadze, zdarzenia na żywo i tabela źródeł. Źródło,
 * którego jeszcze nie ma (CrowdSec, Falco, Wazuh, DefectDojo), ma stan
 * „nieskonfigurowane”, a nie błąd. Dane: `GET /api/security/overview`.
 */

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatIsoDatePl, formatMomentPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import {
  buildTiles,
  eventTone,
  SEVERITY_LABEL,
  SEVERITY_TONE,
  SOURCE_STATE_TONE,
  sourceLabel,
  type SecurityFinding,
  type SecurityOverview,
} from "./security-model";
import { SecurityFindingSheet } from "./SecurityFindingSheet";
import { TONE_BADGE, TONE_STRIPE } from "./tone";

const TIME = new Intl.DateTimeFormat("pl-PL", {
  timeZone: "Europe/Warsaw",
  hour: "2-digit",
  minute: "2-digit",
});
const DAY = new Intl.DateTimeFormat("pl-PL", { timeZone: "Europe/Warsaw", day: "2-digit", month: "2-digit" });

function eventTime(iso: string, today: string): string {
  const date = new Date(iso);
  const sameDay = formatIsoDatePl(iso) === formatIsoDatePl(today);
  return sameDay ? TIME.format(date) : DAY.format(date);
}

function FindingRow({
  finding,
  onOpen,
  selected,
}: {
  finding: SecurityFinding;
  onOpen: (f: SecurityFinding) => void;
  selected: boolean;
}) {
  const fixed = finding.status === "fixed";
  return (
    <li
      className={cn(
        "grid grid-cols-[5.5rem_minmax(0,1fr)_auto] items-center gap-3 px-4 py-2",
        selected && "bg-primary/5",
      )}
    >
      <Badge variant={fixed ? "success" : TONE_BADGE[SEVERITY_TONE[finding.severity]]} className="justify-self-start">
        {fixed ? "zamknięte" : SEVERITY_LABEL[finding.severity]}
      </Badge>
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-foreground">{finding.title}</p>
        <p className="truncate text-xs text-muted-foreground">
          {sourceLabel(finding.source)}
          {finding.scanner && finding.scanner !== finding.source ? ` · ${finding.scanner}` : ""}
          {fixed
            ? ` · zamknięte ${formatIsoDatePl(finding.closed_at)}`
            : ` · od ${formatIsoDatePl(finding.first_seen_at)}`}
          {finding.location ? ` · ${finding.location}` : ""}
          {finding.exception_expired ? " · wyjątek minął" : ""}
        </p>
      </div>
      <Button size="sm" variant="outline" onClick={() => onOpen(finding)}>
        {fixed ? "Historia" : "Otwórz"}
      </Button>
    </li>
  );
}

export interface SecurityOverviewPanelProps {
  data: SecurityOverview;
}

export function SecurityOverviewPanel({ data }: SecurityOverviewPanelProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const all = [...data.waiting, ...data.excepted, ...data.recently_closed];
  const selected = all.find((f) => f.id === selectedId) ?? null;
  const tiles = buildTiles(data.tiles, (iso) => formatMomentPl(iso).replace(/\.\d{4},/, ","));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {tiles.map((tile) => (
          <div
            key={tile.key}
            data-testid={`security-tile-${tile.key}`}
            className={cn("rounded-lg border border-border border-l-4 bg-card px-4 py-2.5", TONE_STRIPE[tile.tone])}
          >
            <p className="text-xs text-muted-foreground">{tile.label}</p>
            <p className="text-xl font-bold tabular-nums text-foreground">{tile.value}</p>
            <p className="line-clamp-2 text-xs text-muted-foreground">{tile.sub}</p>
          </div>
        ))}
      </div>

      <div className="grid min-w-0 gap-4 2xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <section className="min-w-0 rounded-lg border border-border bg-card" aria-labelledby="security-waiting">
          <h2 id="security-waiting" className="flex items-center justify-between border-b border-border px-4 py-2 text-sm font-semibold">
            Czeka na reakcję <Badge variant="outline">{data.waiting.length}</Badge>
          </h2>
          {data.waiting.length === 0 ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">Nic nie czeka. Nowe znaleziska ze skanerów pojawią się tutaj.</p>
          ) : null}
          <ul className="divide-y divide-border">
            {data.waiting.map((f) => (
              <FindingRow key={f.id} finding={f} onOpen={(x) => setSelectedId(x.id)} selected={f.id === selectedId} />
            ))}
          </ul>
          {data.excepted.length ? (
            <>
              <h3 className="border-y border-border bg-muted/40 px-4 py-1.5 text-xs font-semibold text-muted-foreground">
                Wyjątki z terminem ({data.excepted.length})
              </h3>
              <ul className="divide-y divide-border">
                {data.excepted.map((f) => (
                  <li key={f.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-4 py-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm text-foreground">{f.title}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        do {formatIsoDatePl(f.exception_until)} · {f.exception_reason}
                      </p>
                    </div>
                    <Button size="sm" variant="ghost" onClick={() => setSelectedId(f.id)}>
                      Otwórz
                    </Button>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          {data.recently_closed.length ? (
            <ul className="divide-y divide-border border-t border-border">
              {data.recently_closed.map((f) => (
                <FindingRow key={f.id} finding={f} onOpen={(x) => setSelectedId(x.id)} selected={f.id === selectedId} />
              ))}
            </ul>
          ) : null}
        </section>

        <section className="min-w-0 rounded-lg border border-border bg-card" aria-labelledby="security-events">
          <h2 id="security-events" className="border-b border-border px-4 py-2 text-sm font-semibold">
            Zdarzenia na żywo
          </h2>
          {data.events.length === 0 ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">Jeszcze nic nie przyszło.</p>
          ) : (
            <ul className="max-h-80 divide-y divide-border overflow-y-auto">
              {data.events.map((e) => (
                <li key={e.id} className="grid grid-cols-[3rem_auto_minmax(0,1fr)] items-center gap-2 px-4 py-1.5 text-sm">
                  <span className="font-mono text-xs text-muted-foreground">{eventTime(e.occurred_at, data.today)}</span>
                  <Badge variant={TONE_BADGE[eventTone(e)]}>{sourceLabel(e.source)}</Badge>
                  <span className="min-w-0 truncate text-foreground" title={e.summary}>
                    {e.link ? (
                      <a href={e.link} target="_blank" rel="noreferrer" className="hover:underline">
                        {e.summary}
                      </a>
                    ) : (
                      e.summary
                    )}
                    {e.count > 1 ? <span className="text-muted-foreground"> · {e.count}</span> : null}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="rounded-lg border border-border bg-card" aria-labelledby="security-sources">
        <h2 id="security-sources" className="border-b border-border px-4 py-2 text-sm font-semibold">
          Źródła
        </h2>
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr className="border-b border-border">
                <th className="sticky left-0 bg-card px-4 py-1.5 font-medium">Źródło</th>
                <th className="px-4 py-1.5 font-medium">Ostatnio</th>
                <th className="px-4 py-1.5 font-medium">Stan</th>
                <th className="px-4 py-1.5 font-medium">Gdzie</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.sources.map((s) => (
                <tr key={s.key}>
                  <td className="sticky left-0 bg-card px-4 py-1.5 text-foreground">{s.name}</td>
                  <td className="px-4 py-1.5 text-muted-foreground">{s.last_at ? formatMomentPl(s.last_at) : formatIsoDatePl(s.last_on)}</td>
                  <td className="px-4 py-1.5">
                    <Badge variant={TONE_BADGE[SOURCE_STATE_TONE[s.state]]}>{s.state_label}</Badge>
                    {s.detail ? <span className="ml-2 text-xs text-muted-foreground">{s.detail}</span> : null}
                  </td>
                  <td className="px-4 py-1.5 text-muted-foreground">
                    {s.link ? (
                      <a href={s.link} target="_blank" rel="noreferrer" className="hover:underline">
                        {s.where}
                      </a>
                    ) : (
                      s.where
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <SecurityFindingSheet
        finding={selected}
        owners={data.owners}
        today={data.today}
        onClose={() => setSelectedId(null)}
      />
    </div>
  );
}
