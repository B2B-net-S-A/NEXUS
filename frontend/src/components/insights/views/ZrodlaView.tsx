"use client";

/**
 * „Źródła”: skąd przychodzą kandydaci (decyzje Artura 03.11.2026). Portale i strona
 * kariery w jednej tabeli, klik w źródło rozwija ogłoszenia albo linki, klik w liczbę
 * otwiera osoby. Reguła: `docs/claude/finanse-insights/zakladka-zrodla.md`.
 */

import { Fragment, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";

import {
  describeWindow,
  lastDaysPeriod,
  PeriodPicker,
} from "@/components/insights/PeriodPicker";
import { InsightsInviteLinks } from "@/components/insights/sections/InsightsInviteLinks";
import { InsightsLinkPeople } from "@/components/insights/sections/InsightsLinkPeople";
import { SectionError } from "@/components/insights/sections/_shared";
import {
  SOURCE_METRICS,
  SourcesPeoplePanel,
  type SourcePeopleSelection,
} from "@/components/insights/sections/SourcesPeoplePanel";
import { useInsightsPeriod } from "@/components/insights/useInsightsPeriod";
import {
  insightsApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
  type SourceCounts,
  type SourceKey,
  type SourceMetric,
  type SourceRow,
} from "@/lib/insights-api";
import { pluralPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { hasRole, useAuthStore } from "@/store/auth";
import { ViewHeader } from "./ViewKit";

const DEFAULT_DAYS = 30;
const OFFERS_PREVIEW = 6;
const OFFERS_ALL = 500;
const fmt = (value: number): string => value.toLocaleString("pl-PL");

type Pick = (metric: SourceMetric, total: number) => void;

function Numbers({
  counts,
  rowKey,
  active,
  onPick,
  total = false,
  barMax,
}: {
  counts: SourceCounts;
  rowKey: string;
  active: string | null;
  onPick?: Pick;
  total?: boolean;
  barMax?: number;
}) {
  return (
    <>
      {SOURCE_METRICS.map((column) => {
        const value = counts[column.key];
        const isActive = active === `${rowKey}:${column.key}`;
        return (
          <td key={column.key} className="px-2 py-1 text-right tabular-nums">
            <div className="flex items-center justify-end gap-2">
              {onPick && value > 0 ? (
                <button
                  type="button"
                  onClick={() => onPick(column.key, value)}
                  aria-label={`${column.label}: ${fmt(value)}, pokaż osoby`}
                  data-testid={`sources-cell-${rowKey}:${column.key}`}
                  className={cn(
                    "rounded px-1.5 py-0.5 tabular-nums text-foreground underline decoration-dotted decoration-muted-foreground/50 underline-offset-2 hover:bg-primary/10 hover:text-primary",
                    column.key === "people" && "font-semibold",
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
              {column.key === "people" ? (
                <span className="h-1.5 w-12 overflow-hidden rounded-full">
                  {barMax ? (
                    <span className="block h-full rounded-full bg-muted">
                      <span
                        className="block h-full rounded-full bg-primary"
                        style={{ width: `${Math.max((value / barMax) * 100, value > 0 ? 3 : 0)}%` }}
                      />
                    </span>
                  ) : null}
                </span>
              ) : null}
            </div>
          </td>
        );
      })}
    </>
  );
}

function GroupHeader({ label }: { label: string }) {
  return (
    <tr className="border-t border-border">
      <td colSpan={SOURCE_METRICS.length + 1} className="px-4 pb-0.5 pt-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </td>
    </tr>
  );
}

function SubMessage({ children }: { children: ReactNode }) {
  return (
    <tr className="border-t border-border bg-muted/20 text-xs">
      <td colSpan={SOURCE_METRICS.length + 1} className="py-1.5 pl-9 text-muted-foreground">
        {children}
      </td>
    </tr>
  );
}

function SubRow({
  label,
  counts,
  rowKey,
  active,
  onPick,
}: {
  label: string;
  counts: SourceCounts;
  rowKey: string;
  active: string | null;
  onPick: Pick;
}) {
  return (
    <tr className="border-t border-border bg-muted/20 text-xs">
      <td className="max-w-[230px] truncate py-1 pl-9 pr-2 text-foreground" title={label}>
        {label}
      </td>
      <Numbers counts={counts} rowKey={rowKey} active={active} onPick={onPick} />
    </tr>
  );
}

function PortalOffers({
  row,
  period,
  active,
  select,
}: {
  row: SourceRow;
  period: InsightsPeriodParams;
  active: string | null;
  select: (next: SourcePeopleSelection, key: string) => void;
}) {
  const [limit, setLimit] = useState(OFFERS_PREVIEW);
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: insightsQueryKeys.sourceOffers(period, row.source, limit),
    queryFn: () => insightsApi.sourceOffers(period, row.source, limit),
  });
  if (isPending) return <SubMessage>Ładuję ogłoszenia…</SubMessage>;
  if (isError) {
    return (
      <SubMessage>
        Nie udało się pobrać ogłoszeń.{" "}
        <button type="button" onClick={() => void refetch()} className="text-primary hover:underline">
          Spróbuj ponownie
        </button>
      </SubMessage>
    );
  }
  if (data.rows.length === 0) return <SubMessage>W tym okresie nie ma ogłoszeń ze zgłoszeniami.</SubMessage>;
  return (
    <>
      {data.rows.map((offer) => {
        const rowKey = `${row.source}/${offer.offer}`;
        const label = offer.offer || "Bez tytułu ogłoszenia";
        return (
          <SubRow
            key={rowKey}
            label={label}
            counts={offer}
            rowKey={rowKey}
            active={active}
            onPick={(metric, total) =>
              select(
                { source: row.source, metric, offer: offer.offer, title: `${row.label} · ${label}`, total },
                `${rowKey}:${metric}`,
              )
            }
          />
        );
      })}
      {data.total > data.rows.length && (
        <SubMessage>
          <button type="button" onClick={() => setLimit(OFFERS_ALL)} className="text-primary hover:underline">
            Pokaż wszystkie ogłoszenia ({fmt(data.total)})
          </button>
        </SubMessage>
      )}
    </>
  );
}

function LinkBreakdown({
  row,
  period,
  active,
  select,
}: {
  row: SourceRow;
  period: InsightsPeriodParams;
  active: string | null;
  select: (next: SourcePeopleSelection, key: string) => void;
}) {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: insightsQueryKeys.sourceLinks(period, row.source),
    queryFn: () => insightsApi.sourceLinks(period, row.source),
  });
  if (isPending) return <SubMessage>Ładuję linki…</SubMessage>;
  if (isError) {
    return (
      <SubMessage>
        Nie udało się pobrać linków.{" "}
        <button type="button" onClick={() => void refetch()} className="text-primary hover:underline">
          Spróbuj ponownie
        </button>
      </SubMessage>
    );
  }
  return (
    <>
      {data.rows.map((link) => {
        const rowKey = `${row.source}/${link.key ?? "brak"}`;
        const scope =
          link.key === null
            ? {}
            : row.source === "link_general"
              ? { owner_id: link.key }
              : { job_id: link.key };
        return (
          <SubRow
            key={rowKey}
            label={link.label}
            counts={link}
            rowKey={rowKey}
            active={active}
            onPick={(metric, total) =>
              select(
                { source: row.source, metric, ...scope, title: `${row.label} · ${link.label}`, total },
                `${rowKey}:${metric}`,
              )
            }
          />
        );
      })}
    </>
  );
}

function per100(row: SourceRow): string | null {
  if (row.people === 0) return null;
  return ((row.cv_sent / row.people) * 100).toLocaleString("pl-PL", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

function conclusion(portals: SourceRow[], portalPeople: number, careerPeople: number): string {
  const rates = portals
    .map((row) => ({ label: row.label, rate: per100(row) }))
    .filter((item) => item.rate !== null)
    .map((item) => `z ${item.label} ${item.rate}`);
  const noun = pluralPl(portalPeople, "osobę", "osoby", "osób");
  const head = `Portale dały ${fmt(portalPeople)} ${noun}, strona kariery ${fmt(careerPeople)}.`;
  return rates.length > 0 ? `${head} Na 100 osób do wysłanego CV dochodzi ${rates.join(", ")}.` : head;
}

export function ZrodlaView() {
  const fallback = useMemo(() => lastDaysPeriod(DEFAULT_DAYS), []);
  const { period, setPeriod } = useInsightsPeriod(fallback);
  const user = useAuthStore((s) => s.user);
  const seesOwners = hasRole(user, "admin", "head_of_recruitment", "delivery_lead");
  const [open, setOpen] = useState<ReadonlySet<SourceKey>>(new Set());
  const [selection, setSelection] = useState<{ value: SourcePeopleSelection; key: string } | null>(null);

  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.sources(period),
    queryFn: () => insightsApi.sources(period),
  });
  const viewState = resolveViewState({ isLoading: isPending, isSuccess, isError, error, isEmpty: false });

  const toggle = (key: SourceKey) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const select = (value: SourcePeopleSelection, key: string) => setSelection({ value, key });
  const active = selection?.key ?? null;

  const caption = data ? describeWindow(data.period, period.period) : null;
  const clipped = data ? new Date(data.counted_from).getTime() > new Date(data.period.start).getTime() : false;
  const maxPeople = data ? Math.max(...data.portals.map((row) => row.people), ...data.career.map((row) => row.people), 1) : 1;

  const sourceRow = (row: SourceRow, expandable: boolean, details: ReactNode) => (
    <Fragment key={row.source}>
      <tr className="border-t border-border hover:bg-muted/30">
        <td className="px-4 py-1 font-medium text-foreground">
          {expandable ? (
            <button
              type="button"
              onClick={() => toggle(row.source)}
              aria-expanded={open.has(row.source)}
              className="inline-flex items-center gap-1 text-left font-medium hover:text-primary"
            >
              {open.has(row.source) ? (
                <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
              )}
              {row.label}
            </button>
          ) : (
            row.label
          )}
        </td>
        <Numbers
          counts={row}
          rowKey={row.source}
          active={active}
          barMax={maxPeople}
          onPick={(metric, total) =>
            select({ source: row.source, metric, title: row.label, total }, `${row.source}:${metric}`)
          }
        />
      </tr>
      {expandable && open.has(row.source) ? details : null}
    </Fragment>
  );

  return (
    <div className="space-y-6">
      <div className="grid gap-3">
        <ViewHeader
          question="Skąd przychodzą kandydaci?"
          lede={data ? conclusion(data.portals, data.portals_total.people, data.career_total.people) : undefined}
        />
        <div className="flex justify-end">
          <PeriodPicker
            value={period}
            onChange={(next) => {
              setSelection(null);
              setPeriod(next);
            }}
            resolved={data?.period ?? null}
            defaultValue={fallback}
            hideHistoryNote
          />
        </div>
      </div>

      {viewState === "loading" ? (
        <section className="flex justify-center rounded-xl border border-border bg-card py-12 shadow-xs">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </section>
      ) : isBlockingViewState(viewState) || !data ? (
        <SectionError label="Źródła kandydatów" error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <section className="overflow-hidden rounded-xl border border-border bg-card shadow-xs" data-testid="sources-table">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-sm">
                <thead className="bg-muted/50 text-xs text-muted-foreground">
                  <tr>
                    <th className="w-[230px] px-4 py-2 text-left font-medium">Źródło</th>
                    {SOURCE_METRICS.map((column) => (
                      <th key={column.key} className="px-3 py-2 text-right font-medium" title={column.means}>
                        {column.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <GroupHeader label="Portale" />
                  {data.portals.map((row) =>
                    sourceRow(
                      row,
                      row.applications > 0,
                      <PortalOffers row={row} period={period} active={active} select={select} />,
                    ),
                  )}
                  <tr className="border-t border-border bg-muted/30">
                    <td className="px-4 py-1 font-semibold text-foreground">Razem portale</td>
                    <Numbers counts={data.portals_total} rowKey="portale" active={active} total />
                  </tr>
                  <GroupHeader label="Strona kariery" />
                  {data.career.map((row) =>
                    sourceRow(
                      row,
                      seesOwners && row.applications > 0,
                      <LinkBreakdown row={row} period={period} active={active} select={select} />,
                    ),
                  )}
                  <tr className="border-t border-border bg-muted/30">
                    <td className="px-4 py-1 font-semibold text-foreground">Razem strona kariery</td>
                    <Numbers counts={data.career_total} rowKey="kariera" active={active} total />
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <div className="grid gap-1 text-xs text-muted-foreground">
            <p>
              Podkreślona liczba otwiera listę osób. Klik w źródło pokazuje ogłoszenia albo linki. „Razem” liczy osobę raz, więc nie jest sumą wierszy.
              {clipped ? " Zgłoszenia liczymy od 12.10.2026, wcześniej był import z Traffita." : ""}
            </p>
            <p>
              Nowi kandydaci bez rozpoznanego źródła: {fmt(data.new_candidates_without_source)} z {fmt(data.new_candidates_total)}. Stan scraperów i błędy importu:{" "}
              <Link href="/insights?tab=raporty&report=doplyw" className="text-primary hover:underline">
                Raporty → Źródła, portale i linki
              </Link>
              .
            </p>
            <details>
              <summary className="cursor-pointer">Jak liczymy?</summary>
              <p className="mt-1 max-w-3xl">
                Portale: etap po pierwszym zgłoszeniu w okresie, w dowolnej rekrutacji, bo zgłoszenie z portalu nie mówi, której rekrutacji dotyczy. Link do rekrutacji: etap w rekrutacji linku. Link ogólny: w dowolnej rekrutacji. JustJoin.IT i RocketJobs mają jedno konto i scraper nie rozdziela ich zgłoszeń.
              </p>
            </details>
          </div>
        </>
      )}

      {seesOwners ? <InsightsLinkPeople period={period} /> : <InsightsInviteLinks period={period} />}

      {selection && (
        <SourcesPeoplePanel
          key={selection.key}
          selection={selection.value}
          period={period}
          rangeLabel={caption?.range ?? ""}
          canExport={seesOwners}
          onClose={() => setSelection(null)}
        />
      )}
    </div>
  );
}
