"use client";

// Zakładka klienta „Stawki ramowe” (F2, 15.11.2026): kto jest w limicie z umowy
// ramowej, kto dzięki dopłacie, kto ponad i co daje umowa; raport kwartalny
// Governance (xlsx bez marży) i cennik umowy. Kwoty: DL swojego klienta i Finanse.
import Link from "next/link";
import { useMemo, useState } from "react";
import { Download, Search } from "lucide-react";

import { FrameworkTermsPanel } from "@/components/clients/FrameworkTermsPanel";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  frameworkReportPath,
  useFrameworkOverview,
  type FrameworkOverview,
  type FrameworkStatus,
} from "@/lib/api/framework-rates";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { formatIsoDatePl } from "@/lib/date-pl";
import { STATUS_LABEL, plnAmount, plnPerHour, statusTone } from "@/lib/framework-category";
import { filterRows, inRateShare, quarterLabel, type OverviewFilter } from "@/lib/framework-overview";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

type View = "people" | "report" | "terms";

interface Props {
  clientId: number;
  canImport: boolean;
  canRecompute: boolean;
}

export function FrameworkRatesTab({ clientId, canImport, canRecompute }: Props) {
  const query = useFrameworkOverview(clientId, true);
  const [view, setView] = useState<View>("people");

  return (
    <div className="space-y-3" data-testid="framework-rates-tab">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-foreground">Stawki z umowy ramowej</h2>
          <p className="text-xs text-muted-foreground">
            Limit = maksimum z cennika × dopłata za technologię. Dopłata nie zmienia stawki przychodowej.
          </p>
        </div>
        <div className="flex rounded-lg border border-border bg-muted/40 p-0.5 text-xs" role="tablist">
          {(
            [
              ["people", "Konsultanci"],
              ["report", "Raport kwartalny"],
              ["terms", "Cennik umowy"],
            ] as [View, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={view === key}
              data-tour={key === "report" ? "clients.framework-rates.report" : undefined}
              onClick={() => setView(key)}
              className={cn(
                "rounded-md px-2.5 py-1 font-medium transition-colors",
                view === key ? "bg-card text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {view === "terms" ? (
        <FrameworkTermsPanel clientId={clientId} canImport={canImport} canRecompute={canRecompute} />
      ) : query.isPending ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : !query.isSuccess ? (
        <QueryStateNotice
          state={
            resolveViewState({ isLoading: false, isError: true, error: query.error, isEmpty: false }) === "forbidden"
              ? "forbidden"
              : "error"
          }
          onRetry={() => void query.refetch()}
        />
      ) : view === "people" ? (
        <PeopleView data={query.data} onOpenTerms={() => setView("terms")} />
      ) : (
        <ReportView data={query.data} clientId={clientId} />
      )}
    </div>
  );
}

function Kpis({ data }: { data: FrameworkOverview }) {
  const c = data.counts;
  const share = inRateShare(c);
  const items: { label: string; value: number; sub: string; tone: string }[] = [
    { label: "W stawce", value: c.in + c.in_addon, sub: `${share ?? "—"}% osób z limitem · ${c.in_addon} dzięki dopłacie`, tone: "bg-success" },
    { label: "Ponad stawką", value: c.over, sub: `łącznie +${plnPerHour(data.over_gap)} ponad limit`, tone: "bg-destructive" },
    { label: "Z dźwignią w umowie", value: data.rows.filter((r) => r.levers.length > 0).length, sub: "dopłata albo awans poziomu", tone: "bg-warning" },
    { label: "Bez limitu z umowy", value: c.no_limit, sub: "brak kategorii albo stawki", tone: "bg-muted-foreground/40" },
  ];
  return (
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
      {items.map((k) => (
        <div key={k.label} className="relative min-w-0 overflow-hidden rounded-xl border border-border bg-card px-3 py-1.5">
          <span className={cn("absolute inset-y-0 left-0 w-1", k.tone)} />
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-semibold tabular-nums text-foreground">{k.value}</span>
            <span className="truncate text-[11px] font-medium text-muted-foreground">{k.label}</span>
          </div>
          <div className="truncate text-[11px] leading-4 text-muted-foreground" title={k.sub}>
            {k.sub}
          </div>
        </div>
      ))}
    </div>
  );
}

function PeopleView({ data, onOpenTerms }: { data: FrameworkOverview; onOpenTerms: () => void }) {
  const [filter, setFilter] = useState<OverviewFilter>("all");
  const [q, setQ] = useState("");
  const rows = useMemo(() => filterRows(data.rows, filter, q), [data.rows, filter, q]);
  const filters: [OverviewFilter, string, number][] = [
    ["all", "Wszyscy", data.rows.length],
    ["over", STATUS_LABEL.over, data.counts.over],
    ["in", STATUS_LABEL.in, data.counts.in],
    ["in_addon", STATUS_LABEL.in_addon, data.counts.in_addon],
    ["no_limit", STATUS_LABEL.no_limit, data.counts.no_limit],
  ];

  if (data.rows.length === 0) {
    return (
      <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
        Klient nie ma aktywnych kontraktów.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <Kpis data={data} />
      {data.rows.every((r) => !r.category) && (
        <p className="rounded-lg border border-warning/30 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
          Żaden kontrakt nie ma jeszcze kategorii z umowy ramowej.{" "}
          <button type="button" className="underline" onClick={onOpenTerms}>
            Cennik umowy
          </button>{" "}
          → wgraj załącznik i „Przelicz kategorie z COA”.
        </p>
      )}
      <div className="rounded-xl border border-border bg-card">
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
          {filters.map(([key, label, count]) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs",
                filter === key ? "border-primary/40 bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground",
              )}
            >
              {label} {count}
            </button>
          ))}
          <label className="relative ml-auto flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground">
            <Search className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="sr-only">Szukaj osoby albo kategorii</span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Osoba albo kategoria"
              className="w-40 bg-transparent text-foreground outline-hidden placeholder:text-muted-foreground"
            />
          </label>
        </div>
        <div className="max-h-[calc(100dvh-340px)] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-card text-left text-[11px] uppercase tracking-wide text-muted-foreground">
              <tr className="border-b border-border">
                <th className="px-3 py-1.5 font-medium">Konsultant</th>
                <th className="px-2 py-1.5 font-medium">Kategoria</th>
                <th className="px-2 py-1.5 text-right font-medium">Stawka zł/h</th>
                <th className="px-2 py-1.5 text-right font-medium">Limit zł/h</th>
                <th className="px-2 py-1.5 text-right font-medium">Różnica</th>
                <th className="px-2 py-1.5 font-medium">Status</th>
                <th className="px-2 py-1.5 font-medium">Dźwignia z umowy</th>
                <th className="px-3 py-1.5 font-medium">Koniec COA</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const gap = row.gap === null ? null : Number(row.gap);
                return (
                  <tr key={row.contract_id} className="border-b border-border/60 hover:bg-muted/50">
                    <td className="px-3 py-1.5">
                      <Link href={`/contracts/${row.contract_id}`} className="whitespace-nowrap font-medium text-foreground hover:underline">
                        {row.person}
                      </Link>
                    </td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-xs">
                      {row.category ?? (
                        <span className="text-muted-foreground">{row.coa_label ? `${row.coa_label} (spoza cennika)` : "—"}</span>
                      )}
                      {row.addon && <div className="text-[11px] text-info">+ {row.addon}</div>}
                      {row.limit_mismatch && (
                        <div className="text-[11px] text-warning" title="Limit na kontrakcie nie wynika z cennika (dawny import albo ręczny krok). Sprawdź kategorię i dopłatę w kontrakcie.">
                          limit ≠ cennik
                        </div>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums">{plnAmount(row.rate)}</td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums">{plnAmount(row.limit)}</td>
                    <td className={cn("whitespace-nowrap px-2 py-1.5 text-right tabular-nums font-medium", gap !== null && gap > 0 ? "text-destructive" : "text-success")}>
                      {gap === null ? "—" : gap > 0 ? `+${plnAmount(gap)}` : plnAmount(gap)}
                    </td>
                    <td className="px-2 py-1.5">
                      <StatusDot tone={statusTone(row.status as FrameworkStatus)}>{STATUS_LABEL[row.status]}</StatusDot>
                    </td>
                    <td className="px-2 py-1.5">
                      {row.levers.length ? (
                        <span className="flex flex-wrap gap-1">
                          {row.levers.map((l) => (
                            <Badge key={l.label} variant={l.kind === "addon" ? "soft" : "outline"} size="md" className="whitespace-nowrap">
                              {l.label}
                            </Badge>
                          ))}
                        </span>
                      ) : row.status === "over" && !row.limit_mismatch ? (
                        <span className="text-xs text-muted-foreground">{row.category ? "brak w umowie" : "brak kategorii"}</span>
                      ) : null}
                    </td>
                    <td className="px-3 py-1.5 text-xs tabular-nums text-muted-foreground">
                      {row.order_end ? formatIsoDatePl(row.order_end) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && <p className="p-4 text-sm text-muted-foreground">Nikt nie pasuje do filtra.</p>}
        </div>
      </div>
    </div>
  );
}

function ReportView({ data, clientId }: { data: FrameworkOverview; clientId: number }) {
  const { showError } = useToast();
  const [busy, setBusy] = useState(false);
  const max = Math.max(1, ...data.trend.map((p) => p.counts.in + p.counts.in_addon + p.counts.over));

  const download = async () => {
    setBusy(true);
    try {
      await downloadAuthenticatedFile(frameworkReportPath(clientId), `stawki-ramowe-${data.on}.xlsx`);
    } catch (err) {
      showError(apiErrorMessage(err, "Nie udało się pobrać raportu."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-3 lg:grid-cols-[1.1fr_1fr]">
      <div className="space-y-3 rounded-xl border border-border bg-card p-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="text-sm font-semibold text-foreground">Raport Governance · stan na {formatIsoDatePl(data.on)}</div>
            <div className="text-xs text-muted-foreground">Do klienta: osoby w stawce, z dopłatą i ponad stawką. Bez marży.</div>
          </div>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void download()}>
            <Download className="mr-1 h-3.5 w-3.5" />
            Pobierz xlsx
          </Button>
        </div>
        <div className="space-y-1.5" aria-label="Trend kwartałów">
          {data.trend.map((point) => {
            const total = point.counts.in + point.counts.in_addon + point.counts.over;
            return (
              <div key={point.on} className="grid grid-cols-[64px_1fr_96px] items-center gap-2 text-xs">
                <span className="text-muted-foreground">{quarterLabel(point.on, data.on)}</span>
                <span className="flex h-3 overflow-hidden rounded-full bg-muted" style={{ width: `${(total / max) * 100}%` }}>
                  <span className="bg-success" style={{ width: `${(point.counts.in / Math.max(total, 1)) * 100}%` }} />
                  <span className="bg-info" style={{ width: `${(point.counts.in_addon / Math.max(total, 1)) * 100}%` }} />
                  <span className="bg-destructive" style={{ width: `${(point.counts.over / Math.max(total, 1)) * 100}%` }} />
                </span>
                <span className="text-right tabular-nums text-muted-foreground">
                  {point.counts.in + point.counts.in_addon} / {point.counts.over}
                </span>
              </div>
            );
          })}
          <p className="text-[11px] text-muted-foreground">Zielone: w stawce · niebieskie: dzięki dopłacie · czerwone: ponad. Liczby: w stawce / ponad.</p>
        </div>
      </div>
      <div className="rounded-xl border border-border bg-card p-3">
        <div className="mb-2 text-sm font-semibold text-foreground">Według kategorii</div>
        <table className="w-full text-xs">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-1 font-medium">Kategoria</th>
              <th className="text-right font-medium">W stawce</th>
              <th className="text-right font-medium">Z dopłatą</th>
              <th className="text-right font-medium">Ponad</th>
            </tr>
          </thead>
          <tbody>
            {data.by_category.map((c) => (
              <tr key={c.category} className="border-t border-border/60">
                <td className="py-1 text-foreground">{c.category}</td>
                <td className="text-right tabular-nums">{c.counts.in}</td>
                <td className="text-right tabular-nums text-info">{c.counts.in_addon}</td>
                <td className="text-right tabular-nums text-destructive">{c.counts.over}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
