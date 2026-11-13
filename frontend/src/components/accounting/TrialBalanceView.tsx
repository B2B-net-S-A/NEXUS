"use client";

import { Fragment, useMemo, useState } from "react";
import { X } from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
import { useAccountCard, useTrialBalance, type TrialRow } from "@/lib/api/accounting";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { useAccounting } from "./AccountingShell";
import { MONTHS_PL, analyticsLabel, datePl, findPeriod, gr } from "./ledger-model";

const CLASS_NAMES: Record<string, string> = {
  "0": "Aktywa trwałe",
  "1": "Środki pieniężne",
  "2": "Rozrachunki i roszczenia",
  "3": "Materiały i towary",
  "4": "Koszty według rodzajów",
  "5": "Koszty według funkcji (MPK)",
  "6": "Produkty i rozliczenia międzyokresowe",
  "7": "Przychody i koszty ich osiągnięcia",
  "8": "Kapitały, fundusze, rezerwy i wynik",
  "9": "Konta pozabilansowe",
};
const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";

function Amount({ value }: { value: number }) {
  return value ? <>{gr(value)}</> : <span className={CALM_EMPTY}>—</span>;
}

type Scope = "month" | "ytd" | "year";
type AmountKey = "bo_wn" | "bo_ma" | "wn" | "ma" | "saldo_wn" | "saldo_ma";

