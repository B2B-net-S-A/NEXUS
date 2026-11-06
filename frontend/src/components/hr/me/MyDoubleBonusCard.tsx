"use client";

// „Do 200%”: postęp osoby w miesiącu programu premii 200% (decyzje Artura
// 05.11.2026). Rekruter widzi placementy, weryfikacje na dzień i precision,
// Delivery Lead średnią marżę placementów podpisanych w miesiącu.

import { apiErrorMessage } from "@/lib/api-error";
import {
  useMyDoubleBonus,
  type DoubleBonusDl,
  type DoubleBonusRecruiter,
  type DoubleBonusThresholds,
} from "@/lib/api/hr-payroll";
import type { EmploymentTerms } from "@/lib/hr-employment-terms";

import { progressShare } from "../payroll/double-bonus-format";
import { monthLocative } from "../payroll/payroll-format";

interface MyDoubleBonusCardProps {
  words: Pick<EmploymentTerms, "bonuses">;
}

export function MyDoubleBonusCard({ words }: MyDoubleBonusCardProps) {
  const query = useMyDoubleBonus();
  if (query.isError) {
    return (
      <p className="text-xs text-muted-foreground">
        {apiErrorMessage(query.error, "Nie udało się wczytać postępu do 200%.")}
      </p>
    );
  }
  const data = query.data;
  if (!query.isSuccess || !data?.in_program || !data.thresholds) return null;
  const rows = data.rows.filter((row) => !row.excluded);
  if (rows.length === 0) return null;
  const thresholds = data.thresholds;

  return (
    <section
      aria-labelledby="my-double-bonus"
      data-tour="my-time.double-bonus"
      className="space-y-3 rounded-lg border border-border bg-card p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="my-double-bonus" className="text-sm font-semibold text-foreground">
          Do 200% w {monthLocative(data.year, data.month)}
        </h3>
        <span className="text-xs text-muted-foreground">
          {data.final ? "wynik po końcu miesiąca" : "stan na dziś"}
        </span>
      </div>
      {rows.map((row) =>
        row.kind === "dl" ? (
          <DlProgress key="dl" row={row} thresholds={thresholds} />
        ) : (
          <RecruiterProgress key="recruiter" row={row} thresholds={thresholds} />
        ),
      )}
      <p className="text-xs text-muted-foreground">
        Gdy na koniec miesiąca spełnisz warunki, {words.bonuses} za placementy podpisane w tym
        miesiącu dostaniesz podwójnie i od razu z tym miesiącem. Jeśli nie, zwykła kwota po
        przepracowaniu progu przez konsultanta.
      </p>
    </section>
  );
}

function Meter({
  label,
  value,
  share,
  met,
}: {
  label: string;
  value: string;
  share: number;
  met: boolean;
}) {
  return (
    <div className="space-y-1 rounded-md bg-muted/40 p-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold tabular-nums text-foreground">{value}</div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
        <div
          className={met ? "h-full bg-success" : "h-full bg-primary"}
          style={{ width: `${share}%` }}
        />
      </div>
    </div>
  );
}

const pl = (value: string | null, digits = 1) =>
  value == null ? "—" : Number(value).toLocaleString("pl-PL", { maximumFractionDigits: digits });

function RecruiterProgress({
  row,
  thresholds,
}: {
  row: DoubleBonusRecruiter;
  thresholds: DoubleBonusThresholds;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      <Meter
        label="Placementy podpisane"
        value={`${row.placements} / ${row.target ?? "—"}`}
        share={progressShare(row.placements, row.target ?? 0)}
        met={row.checks.placements}
      />
      <Meter
        label="Weryfikacje na dzień"
        value={`${pl(row.verifications_per_day)} / ${pl(thresholds.verifications_per_day)}`}
        share={progressShare(row.verifications_per_day, thresholds.verifications_per_day)}
        met={row.checks.verifications}
      />
      <Meter
        label="Precision"
        value={`${pl(row.precision_pct, 0)}% / ${pl(thresholds.precision_pct, 0)}%`}
        share={progressShare(row.precision_pct, thresholds.precision_pct)}
        met={row.checks.precision}
      />
    </div>
  );
}

function DlProgress({ row, thresholds }: { row: DoubleBonusDl; thresholds: DoubleBonusThresholds }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <Meter
        label={`Średnia marża (więcej niż ${pl(thresholds.dl_min_margin, 2)} zł/h)`}
        value={row.average_margin == null ? "—" : `${pl(row.average_margin, 2)} zł/h`}
        share={progressShare(row.average_margin, thresholds.dl_min_margin)}
        met={row.qualified}
      />
      <Meter
        label="Placementy podpisane"
        value={String(row.placements)}
        share={row.placements > 0 ? 100 : 0}
        met={row.placements > 0}
      />
    </div>
  );
}
