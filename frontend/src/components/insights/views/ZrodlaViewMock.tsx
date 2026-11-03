"use client";

/**
 * MAKIETA (03.11.2026), tylko lokalnie: zakładka „Źródła”. Liczby i osoby to
 * wynik zapytań read-only na bazie stagingu. Wstrzykuje je skrypt zrzutów
 * przez `window.__SOURCES_MOCK`, żeby nazwiska nie trafiły do repo.
 */

import { Fragment, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, Download } from "lucide-react";

import { DetailPanel } from "@/components/ds/DetailPanel";
import { PeriodPicker } from "@/components/insights/PeriodPicker";
import { InsightsInviteLinks } from "@/components/insights/sections/InsightsInviteLinks";
import { InsightsLinkPeople } from "@/components/insights/sections/InsightsLinkPeople";
import { useInsightsPeriod } from "@/components/insights/useInsightsPeriod";
import { Button } from "@/components/ui/button";
import type { InsightsPeriodParams } from "@/lib/insights-api";
import { cn } from "@/lib/utils";
import { hasRole, useAuthStore } from "@/store/auth";
import { ViewHeader } from "./ViewKit";

type Metric = "people" | "applications" | "fresh" | "inProcess" | "verified" | "cvSent" | "hired";
type Counts = Record<Metric, number>;
type OfferRow = Counts & { offer: string };

interface Person {
  id: number;
  name: string;
  offer?: string;
  n?: number;
  date: string;
  stage: string | null;
  job: string | null;
}

interface LinkApplication {
  src: "general" | "job";
  id: number;
  name: string;
  owner: string;
  job: string | null;
  date: string;
  nowi: boolean;
  stage: string | null;
}

interface MockWindow {
  sources: Record<string, Counts>;
  total: Counts;
  offers: Record<string, OfferRow[]>;
  offersTotal: Record<string, number>;
}

interface MockData {
  w30: MockWindow;
  custom: MockWindow;
  people: Record<string, Partial<Record<Metric, Person[]>>>;
  peopleByOffer: Record<string, Record<string, Partial<Record<Metric, Person[]>>>>;
  links: LinkApplication[];
}

interface Selection {
  key: string;
  title: string;
  metric: Metric;
  total: number;
  people: Person[];
}

const COLUMNS: { key: Metric; label: string; means: string }[] = [
  { key: "people", label: "Osoby", means: "Każda osoba, która w tym okresie zgłosiła się z tego źródła." },
  { key: "applications", label: "Zgłoszenia", means: "Osoby ze zgłoszeniami w okresie. Jedna osoba może mieć kilka zgłoszeń." },
  { key: "fresh", label: "Nowi w bazie", means: "Osoby, których przed tym zgłoszeniem nie było w NEXUSIE." },
  { key: "inProcess", label: "W rekrutacji", means: "Osoby z ruchem na Tablicy po zgłoszeniu, poza etapem „Z ogłoszenia”." },
  { key: "verified", label: "Zweryfikowani", means: "Osoby, które po zgłoszeniu doszły do etapu „Zweryfikowany”." },
  { key: "cvSent", label: "CV wysłane", means: "Osoby, których CV po zgłoszeniu poszło do klienta." },
  { key: "hired", label: "Zatrudnieni", means: "Osoby zatrudnione po zgłoszeniu." },
];

const PORTALS = [
  { key: "pracuj", label: "Pracuj.pl" },
  { key: "jjit", label: "JustJoin.IT" },
  { key: "rocketjobs", label: "RocketJobs" },
];

const STAGE_LABEL: Record<string, string> = {
  new: "Nowi",
  screening: "Screening",
  prep_call: "Prep",
  verified: "Zweryfikowany",
  cv_sent: "CV wysłane",
  interview: "Zweryfikowany",
  client_interview: "Rozmowa u klienta",
  acceptance: "Akceptacja",
  hired: "Zatrudniony",
  rejected: "Odrzucony",
  withdrawn: "Zrezygnował",
};