export function TrialBalanceView() {
  const { config, period } = useAccounting();
  const { year } = findPeriod(config, period);
  const [scope, setScope] = useState<Scope>("month");
  const [level, setLevel] = useState<"synthetic" | "analytic">("synthetic");
  const [account, setAccount] = useState<string | null>(null);
  const from = scope === "month" ? period.month : 1;
  const to = scope === "year" ? 12 : period.month;
  const trial = useTrialBalance(year ? period.year : null, from, to, level);
  const groups = useMemo(() => {
    const out = new Map<string, TrialRow[]>();
    for (const row of trial.data?.items ?? []) {
      const list = out.get(row.class) ?? [];
      list.push(row);
      out.set(row.class, list);
    }
    return [...out.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [trial.data]);

  if (!year) {
    return (
      <p className="rounded-lg border border-dashed border-border px-6 py-10 text-center text-sm text-muted-foreground">
        Nie ma roku obrotowego {period.year}.
      </p>
    );
  }
  const data = trial.data;
  const compact = account != null;
  const keys: readonly AmountKey[] = compact
    ? ["wn", "ma", "saldo_wn", "saldo_ma"]
    : ["bo_wn", "bo_ma", "wn", "ma", "saldo_wn", "saldo_ma"];
  const range =
    from === to ? MONTHS_PL[from - 1] : `${MONTHS_PL[from - 1]}–${MONTHS_PL[to - 1]}`;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="Zakres" value={scope} onChange={(e) => setScope(e.target.value as Scope)} className={CONTROL}>
          <option value="month">Obroty wybranego miesiąca</option>
          <option value="ytd">Od stycznia do wybranego miesiąca</option>
          <option value="year">Cały rok {period.year}</option>
        </select>
        <select
          aria-label="Poziom"
          value={level}
          onChange={(e) => setLevel(e.target.value as "synthetic" | "analytic")}
          className={CONTROL}
        >
          <option value="synthetic">Konta i grupy analityk</option>
          <option value="analytic">Każde konto analityczne</option>
        </select>
        <span className="text-[12px] text-muted-foreground">Tylko zapisy zatwierdzone; bufor nie wchodzi do obrotów.</span>
        {data ? (
          <span className={cn("ml-auto text-[13px] font-semibold", data.balanced ? "text-success" : "text-destructive")}>
            {data.balanced ? "Wn = Ma w obrotach, BO i saldach ✓" : "Wn ≠ Ma — sprawdź dokumenty"}
          </span>
        ) : null}
      </div>

      <div className={cn("grid gap-3", account && "xl:grid-cols-[minmax(0,1fr)_420px]")}>
        <div className="min-w-0">
          {trial.isLoading ? (
            <p className="py-6 text-sm text-muted-foreground">Wczytywanie obrotów…</p>
          ) : trial.isError ? (
            <QueryStateNotice state="error" onRetry={() => trial.refetch()} />
          ) : data && data.items.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
              Brak zatwierdzonych zapisów w okresie: {range} {period.year}.
            </div>
          ) : data ? (
            <div className="overflow-x-auto rounded-lg border border-border bg-card">
              {/* Przy otwartej karcie konta bez kolumn BO — saldo zostaje na ekranie 1280 px. */}
              <table className={cn("w-full table-fixed text-sm", compact ? "min-w-[540px]" : "min-w-[760px]")}>
                <colgroup>
                  <col className={compact ? "w-[16%]" : "w-[13%]"} />
                  <col />
                  {keys.map((key) => (
                    <col key={key} className={compact ? "w-[17%]" : key.startsWith("bo_") ? "w-[11%]" : "w-[12%]"} />
                  ))}
                </colgroup>
                <thead>
                  <tr className="border-b border-border/70">
                    <th className={cn(CALM_HEAD, "px-3 py-2 text-left")} rowSpan={2}>Konto</th>
                    <th className={cn(CALM_HEAD, "px-2 py-2 text-left")} rowSpan={2}>Nazwa</th>
                    {compact ? null : (
                      <th className={cn(CALM_HEAD, "px-2 pt-2 text-center")} colSpan={2}>Bilans otwarcia</th>
                    )}
                    <th className={cn(CALM_HEAD, "px-2 pt-2 text-center")} colSpan={2}>Obroty: {range}</th>
                    <th className={cn(CALM_HEAD, "px-3 pt-2 text-center")} colSpan={2}>Saldo, zł</th>
                  </tr>
                  <tr className="border-b border-border/70">
                    {keys.map((key, index) => (
                      <th key={key} className={cn(CALM_HEAD, "px-2 pb-1.5 text-right", index === keys.length - 1 && "pr-3")}>
                        {key.endsWith("_wn") || key === "wn" ? "Wn" : "Ma"}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {groups.map(([cls, rows]) => {
                    const sum = (key: keyof TrialRow) => rows.reduce((total, row) => total + (row[key] as number), 0);
                    return (
                      <Fragment key={cls}>
                        <tr className="border-b border-border/60 bg-muted/40">
                          <td className="px-3 py-1.5 text-[12px] font-semibold" colSpan={2}>
                            Zespół {cls} · {CLASS_NAMES[cls] ?? "Inne"}
                          </td>
                          {keys.map((key, index) => (
                            <td
                              key={key}
                              className={cn(
                                CALM_AMOUNT,
                                "px-2 py-1.5 text-[12px]",
                                index === keys.length - 1 && "pr-3",
                                (key === "wn" || key === "ma") && "font-semibold",
                              )}
                            >
                              <Amount value={sum(key)} />
                            </td>
                          ))}
                        </tr>
                        {rows.map((row) => (
                          <tr
                            key={row.account}
                            onClick={() => setAccount(row.account)}
                            className={cn(CALM_ROW, "cursor-pointer align-top hover:bg-muted/40", row.account === account && "bg-primary/5")}
                          >
                            <td className="px-3 py-1.5 font-medium tabular-nums text-primary">{row.account}</td>
                            <td className="min-w-0 px-2 py-1.5">
                              <span className="block truncate">{row.name}</span>
                              {row.analytics ? <span className={CALM_SUBLINE}>{analyticsLabel(row.analytics)}</span> : null}
                            </td>
                            {keys.map((key, index) => (
                              <td key={key} className={cn(CALM_AMOUNT, "px-2 py-1.5", index === keys.length - 1 && "pr-3")}>
                                <Amount value={row[key]} />
                              </td>
                            ))}
                          </tr>
                        ))}
                      </Fragment>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 border-border">
                    <td className="px-3 py-2 font-semibold" colSpan={2}>Razem</td>
                    {keys.map((key, index) => (
                      <td key={key} className={cn(CALM_AMOUNT, "px-2 py-2 font-semibold", index === keys.length - 1 && "pr-3")}>
                        {gr(data.totals[key])}
                      </td>
                    ))}
                  </tr>
                </tfoot>
              </table>
            </div>
          ) : null}
        </div>
        {account ? (
          <AccountCardPanel account={account} year={period.year} from={from} to={to} onClose={() => setAccount(null)} />
        ) : null}
      </div>
    </div>
  );
}

function AccountCardPanel({
  account,
  year,
  from,
  to,
  onClose,
}: {
  account: string;
  year: number;
  from: number;
  to: number;
  onClose: () => void;
}) {
  const card = useAccountCard(account, year, from, to);
  return (
    <aside className="min-w-0 self-start rounded-lg border border-border bg-card xl:sticky xl:top-3">
      <div className="flex items-start justify-between gap-3 border-b border-border/70 px-3.5 py-2.5">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">Karta konta</p>
          <h2 className="truncate text-[15px] font-semibold tabular-nums">{account}</h2>
          <p className="truncate text-[12px] text-muted-foreground">{card.data?.name ?? "—"}</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Zamknij kartę konta" className="text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
      {card.isLoading ? (
        <p className="px-3.5 py-4 text-sm text-muted-foreground">Wczytywanie zapisów…</p>
      ) : card.isError || !card.data ? (
        <QueryStateNotice state="error" onRetry={() => card.refetch()} className="m-3" />
      ) : (
        <>
          <p className="px-3.5 py-2 text-[12.5px] text-muted-foreground">
            Saldo na początek: <b className="tabular-nums text-foreground">{gr(card.data.opening)}</b> · na koniec:{" "}
            <b className="tabular-nums text-foreground">{gr(card.data.closing)}</b>
          </p>
          {card.data.payroll_hidden ? (
            <p className="mx-3.5 mb-2 rounded-md bg-muted/60 px-2.5 py-2 text-[12px] text-muted-foreground">
              Na koncie są też dokumenty płacowe — karta i salda są bez nich. Pełne kwoty widzą Płace i administrator.
            </p>
          ) : null}
          <div className="max-h-[480px] overflow-y-auto">
            <table className="w-full table-fixed text-[12.5px]">
              <thead className="sticky top-0 bg-card">
                <tr className="border-y border-border/70">
                  <th className={cn(CALM_HEAD, "w-[22%] px-3.5 py-1.5 text-left")}>Poz. · data</th>
                  <th className={cn(CALM_HEAD, "px-1 py-1.5 text-left")}>Dokument</th>
                  <th className={cn(CALM_HEAD, "w-[19%] px-1 py-1.5 text-right")}>Wn</th>
                  <th className={cn(CALM_HEAD, "w-[19%] px-3.5 py-1.5 text-right")}>Ma</th>
                </tr>
              </thead>
              <tbody>
                {card.data.items.map((line, index) => (
                  <tr key={`${line.document_id}-${index}`} className={cn(CALM_ROW, "align-top")}>
                    <td className="px-3.5 py-1.5 tabular-nums">
                      {line.journal_no}
                      <span className={CALM_SUBLINE}>{datePl(line.op_date)}</span>
                    </td>
                    <td className="min-w-0 px-1 py-1.5">
                      <span className="block truncate">{line.number}</span>
                      <span className={cn(CALM_SUBLINE, "truncate")}>
                        {line.account !== account ? `${line.account} · ` : ""}
                        {line.description}
                      </span>
                    </td>
                    <td className={cn(CALM_AMOUNT, "px-1 py-1.5")}>{line.wn ? gr(line.wn) : <span className={CALM_EMPTY}>—</span>}</td>
                    <td className={cn(CALM_AMOUNT, "px-3.5 py-1.5")}>{line.ma ? gr(line.ma) : <span className={CALM_EMPTY}>—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {card.data.items.length === 0 ? (
              <p className="px-3.5 py-4 text-sm text-muted-foreground">Brak zapisów w tym okresie.</p>
            ) : null}
            {card.data.truncated ? (
              <p className="px-3.5 py-2 text-[12px] text-muted-foreground">Pokazano pierwsze 2000 zapisów — zawęź okres.</p>
            ) : null}
          </div>
        </>
      )}
    </aside>
  );
}
