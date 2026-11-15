"use client";

import { Fragment, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useUpdateAccount } from "@/lib/api/accounting";
import {
  reportKeys,
  useAccountPositions,
  useMarkers,
  useStatements,
  type AccountPosition,
  type Marker,
  type StatementNode,
  type Statements,
} from "@/lib/api/accounting-reports";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard, useAccounting } from "./AccountingShell";
import { MONTHS_PL, findPeriod, gr } from "./ledger-model";
import { SOURCE_LABELS, flattenStatement, reportLine, shortLabel } from "./reports-model";

type View = "balance" | "income" | "positions";
type Scope = "month" | "ytd";

const VIEWS: { key: View; label: string }[] = [
  { key: "balance", label: "Bilans" },
  { key: "income", label: "Rachunek zysków i strat" },
  { key: "positions", label: "Pozycje kont" },
];
const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const CHIP = "inline-flex items-center rounded px-1.5 py-0.5 text-[11.5px] font-medium";

function Amount({ value }: { value: number }) {
  return value ? <>{gr(value)}</> : <span className={CALM_EMPTY}>—</span>;
}

function StatementTable({ rows, title, all }: { rows: StatementNode[]; title: string; all: boolean }) {
  const flat = flattenStatement(rows, all);
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className={CALM_HEAD}>
          <th className="px-3.5 py-2 text-left">{title}</th>
          <th className="px-3.5 py-2 text-right">Kwota</th>
        </tr>
      </thead>
      <tbody>
        {flat.map((row) => (
          <tr
            key={row.key}
            className={cn(CALM_ROW, row.level === 1 && "bg-muted/40 font-semibold", row.computed && "font-semibold")}
          >
            <td className="px-3.5 py-1.5 align-top" style={{ paddingLeft: 14 + (row.level - 1) * 18 }}>
              <span className="mr-2 inline-block min-w-6 text-muted-foreground">{row.number}</span>
              {row.label}
              {row.accounts.length ? (
                <span className={CALM_SUBLINE}>
                  {row.accounts.map((item) => `${item.account} ${gr(item.amount)}`).join(" · ")}
                </span>
              ) : null}
            </td>
            <td className={cn(CALM_AMOUNT, "px-3.5 py-1.5 align-top")}>
              <Amount value={row.amount} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Problems({ data }: { data: Statements }) {
  if (data.complete && !data.warnings.length) return null;
  return (
    <div className="space-y-1 rounded-md border border-warning/40 bg-warning/10 px-3.5 py-2 text-[13px]">
      {data.issues.length ? (
        <p>
          <b>Sprawozdanie niekompletne.</b> Konta bez pozycji w sprawozdaniu (pozycję wskazuje się w „Pozycje kont”):{" "}
          {data.issues.map((item) => `${item.account} — ${item.problem.toLowerCase()} (${gr(item.amount)})`).join("; ")}.
        </p>
      ) : null}
      {data.warnings.map((warning) => (
        <p key={warning.code}>
          {warning.message} Różnica: {gr(warning.amount)}.
        </p>
      ))}
    </div>
  );
}

function MarkerSelect({
  value,
  markers,
  groups,
  onChange,
  label,
  emptyLabel,
}: {
  value: string;
  markers: Marker[];
  groups: Marker["group"][];
  onChange: (code: string) => void;
  label: string;
  emptyLabel: string;
}) {
  const names: Record<Marker["group"], string> = {
    assets: "Aktywa",
    liabilities: "Pasywa",
    result: "Rachunek zysków i strat",
    other: "Inne",
  };
  return (
    <select aria-label={label} className={cn(CONTROL, "w-full max-w-[460px]")} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{emptyLabel}</option>
      {groups.map((group) => (
        <optgroup key={group} label={names[group]}>
          {markers
            .filter((marker) => marker.group === group)
            .map((marker) => (
              <option key={marker.code} value={marker.code}>
                {marker.code} — {marker.label}
              </option>
            ))}
        </optgroup>
      ))}
    </select>
  );
}

function PositionEditor({ row, markers, onDone }: { row: AccountPosition; markers: Marker[]; onDone: () => void }) {
  const [debit, setDebit] = useState(row.position?.debit.code ?? "");
  const [credit, setCredit] = useState(
    row.position && row.position.credit.code !== row.position.debit.code ? row.position.credit.code : "",
  );
  const update = useUpdateAccount();
  const client = useQueryClient();
  const { showToast } = useToast();
  const group = markers.find((marker) => marker.code === debit)?.group;
  const balanceSheet = group === "assets" || group === "liabilities";

  const save = (value: string | null) =>
    update.mutate(
      { id: row.id, changes: { report_line: value } },
      {
        onSuccess: () => {
          void client.invalidateQueries({ queryKey: reportKeys.all });
          onDone();
        },
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać pozycji konta."), "error"),
      },
    );

  return (
    <div className="grid gap-2 py-1">
      <MarkerSelect
        label={`Pozycja konta ${row.number}`}
        value={debit}
        markers={markers}
        groups={["assets", "liabilities", "result", "other"]}
        onChange={setDebit}
        emptyLabel="— wybierz znacznik —"
      />
      {balanceSheet ? (
        <MarkerSelect
          label={`Pozycja salda Ma konta ${row.number}`}
          value={credit}
          markers={markers}
          groups={["assets", "liabilities"]}
          onChange={setCredit}
          emptyLabel="Saldo Ma — ta sama pozycja"
        />
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={!debit || update.isPending} onClick={() => save(reportLine(debit, balanceSheet ? credit : ""))}>
          Zapisz
        </Button>
        {row.report_line ? (
          <Button size="sm" variant="outline" disabled={update.isPending} onClick={() => save(null)}>
            Usuń wpis (wróć do reguły)
          </Button>
        ) : null}
        <Button size="sm" variant="ghost" onClick={onDone}>
          Anuluj
        </Button>
      </div>
    </div>
  );
}

function PositionsView() {
  const positions = useAccountPositions();
  const markers = useMarkers();
  const [editing, setEditing] = useState<number | null>(null);
  const [onlyMissing, setOnlyMissing] = useState(false);
  const rows = useMemo(
    () => (positions.data ?? []).filter((row) => !onlyMissing || row.source === "none"),
    [positions.data, onlyMissing],
  );
  const missing = (positions.data ?? []).filter((row) => row.source === "none").length;

  if (positions.isError || markers.isError) {
    return (
      <QueryStateNotice
        state="error"
        onRetry={() => {
          void positions.refetch();
          void markers.refetch();
        }}
      />
    );
  }
  if (!positions.isSuccess || !markers.isSuccess) {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie planu kont…</p>;
  }
  return (
    <SectionCard
      title="Konta i ich pozycje w sprawozdaniu"
      aside={`${positions.data.length} kont · ${missing} bez pozycji`}
    >
      <div className="flex flex-wrap items-center gap-3 border-b border-border/70 px-3.5 py-2 text-[12.5px] text-muted-foreground">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={onlyMissing} onChange={(e) => setOnlyMissing(e.target.checked)} />
          Tylko konta bez pozycji
        </label>
        <span>
          Pozycja = znacznik MF z JPK_KR_PD. Wpis przy koncie wygrywa z regułą po numerze; rozrachunki mają osobną pozycję dla
          salda Wn i Ma.
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="px-3.5 py-6 text-center text-sm text-muted-foreground">
          {onlyMissing ? "Każde konto ma pozycję." : "Plan kont jest pusty."}
        </p>
      ) : (
        <table className="w-full text-[13px]">
          <thead>
            <tr className={CALM_HEAD}>
              <th className="px-3.5 py-2 text-left">Konto</th>
              <th className="px-3.5 py-2 text-left">Pozycja</th>
              <th className="px-3.5 py-2 text-left">Skąd</th>
              <th className="px-3.5 py-2" />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <Fragment key={row.id}>
                <tr className={cn(CALM_ROW, !row.active && "text-muted-foreground")}>
                  <td className="px-3.5 py-1.5 align-top">
                    <span className="font-mono">{row.number}</span> {row.name}
                  </td>
                  <td className="px-3.5 py-1.5 align-top">
                    {editing === row.id ? (
                      <PositionEditor row={row} markers={markers.data} onDone={() => setEditing(null)} />
                    ) : row.position ? (
                      <>
                        <span title={row.position.debit.label}>
                          <span className="font-mono text-[12px]">{row.position.debit.code}</span>{" "}
                          {shortLabel(row.position.debit.label)}
                        </span>
                        {row.position.credit.code !== row.position.debit.code ? (
                          <span className={CALM_SUBLINE} title={row.position.credit.label}>
                            saldo Ma: <span className="font-mono">{row.position.credit.code}</span>{" "}
                            {shortLabel(row.position.credit.label)}
                          </span>
                        ) : null}
                      </>
                    ) : row.excluded ? (
                      <span className="text-muted-foreground">poza sprawozdaniem — {row.excluded}</span>
                    ) : (
                      <span className="text-destructive-text">bez pozycji</span>
                    )}
                  </td>
                  <td className="px-3.5 py-1.5 align-top whitespace-nowrap">
                    <span
                      className={cn(
                        CHIP,
                        row.source === "none" ? "bg-warning/15 text-warning" : "bg-muted text-muted-foreground",
                      )}
                    >
                      {SOURCE_LABELS[row.source]}
                    </span>
                  </td>
                  <td className="px-3.5 py-1.5 text-right align-top">
                    {editing === row.id || row.excluded ? null : (
                      <Button size="sm" variant="ghost" onClick={() => setEditing(row.id)}>
                        Zmień
                      </Button>
                    )}
                  </td>
                </tr>
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </SectionCard>
  );
}

export function ReportsView() {
  const { config, period } = useAccounting();
  const { year } = findPeriod(config, period);
  const [view, setView] = useState<View>("balance");
  const [scope, setScope] = useState<Scope>("ytd");
  const [all, setAll] = useState(false);
  const from = scope === "month" ? period.month : 1;
  const statements = useStatements(year && view !== "positions" ? period.year : null, from, period.month);
  const data = statements.data;
  const range = from === period.month ? MONTHS_PL[from - 1] : `${MONTHS_PL[from - 1]}–${MONTHS_PL[period.month - 1]}`;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label="Sprawozdanie">
        {VIEWS.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={view === item.key}
            onClick={() => setView(item.key)}
            className={cn(
              "h-8 rounded-md border px-3 text-[13px]",
              view === item.key ? "border-primary bg-primary/10 font-medium" : "border-border bg-background",
            )}
          >
            {item.label}
          </button>
        ))}
        {view !== "positions" ? (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {view === "income" ? (
              <select aria-label="Zakres" value={scope} onChange={(e) => setScope(e.target.value as Scope)} className={CONTROL}>
                <option value="ytd">Od stycznia do wybranego miesiąca</option>
                <option value="month">Wybrany miesiąc</option>
              </select>
            ) : null}
            <label className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
              <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
              Wszystkie pozycje
            </label>
          </div>
        ) : null}
      </div>

      {view === "positions" ? (
        <PositionsView />
      ) : !year ? (
        <p className="rounded-lg border border-dashed border-border px-6 py-10 text-center text-sm text-muted-foreground">
          Nie ma roku obrotowego {period.year}.
        </p>
      ) : statements.isError ? (
        <QueryStateNotice state="error" onRetry={() => statements.refetch()} />
      ) : !statements.isSuccess || !data ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie sprawozdania…</p>
      ) : (
        <>
          <Problems data={data} />
          {view === "balance" ? (
            <div className="grid gap-3 lg:grid-cols-2">
              <SectionCard title={`Aktywa na koniec: ${MONTHS_PL[period.month - 1]} ${period.year}`}>
                <StatementTable rows={data.balance.assets} title="Pozycja" all={all} />
                <p className="flex justify-between border-t border-border px-3.5 py-2 text-[13px] font-semibold">
                  <span>Aktywa razem</span>
                  <span className="tabular-nums">{gr(data.balance.assets_total)}</span>
                </p>
              </SectionCard>
              <SectionCard
                title="Pasywa"
                aside={
                  <span className={data.balance.balanced ? "text-success" : "text-destructive-text"}>
                    {data.balance.balanced ? "aktywa = pasywa" : "aktywa ≠ pasywa"}
                  </span>
                }
              >
                <StatementTable rows={data.balance.liabilities} title="Pozycja" all={all} />
                <p className="flex justify-between border-t border-border px-3.5 py-2 text-[13px] font-semibold">
                  <span>Pasywa razem</span>
                  <span className="tabular-nums">{gr(data.balance.liabilities_total)}</span>
                </p>
              </SectionCard>
            </div>
          ) : (
            <SectionCard
              title={`Rachunek zysków i strat — wariant porównawczy · ${range} ${period.year}`}
              aside="załącznik nr 1 do ustawy o rachunkowości"
            >
              <StatementTable rows={data.income.lines} title="Pozycja" all={all} />
            </SectionCard>
          )}
          <p className="text-[12.5px] text-muted-foreground">
            Z zatwierdzonych zapisów księgi. Dopóki rok jest w trybie „Symfonia”, sprawozdanie urzędowe robi Symfonia — to
            zestawienie służy do porównania.
          </p>
        </>
      )}
    </div>
  );
}