const DEFAULT_PERIOD: InsightsPeriodParams = {
  period: "custom",
  date_from: "2026-10-12",
  date_to: "2026-11-02",
};

const fmt = (value: number): string => value.toLocaleString("pl-PL");

function linkCounts(apps: LinkApplication[]): Counts {
  return {
    people: new Set(apps.map((a) => a.id)).size,
    applications: apps.length,
    fresh: apps.filter((a) => a.nowi).length,
    inProcess: apps.filter((a) => a.stage && a.stage !== "new").length + apps.filter((a) => a.stage === "new").length,
    verified: 0,
    cvSent: 0,
    hired: 0,
  };
}

function linkPeople(apps: LinkApplication[], metric: Metric): Person[] {
  const pick = apps.filter((a) => (metric === "fresh" ? a.nowi : metric === "inProcess" ? Boolean(a.stage) : true));
  return pick.map((a) => ({ id: a.id, name: a.name, date: a.date, stage: a.stage, job: a.job, offer: a.job ?? `Link: ${a.owner}` }));
}

function Numbers({
  counts,
  rowKey,
  active,
  onPick,
  total = false,
  barMax,
}: {
  counts: Counts;
  rowKey: string;
  active: string | null;
  onPick?: (metric: Metric) => void;
  total?: boolean;
  barMax?: number;
}) {
  return (
    <>
      {COLUMNS.map((column) => {
        const value = counts[column.key];
        const clickable = Boolean(onPick) && value > 0;
        const isActive = active === `${rowKey}:${column.key}`;
        return (
          <td key={column.key} className="px-2 py-1 text-right tabular-nums">
            <div className="flex items-center justify-end gap-2">
              {clickable ? (
                <button
                  type="button"
                  onClick={() => onPick?.(column.key)}
                  aria-label={`${column.label}: ${fmt(value)}, pokaż osoby`}
                  data-cell={`${rowKey}:${column.key}`}
                  className={cn(
                    "rounded px-1.5 py-0.5 tabular-nums text-foreground underline decoration-dotted decoration-muted-foreground/50 underline-offset-2 hover:bg-primary/10 hover:text-primary",
                    (total || column.key === "people") && "font-semibold",
                    isActive && "bg-primary text-primary-foreground no-underline hover:bg-primary hover:text-primary-foreground",
                  )}
                >
                  {fmt(value)}
                </button>
              ) : (
                <span className={cn("px-1.5 py-0.5", value === 0 ? "text-muted-foreground" : "text-foreground", total && "font-semibold")}>
                  {fmt(value)}
                </span>
              )}
              {column.key === "people" && barMax ? (
                <span className="h-1.5 w-12 overflow-hidden rounded-full bg-muted">
                  <span className="block h-full bg-primary" style={{ width: `${Math.max((value / barMax) * 100, value > 0 ? 3 : 0)}%` }} />
                </span>
              ) : column.key === "people" ? (
                <span className="w-12" />
              ) : null}
            </div>
          </td>
        );
      })}
    </>
  );
}

