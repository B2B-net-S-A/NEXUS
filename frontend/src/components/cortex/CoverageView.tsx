"use client";

import { FileText, Gauge, ScanText, Tags, UserCheck } from "lucide-react";
import type { CortexCoverage } from "@/lib/api";
import { StatCard, StatCardGrid } from "@/components/ds/StatCard";

const FRESHNESS_LABELS: Record<string, string> = {
  lt_1y: "‹ 1 rok",
  y1_3: "1–3 lata",
  gt_3y: "› 3 lata",
  unknown: "nieznana data",
};

// Semantic freshness ramp using existing theme tokens (globals.css defines
// --success / --warning; --destructive is also a mapped Tailwind color). Arbitrary
// `bg-[hsl(var(--…))]` values keep this theme-aware without adding new tokens.
// fresh → good (success), medium → warning, stale → destructive.
const FRESHNESS_COLORS: Record<string, string> = {
  lt_1y: "bg-[hsl(var(--success))]",
  y1_3: "bg-[hsl(var(--warning))]",
  gt_3y: "bg-destructive",
  unknown: "bg-muted-foreground/40",
};

/** Czysto prezentacyjny widok jakości danych (reużywany przez /preview/cortex). */
export function CoverageView({ data }: { data: CortexCoverage }) {
  const c = data.candidates;
  const freshnessTotal = Object.values(data.facts.freshness).reduce(
    (a, b) => a + b,
    0
  );

  return (
    <div className="space-y-6">
      <StatCardGrid>
        <StatCard
          label="Plik CV"
          value={`${c.with_cv_file_pct}%`}
          sub={`${c.with_cv_file.toLocaleString("pl-PL")} rekordów`}
          icon={FileText}
        />
        <StatCard
          label="Tekst z CV"
          value={`${c.with_raw_cv_text_pct}%`}
          sub={`${c.with_raw_cv_text.toLocaleString("pl-PL")} zparsowanych`}
          icon={ScanText}
        />
        <StatCard
          label="Fakty kompetencyjne"
          value={`${c.with_any_fact_pct}%`}
          sub={`${c.with_any_fact.toLocaleString("pl-PL")} rekordów z ≥1 faktem`}
          icon={Tags}
        />
        <StatCard
          label="Znana dostępność"
          value={`${c.availability_known_pct}%`}
          sub={`${c.availability_known.toLocaleString("pl-PL")} deklaracji`}
          icon={UserCheck}
        />
      </StatCardGrid>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="bg-card dark:bg-muted rounded-2xl shadow-sm p-6 space-y-3">
          <h3 className="font-semibold text-sm flex items-center gap-2">
            <Gauge className="w-4 h-4" />
            Świeżość faktów (kiedy sygnał był prawdziwy)
          </h3>
          {freshnessTotal === 0 ? (
            <p className="text-sm text-muted-foreground">Brak faktów.</p>
          ) : (
            <>
              <div className="flex h-3 w-full overflow-hidden rounded-full bg-muted">
                {Object.entries(data.facts.freshness).map(([bucket, cnt]) =>
                  cnt > 0 ? (
                    <div
                      key={bucket}
                      className={FRESHNESS_COLORS[bucket]}
                      style={{ width: `${(cnt / freshnessTotal) * 100}%` }}
                      title={`${FRESHNESS_LABELS[bucket]}: ${cnt}`}
                    />
                  ) : null
                )}
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                {Object.entries(data.facts.freshness).map(([bucket, cnt]) => (
                  <span key={bucket} className="inline-flex items-center gap-1.5">
                    <span
                      className={`inline-block h-2 w-2 rounded-full ${FRESHNESS_COLORS[bucket]}`}
                    />
                    {FRESHNESS_LABELS[bucket]}:{" "}
                    <span className="tabular-nums">
                      {cnt.toLocaleString("pl-PL")}
                    </span>
                  </span>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                Fakty z Traffita nie mają daty źródłowej — lądują uczciwie w
                „nieznana data”.
              </p>
            </>
          )}
          <div className="pt-2 border-t border-border text-xs text-muted-foreground space-y-1">
            <div>
              Fakty wg źródła:{" "}
              {Object.entries(data.facts.by_source).length === 0
                ? "brak"
                : Object.entries(data.facts.by_source)
                    .map(
                      ([src, v]) =>
                        `${src}: ${v.facts.toLocaleString("pl-PL")} faktów / ${v.candidates.toLocaleString("pl-PL")} kandydatów`
                    )
                    .join(" · ")}
            </div>
            <div>
              Surowiec: traffit_technologie u {c.with_traffit_tech_pct}% bazy (
              {c.with_traffit_tech.toLocaleString("pl-PL")} rekordów).
            </div>
          </div>
        </div>

        <div className="bg-card dark:bg-muted rounded-2xl shadow-sm p-6 space-y-3">
          <h3 className="font-semibold text-sm">Procesy zbierania powodów</h3>
          <ProcessRow
            label="Powód zamknięcia rekrutacji (close_reason)"
            done={data.processes.jobs_closed_with_reason}
            total={data.processes.jobs_closed}
          />
          <ProcessRow
            label="Powód zakończenia kontraktu (termination_reason)"
            done={data.processes.contracts_ended_with_reason}
            total={data.processes.contracts_ended}
          />
          <p className="text-xs text-muted-foreground">
            {data.processes.contracts_natural_expiry.toLocaleString("pl-PL")}{" "}
            kontraktów wygasło naturalnie (koniec okresu — to nie terminacja).
            Wymuszenie obu pól przy zamykaniu wchodzi w kolejnym etapie Cortexa;
            historia importowana z Traffita pozostanie „unknown”.
          </p>
        </div>
      </div>
    </div>
  );
}

function ProcessRow({
  label,
  done,
  total,
}: {
  label: string;
  done: number;
  total: number;
}) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span>{label}</span>
        <span className="tabular-nums text-muted-foreground">
          {done.toLocaleString("pl-PL")} / {total.toLocaleString("pl-PL")} ({pct}
          %)
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full bg-primary"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
