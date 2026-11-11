"use client";

import { AlertTriangle, ArrowDown, Info, Lightbulb, PhoneCall } from "lucide-react";
import { useState, type ReactNode } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { CALL_OUTCOME_LABELS, type CallOutcome } from "@/lib/api/sales";
import {
  useCallingEffectiveness,
  type CampaignStats,
  type Effectiveness,
  type EffectivenessPeriod,
  type HourCell,
  type Insight,
  type PersonStats,
} from "@/lib/api/sales-calling-stats";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

// Sprzedaż → Dzwonienie → Skuteczność (decyzje Artura 11.11.2026,
// docs/claude/sprzedaz/dzwonienie-skutecznosc.md): lejek, kampanie, listy, pory dnia
// i ranking osób z sortowaniem. Kolejka dalej nie ma rankingu ani celu dziennego.

type Tone = "primary" | "success" | "muted" | "warning" | "danger" | "info";

const TONE_BAR: Record<Tone, string> = {
  primary: "bg-primary",
  success: "bg-success",
  muted: "bg-muted-foreground/30",
  warning: "bg-warning",
  danger: "bg-destructive",
  info: "bg-info",
};

const OUTCOME_TONES: Record<string, Tone> = {
  no_answer: "muted",
  connected: "primary",
  call_back: "primary",
  wants_offer: "info",
  offer_sent: "info",
  meeting_booked: "success",
  not_now: "warning",
  do_not_contact: "danger",
};

/** Dzisiejszy stan rekordów, którym w okresie wysłano ofertę ogólną. */
const FOLLOWUP: { key: string; label: string; tone: Tone }[] = [
  { key: "offer_sent", label: "Czeka na oddzwonienie", tone: "muted" },
  { key: "meeting_booked", label: "Spotkanie po ofercie", tone: "success" },
  { key: "call_back", label: "Oddzwonić", tone: "primary" },
  { key: "not_now", label: "Nie teraz", tone: "warning" },
  { key: "no_answer", label: "Nie odbiera po ofercie", tone: "info" },
  { key: "do_not_contact", label: "Nie kontaktować", tone: "danger" },
];

const DAYS = ["Pon", "Wt", "Śr", "Czw", "Pt"];

const PERIOD_OPTIONS: { value: EffectivenessPeriod; label: string }[] = [
  { value: "week", label: "Ten tydzień" },
  { value: "4w", label: "4 tygodnie" },
  { value: "all", label: "Od początku" },
];

export function percent(part: number, whole: number | null | undefined): string {
  return whole ? `${Math.round((100 * part) / whole)}%` : "—";
}

function shortDate(iso: string): string {
  const [, month, day] = iso.split("-");
  return `${day}.${month}`;
}

function Panel({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      aria-label={title}
      className="min-w-0 overflow-x-auto rounded-lg border border-border bg-card p-3"
    >
      <header className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {aside && <span className="text-right text-xs text-muted-foreground">{aside}</span>}
      </header>
      {children}
    </section>
  );
}

function Thin({ children }: { children: ReactNode }) {
  return <p className="py-2 text-xs text-muted-foreground">{children}</p>;
}

interface FunnelStep {
  key: string;
  label: string;
  value: number;
  hint: string;
  warn?: boolean;
}

export function funnelSteps(data: Effectiveness): FunnelStep[] {
  const f = data.funnel;
  return [
    {
      key: "calls",
      label: "Telefony",
      value: f.calls,
      hint: data.workdays ? `${Math.round(f.calls / data.workdays)} dziennie` : "—",
    },
    { key: "talks", label: "Rozmowy", value: f.talks, hint: `${percent(f.talks, f.calls)} telefonów` },
    { key: "offers", label: "Oferta ogólna", value: f.offers, hint: `${percent(f.offers, f.talks)} rozmów` },
    {
      key: "meetings",
      label: "Umówione spotkania",
      value: f.meetings,
      hint: `${percent(f.meetings, f.talks)} rozmów`,
    },
    {
      key: "dated",
      label: "Z terminem w NEXUSIE",
      value: f.dated,
      hint: `${f.dated} z ${f.meetings}`,
      warn: f.meetings > 0 && f.dated < f.meetings,
    },
    {
      key: "qualified",
      label: "Werdykt „Warto”",
      value: f.qualified,
      hint: f.held ? `${f.qualified} z ${f.held} odbytych` : "po pierwszych spotkaniach",
    },
  ];
}