function PeopleTable({ selection }: { selection: Selection }) {
  const column = COLUMNS.find((c) => c.key === selection.metric)!;
  return (
    <div className="grid gap-2">
      <p className="text-xs text-muted-foreground">{column.means}</p>
      <table className="w-full table-fixed text-xs">
        <thead className="text-muted-foreground">
          <tr>
            <th className="w-[27%] py-1.5 pr-2 text-left font-medium">Osoba</th>
            <th className="w-[14%] py-1.5 pr-2 text-left font-medium">Zgłoszenie</th>
            <th className="py-1.5 pr-2 text-left font-medium">Ogłoszenie albo link</th>
            <th className="w-[33%] py-1.5 text-left font-medium">Najdalszy etap</th>
          </tr>
        </thead>
        <tbody>
          {selection.people.map((person) => (
            <tr key={`${person.id}-${person.offer ?? ""}`} className="border-t border-border align-top">
              <td className="py-1.5 pr-2">
                <Link href={`/candidates/${person.id}`} className="font-medium text-primary hover:underline">
                  {person.name}
                </Link>
              </td>
              <td className="py-1.5 pr-2 tabular-nums text-muted-foreground">{person.date}</td>
              <td className="truncate py-1.5 pr-2 text-muted-foreground" title={person.offer}>
                {person.offer ?? "—"}
              </td>
              <td className="py-1.5">
                <span className="font-medium text-foreground">
                  {person.stage ? (STAGE_LABEL[person.stage] ?? person.stage) : "Tylko w bazie"}
                </span>
                {person.job ? (
                  <span className="block truncate text-muted-foreground" title={person.job}>
                    {person.job}
                  </span>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PeopleFooter({ selection }: { selection: Selection }) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
      <span>
        Pokazano {fmt(selection.people.length)} z {fmt(selection.total)}
      </span>
      <div className="flex items-center gap-2">
        {selection.people.length < selection.total && (
          <Button type="button" variant="outline" size="sm">
            Pokaż więcej
          </Button>
        )}
        <Button type="button" variant="outline" size="sm">
          <Download className="h-3.5 w-3.5" />
          Eksportuj
        </Button>
      </div>
    </div>
  );
}

export function ZrodlaViewMock() {
  const [data, setData] = useState<MockData | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [selection, setSelection] = useState<Selection | null>(null);
  const [inline, setInline] = useState(false);
  const { period, setPeriod } = useInsightsPeriod(DEFAULT_PERIOD);
  // Wyniki po osobach: te same role co „Kto co przyniósł”.
  const user = useAuthStore((s) => s.user);
  const seesOwners = hasRole(user, "admin", "head_of_recruitment", "delivery_lead");

  useEffect(() => {
    setData((window as unknown as { __SOURCES_MOCK?: MockData }).__SOURCES_MOCK ?? null);
    setInline(new URLSearchParams(window.location.search).get("osoby") === "wiersz");
  }, []);

  const from = period.date_from ?? "2026-10-12";
  const to = period.date_to ?? "2026-11-02";
  const isDefaultWindow = from === DEFAULT_PERIOD.date_from && to === DEFAULT_PERIOD.date_to;
  const resolved = useMemo(() => {
    const end = new Date(`${to}T12:00:00Z`);
    end.setUTCDate(end.getUTCDate() + 1);
    return {
      start: `${from}T12:00:00Z`,
      end: end.toISOString(),
      timezone: "Europe/Warsaw",
      kind: "custom" as const,
    };
  }, [from, to]);

  if (!data) {
    return <p className="text-sm text-muted-foreground">Makieta czeka na dane ze skryptu zrzutów.</p>;
  }

  const win = isDefaultWindow ? data.w30 : data.custom;
  const links = isDefaultWindow ? data.links : [];
  const general = links.filter((a) => a.src === "general");
  const job = links.filter((a) => a.src === "job");
  const careerTotal = linkCounts(links);
  const maxPeople = win.sources.pracuj.people;
  const per100 = (key: string): string =>
    ((win.sources[key].cvSent / win.sources[key].people) * 100).toLocaleString("pl-PL", { maximumFractionDigits: 1, minimumFractionDigits: 1 });

  const toggle = (key: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const pick = (key: string, title: string, total: number, people: Person[], metric: Metric) =>
    setSelection({ key: `${key}:${metric}`, title, metric, total, people });

  const metricLabel = (metric: Metric) => COLUMNS.find((c) => c.key === metric)!.label;
  const activeCell = selection?.key ?? null;

  const inlineRow = (rowKey: string) =>
    inline && selection?.key.startsWith(`${rowKey}:`) ? (
      <tr className="border-t border-border bg-muted/20">
        <td colSpan={COLUMNS.length + 1} className="px-4 py-3">
          <p className="mb-1 text-sm font-semibold text-foreground">
            {selection.title} · {metricLabel(selection.metric)}: {fmt(selection.total)}
          </p>
          <div className="max-h-64 overflow-y-auto">
            <PeopleTable selection={selection} />
          </div>
          <div className="mt-2">
            <PeopleFooter selection={selection} />
          </div>
        </td>
      </tr>
    ) : null;

  const nameCell = (key: string, label: string, expandable: boolean) => (
    <td className="px-4 py-1 font-medium text-foreground">
      {expandable ? (
        <button type="button" onClick={() => toggle(key)} aria-expanded={open.has(key)} className="inline-flex items-center gap-1 font-medium hover:text-primary">
          {open.has(key) ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
          {label}
        </button>
      ) : (
        label
      )}
    </td>
  );

  const groupHeader = (label: string) => (
    <tr className="border-t border-border">
      <td colSpan={COLUMNS.length + 1} className="px-4 pb-0.5 pt-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </td>
    </tr>
  );

  const groupByOwner = (apps: LinkApplication[], parent: string, parentLabel: string, byJob: boolean) => {
    const groups = new Map<string, LinkApplication[]>();
    apps.forEach((a) => {
      const k = byJob ? (a.job ?? a.owner) : a.owner;
      groups.set(k, [...(groups.get(k) ?? []), a]);
    });
    return [...groups.entries()].map(([label, rows]) => {
      const rowKey = `${parent}/${label}`;
      return (
        <Fragment key={rowKey}>
          <tr className="border-t border-border bg-muted/20 text-xs">
            <td className="truncate py-1 pl-9 pr-2 text-foreground" title={label}>
              {label}
            </td>
            <Numbers
              counts={linkCounts(rows)}
              rowKey={rowKey}
              active={activeCell}
              onPick={(metric) => pick(rowKey, `${parentLabel} · ${label}`, linkCounts(rows)[metric], linkPeople(rows, metric), metric)}
            />
          </tr>
          {inlineRow(rowKey)}
        </Fragment>
      );
    });
  };

  const linkRow = (key: string, label: string, apps: LinkApplication[], byJob: boolean) => {
    const counts = linkCounts(apps);
    return (
      <Fragment key={key}>
        <tr className="border-t border-border hover:bg-muted/30">
          {nameCell(key, label, apps.length > 0 && (byJob || seesOwners))}
          <Numbers
            counts={counts}
            rowKey={key}
            active={activeCell}
            barMax={maxPeople}
            onPick={(metric) => pick(key, label, counts[metric], linkPeople(apps, metric), metric)}
          />
        </tr>
        {inlineRow(key)}
        {open.has(key) && groupByOwner(apps, key, label, byJob)}
      </Fragment>
    );
  };

  return (
    <div className={cn("space-y-6", selection && !inline && "lg:pr-[0px]")}>
      <div className="grid gap-3">
        <ViewHeader
          question="Skąd przychodzą kandydaci?"
          lede={
            <span className="block max-w-none">
              Portale dały {fmt(win.total.people)} osób, strona kariery {fmt(careerTotal.people)}. Na 100 osób z Pracuj.pl do wysłanego CV dochodzi {per100("pracuj")}, z JustJoin.IT {per100("jjit")}, z RocketJobs {per100("rocketjobs")}.
            </span>
          }
        />
        <div className="flex justify-end">
          <PeriodPicker value={period} onChange={setPeriod} resolved={resolved} defaultValue={DEFAULT_PERIOD} />
        </div>
      </div>

      <section className="overflow-hidden rounded-xl border border-border bg-card shadow-xs" data-testid="sources-table">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-sm">
            <thead className="bg-muted/50 text-xs text-muted-foreground">
              <tr>
                <th className="w-[230px] px-4 py-2 text-left font-medium">Źródło</th>
                {COLUMNS.map((column) => (
                  <th key={column.key} className="px-3 py-2 text-right font-medium" title={column.means}>
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {groupHeader("Portale")}
              {PORTALS.map((portal) => {
                const counts = win.sources[portal.key];
                const offers = win.offers[portal.key] ?? [];
                return (
                  <Fragment key={portal.key}>
                    <tr className="border-t border-border hover:bg-muted/30">
                      {nameCell(portal.key, portal.label, true)}
                      <Numbers
                        counts={counts}
                        rowKey={portal.key}
                        active={activeCell}
                        barMax={maxPeople}
                        onPick={(metric) =>
                          pick(portal.key, portal.label, counts[metric], data.people[portal.key]?.[metric === "applications" ? "people" : metric] ?? [], metric)
                        }
                      />
                    </tr>
                    {inlineRow(portal.key)}
                    {open.has(portal.key) && (
                      <>
                        {offers.map((row) => {
                          const rowKey = `${portal.key}/${row.offer}`;
                          return (
                            <Fragment key={rowKey}>
                              <tr className="border-t border-border bg-muted/20 text-xs">
                                <td className="max-w-[230px] truncate py-1 pl-9 pr-2 text-foreground" title={row.offer}>
                                  {row.offer}
                                </td>
                                <Numbers
                                  counts={row}
                                  rowKey={rowKey}
                                  active={activeCell}
                                  onPick={(metric) =>
                                    pick(
                                      rowKey,
                                      `${portal.label} · ${row.offer}`,
                                      row[metric],
                                      data.peopleByOffer[portal.key]?.[row.offer]?.[metric === "applications" ? "people" : metric] ?? [],
                                      metric,
                                    )
                                  }
                                />
                              </tr>
                              {inlineRow(rowKey)}
                            </Fragment>
                          );
                        })}
                        <tr className="border-t border-border bg-muted/20 text-xs">
                          <td colSpan={COLUMNS.length + 1} className="py-1.5 pl-9 text-primary">
                            Pokaż wszystkie ogłoszenia ({fmt(win.offersTotal[portal.key] ?? 0)})
                          </td>
                        </tr>
                      </>
                    )}
                  </Fragment>
                );
              })}
              <tr className="border-t border-border bg-muted/30">
                <td className="px-4 py-1 font-semibold text-foreground">Razem portale</td>
                <Numbers counts={win.total} rowKey="portale" active={activeCell} total />
              </tr>
              {groupHeader("Strona kariery")}
              {linkRow("general", "Link ogólny rekrutera", general, false)}
              {linkRow("job", "Linki do rekrutacji", job, true)}
              <tr className="border-t border-border bg-muted/30">
                <td className="px-4 py-1 font-semibold text-foreground">Razem strona kariery</td>
                <Numbers counts={careerTotal} rowKey="kariera" active={activeCell} total />
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid gap-1 text-xs text-muted-foreground">
        <p>Podkreślona liczba otwiera listę osób. Klik w źródło pokazuje ogłoszenia albo rekruterów. „Razem” liczy osobę raz, więc nie jest sumą wierszy.</p>
        <p>
          Nowi kandydaci bez rozpoznanego źródła: 109 z 2558 (4%). Stan scraperów i błędy importu:{" "}
          <Link href="/insights?tab=raporty&report=doplyw" className="text-primary hover:underline">
            Raporty → Integracje
          </Link>
          .
        </p>
        <details>
          <summary className="cursor-pointer">Jak liczymy?</summary>
          <p className="mt-1 max-w-3xl">
            Dni przed 12.10.2026 nie wchodzą, bo wcześniej był import z Traffita. Portale: etap po pierwszym zgłoszeniu w okresie, w dowolnej rekrutacji, bo zgłoszenie z portalu nie mówi, której rekrutacji dotyczy. Link do rekrutacji: etap w rekrutacji linku. Link ogólny: w dowolnej rekrutacji.
          </p>
        </details>
      </div>

      {seesOwners ? <InsightsLinkPeople period={period} /> : <InsightsInviteLinks period={period} />}

      {selection && !inline && (
        <aside
          className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[620px] flex-col border-l border-border bg-card shadow-xl"
          aria-label="Osoby za liczbą"
          data-testid="sources-people-panel"
        >
          <DetailPanel
            title={`${metricLabel(selection.metric)}: ${fmt(selection.total)}`}
            subtitle={`${selection.title} · 12.10–2.11.2026`}
            onClose={() => setSelection(null)}
            footer={<PeopleFooter selection={selection} />}
          >
            <div className="p-4">
              <PeopleTable selection={selection} />
            </div>
          </DetailPanel>
        </aside>
      )}
    </div>
  );
}