function FunnelStrip({ data }: { data: Effectiveness }) {
  const steps = funnelSteps(data);
  return (
    <ol
      aria-label="Lejek dzwonienia"
      className="grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-border bg-border lg:grid-cols-6"
    >
      {steps.map((step, index) => (
        <li key={step.key} className="relative bg-card px-3 py-2">
          <p className="text-xs text-muted-foreground">{step.label}</p>
          <p
            className={cn(
              "text-xl font-semibold tabular-nums",
              step.warn ? "text-warning-muted-foreground" : "text-foreground",
            )}
          >
            {step.value}
          </p>
          <p className="truncate text-xs text-muted-foreground">{step.hint}</p>
          {index < steps.length - 1 && (
            <span
              aria-hidden
              className="absolute right-1 top-1/2 hidden -translate-y-1/2 text-muted-foreground/50 lg:block"
            >
              ›
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}

const INSIGHT_ICONS = { info: Info, warning: AlertTriangle, success: Lightbulb };

function InsightList({ items }: { items: Insight[] }) {
  if (items.length === 0) return <Thin>Na razie bez wniosków: za mało rozmów, żeby coś porównać.</Thin>;
  return (
    <ul className="space-y-1.5">
      {items.map((item) => {
        const Icon = INSIGHT_ICONS[item.tone] ?? Info;
        return (
          <li key={item.text} className="flex gap-2 text-xs leading-snug text-foreground">
            <Icon
              aria-hidden
              className={cn(
                "mt-0.5 h-3.5 w-3.5 shrink-0",
                item.tone === "warning" ? "text-warning" : item.tone === "success" ? "text-success" : "text-info",
              )}
            />
            <span>{item.text}</span>
          </li>
        );
      })}
    </ul>
  );
}

interface Slice {
  key: string;
  label: string;
  value: number;
  tone: Tone;
}

function SliceBar({ slices, label }: { slices: Slice[]; label: string }) {
  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  if (!total) return <Thin>Brak danych w tym okresie.</Thin>;
  return (
    <div className="space-y-2">
      <div className="flex h-3 overflow-hidden rounded-full bg-muted" role="img" aria-label={label}>
        {slices.map((slice) => (
          <span
            key={slice.key}
            className={TONE_BAR[slice.tone]}
            style={{ width: `${(slice.value / total) * 100}%` }}
          />
        ))}
      </div>
      <ul className="grid gap-y-0.5 text-xs">
        {slices.map((slice) => (
          <li key={slice.key} className="flex items-center gap-1.5">
            <span aria-hidden className={cn("h-2 w-2 shrink-0 rounded-sm", TONE_BAR[slice.tone])} />
            <span className="min-w-0 flex-1 truncate text-muted-foreground">{slice.label}</span>
            <span className="tabular-nums text-foreground">{slice.value}</span>
            <span className="w-9 text-right tabular-nums text-muted-foreground">{percent(slice.value, total)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Th({ children, right }: { children: ReactNode; right?: boolean }) {
  return (
    <th
      scope="col"
      className={cn("whitespace-nowrap px-1.5 py-1 font-medium text-muted-foreground", right ? "text-right" : "text-left")}
    >
      {children}
    </th>
  );
}

function Td({ children, right, strong }: { children: ReactNode; right?: boolean; strong?: boolean }) {
  return (
    <td
      className={cn(
        "px-1.5 py-1",
        right && "text-right tabular-nums",
        strong ? "font-medium text-foreground" : "text-muted-foreground",
      )}
    >
      {children}
    </td>
  );
}

function CampaignTable({ rows }: { rows: CampaignStats[] }) {
  if (rows.length === 0) return <Thin>Nie ma jeszcze kampanii. Załóż ją w kolejce („Kampanie”).</Thin>;
  return (
    <table className="w-full text-xs">
      <thead className="border-b border-border">
        <tr>
          <Th>Kampania</Th>
          <Th right>Lista</Th>
          <Th right>Nowe</Th>
          <Th right>Starczy na</Th>
          <Th right>Rozmowy</Th>
          <Th right>Spotkania</Th>
          <Th right>Spotk./rozm.</Th>
          <Th right>Tel./spotk.</Th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {rows.map((row) => (
          <tr key={row.id ?? "none"}>
            <Td strong>
              <span className="block truncate">{row.name}</span>
              {row.service && (
                <span className="block text-[11px] font-normal text-muted-foreground">{row.service}</span>
              )}
            </Td>
            <Td right>{row.on_list ?? "—"}</Td>
            <Td right>{row.left ?? "—"}</Td>
            <Td right>{row.days_left === null ? "—" : `ok. ${row.days_left} dni`}</Td>
            <Td right>{row.talks}</Td>
            <Td right strong>
              {row.meetings}
            </Td>
            <Td right>{percent(row.meetings, row.talks)}</Td>
            <Td right>{row.meetings ? Math.round(row.calls / row.meetings) : "—"}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SourceTable({ data }: { data: Effectiveness }) {
  if (data.sources.length === 0) return <Thin>Brak telefonów w tym okresie.</Thin>;
  return (
    <table className="w-full text-xs">
      <thead className="border-b border-border">
        <tr>
          <Th>Skąd kontakt</Th>
          <Th right>Rekordy</Th>
          <Th right>Odbiera</Th>
          <Th right>Spotk./rozm.</Th>
          <Th right>Nie kontaktować</Th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {data.sources.map((row) => (
          <tr key={row.source}>
            <Td strong>{row.source}</Td>
            <Td right>{row.records}</Td>
            <Td right>{percent(row.reached, row.records)}</Td>
            <Td right strong>
              {percent(row.meetings, row.talks)}
            </Td>
            <Td right>{row.objections}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ReachHeatmap({ cells }: { cells: HourCell[] }) {
  if (!cells.some((cell) => cell.rate !== null)) {
    return <Thin>Za mało telefonów, żeby pokazać pory dnia (potrzeba co najmniej 5 w danej godzinie).</Thin>;
  }
  const hours = Array.from(new Set(cells.map((cell) => cell.hour))).sort((a, b) => a - b);
  const at = new Map(cells.map((cell) => [`${cell.weekday}:${cell.hour}`, cell]));
  return (
    <div>
      <table className="w-full border-separate border-spacing-0.5 text-[11px]">
        <thead>
          <tr>
            <th className="w-8" />
            {hours.map((hour) => (
              <th key={hour} scope="col" className="font-normal text-muted-foreground">
                {hour}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {DAYS.map((day, weekday) => (
            <tr key={day}>
              <th scope="row" className="pr-1 text-left font-normal text-muted-foreground">
                {day}
              </th>
              {hours.map((hour) => {
                const cell = at.get(`${weekday}:${hour}`);
                const rate = cell?.rate ?? null;
                return (
                  <td
                    key={hour}
                    title={
                      rate === null
                        ? `${day} ${hour}:00 — ${cell?.calls ?? 0} tel., za mało`
                        : `${day} ${hour}:00 — rozmowa w ${Math.round(rate * 100)}% z ${cell?.calls} tel.`
                    }
                    className="rounded-sm p-0 text-center tabular-nums"
                    style={{
                      height: 18,
                      backgroundColor:
                        rate === null
                          ? "hsl(var(--muted))"
                          : `hsl(var(--primary) / ${Math.max(0.08, Math.min(1, rate * 1.4)).toFixed(2)})`,
                      color:
                        rate !== null && rate >= 0.45
                          ? "hsl(var(--primary-foreground))"
                          : "hsl(var(--foreground))",
                    }}
                  >
                    {rate === null ? "" : Math.round(rate * 100)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-[11px] leading-snug text-muted-foreground">
        % telefonów zakończonych rozmową. Puste pole: mniej niż 5 telefonów.
      </p>
    </div>
  );
}

export type SortKey = "calls" | "perDay" | "talks" | "offers" | "meetings" | "meetingRate" | "dated" | "qualified";

const SORT_VALUE: Record<SortKey, (p: PersonStats) => number> = {
  calls: (p) => p.calls,
  perDay: (p) => (p.days ? p.calls / p.days : 0),
  talks: (p) => p.talks,
  offers: (p) => p.offers,
  meetings: (p) => p.meetings,
  meetingRate: (p) => (p.talks ? p.meetings / p.talks : 0),
  dated: (p) => p.dated,
  qualified: (p) => p.qualified,
};

const PEOPLE_COLUMNS: { key: SortKey; label: string }[] = [
  { key: "calls", label: "Telefony" },
  { key: "perDay", label: "Tel./dzień" },
  { key: "talks", label: "Rozmowy" },
  { key: "offers", label: "Oferty" },
  { key: "meetings", label: "Spotkania" },
  { key: "meetingRate", label: "Spotk./rozm." },
  { key: "dated", label: "Z terminem" },
  { key: "qualified", label: "„Warto”" },
];

/** Kolejność rankingu: malejąco po wybranej kolumnie, remis alfabetycznie. */
export function rankPeople(people: PersonStats[], key: SortKey): PersonStats[] {
  return [...people].sort(
    (a, b) => SORT_VALUE[key](b) - SORT_VALUE[key](a) || a.name.localeCompare(b.name, "pl"),
  );
}

/** Ranking osób (decyzja Artura 11.11.2026): sortowanie po kliknięciu w nagłówek. */
function PeopleRanking({ people }: { people: PersonStats[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("meetings");
  if (people.length === 0) return <Thin>Brak telefonów w tym okresie.</Thin>;
  const ranked = rankPeople(people, sortKey);
  return (
    <table className="w-full text-xs">
      <thead className="border-b border-border">
        <tr>
          <Th>#</Th>
          <Th>Osoba</Th>
          {PEOPLE_COLUMNS.map((column) => (
            <th
              key={column.key}
              scope="col"
              aria-sort={sortKey === column.key ? "descending" : undefined}
              className="whitespace-nowrap px-1 py-1 text-right font-medium text-muted-foreground"
            >
              <button
                type="button"
                className={cn(
                  "inline-flex items-center gap-0.5 rounded px-1 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  sortKey === column.key && "text-foreground",
                )}
                onClick={() => setSortKey(column.key)}
              >
                {column.label}
                {sortKey === column.key && <ArrowDown aria-hidden className="h-3 w-3" />}
              </button>
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {ranked.map((row, index) => (
          <tr key={row.user_id}>
            <Td>{index + 1}.</Td>
            <Td strong>
              <span className="block whitespace-nowrap">{row.name}</span>
              <span className="block text-[11px] font-normal text-muted-foreground">
                {row.days} {row.days === 1 ? "dzień" : "dni"} dzwonienia
              </span>
            </Td>
            <Td right>{row.calls}</Td>
            <Td right>{row.days ? Math.round(row.calls / row.days) : "—"}</Td>
            <Td right>{row.talks}</Td>
            <Td right>{row.offers}</Td>
            <Td right strong>
              {row.meetings}
            </Td>
            <Td right>{percent(row.meetings, row.talks)}</Td>
            <Td right>
              <span className={row.dated < row.meetings ? "text-warning-muted-foreground" : undefined}>
                {row.dated} z {row.meetings}
              </span>
            </Td>
            <Td right>{row.qualified}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function outcomeSlices(data: Effectiveness): Slice[] {
  return Object.entries(data.outcomes)
    .map(([key, value]) => ({
      key,
      value,
      label: CALL_OUTCOME_LABELS[key as CallOutcome] ?? key,
      tone: OUTCOME_TONES[key] ?? "muted",
    }))
    .sort((a, b) => b.value - a.value);
}

function followupSlices(data: Effectiveness): Slice[] {
  return FOLLOWUP.filter((item) => data.offer_followup[item.key]).map((item) => ({
    ...item,
    value: data.offer_followup[item.key],
  }));
}

function Board({ data }: { data: Effectiveness }) {
  const offered = Object.values(data.offer_followup).reduce((sum, n) => sum + n, 0);
  return (
    <>
      <FunnelStrip data={data} />
      {data.funnel.calls === 0 ? (
        <div className="rounded-lg border border-border bg-card">
          <EmptyState
            icon={PhoneCall}
            title="W tym okresie nie ma zapisanych telefonów."
            description="Każdy wynik kliknięty w kolejce trafia tu sam: kampania, lista, godzina i osoba."
          />
        </div>
      ) : (
        <>
          <div className="grid gap-2 lg:grid-cols-[1.6fr_1fr]">
            <Panel title="Kampanie" aside="lista dziś · reszta z okresu">
              <CampaignTable rows={data.campaigns} />
            </Panel>
            <Panel title="Wnioski" aside="liczone regułami">
              <InsightList items={data.insights} />
            </Panel>
          </div>
          {/* Ranking i listy na pełną szerokość: przy 1280 px w pół ekranu ucinały kolumny. */}
          <Panel title="Ranking osób" aside="kliknij nagłówek, żeby sortować">
            <PeopleRanking people={data.people} />
          </Panel>
          <div className="grid gap-2 lg:grid-cols-3">
            <Panel title="Jak kończą się telefony" aside={`${data.funnel.calls} telefonów`}>
              <SliceBar slices={outcomeSlices(data)} label="Wyniki telefonów" />
            </Panel>
            <Panel title="Kiedy odbierają">
              <ReachHeatmap cells={data.hours} />
            </Panel>
            <Panel title="Oferta ogólna → co dalej" aside={`${offered} z okresu, stan dziś`}>
              <SliceBar slices={followupSlices(data)} label="Co dalej z ofertą ogólną" />
            </Panel>
          </div>
          <Panel title="Które listy działają">
            <SourceTable data={data} />
          </Panel>
        </>
      )}
    </>
  );
}

/** Dzwonienie → Skuteczność: co daje dzwonienie w wybranym okresie. */
export function EffectivenessView() {
  const [period, setPeriod] = useState<EffectivenessPeriod>("week");
  const [mine, setMine] = useState(false);
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const query = useCallingEffectiveness({ period, campaignId, mine });
  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: false,
  });

  const data = query.data;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <p className="min-w-0 text-muted-foreground">
          {data ? (
            <>
              <span className="font-medium text-foreground">
                {shortDate(data.start)}–{shortDate(data.end)}
              </span>{" "}
              · {data.workdays} {data.workdays === 1 ? "dzień roboczy" : "dni robocze"}
            </>
          ) : (
            "Skuteczność dzwonienia"
          )}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {data && data.campaign_options.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Kampania">
              {data.campaign_options.map((campaign) => (
                <Button
                  key={campaign.id}
                  size="sm"
                  variant={campaignId === campaign.id ? "primary" : "outline"}
                  className="h-7 px-2"
                  aria-pressed={campaignId === campaign.id}
                  onClick={() => setCampaignId(campaignId === campaign.id ? null : campaign.id)}
                >
                  {campaign.name}
                </Button>
              ))}
            </div>
          )}
          <SegmentedRadio label="Okres" size="sm" value={period} onChange={setPeriod} options={PERIOD_OPTIONS} />
          <SegmentedRadio
            label="Zakres"
            size="sm"
            value={mine ? "mine" : "team"}
            onChange={(value) => setMine(value === "mine")}
            options={[
              { value: "mine", label: "Moje" },
              { value: "team", label: "Zespół" },
            ]}
          />
        </div>
      </div>
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Liczenie skuteczności…</p>
      ) : state !== "ready" || !data ? (
        <QueryStateNotice
          state={state === "ready" || state === "empty" ? "error" : state}
          onRetry={() => void query.refetch()}
        />
      ) : (
        <Board data={data} />
      )}
    </div>
  );
}
