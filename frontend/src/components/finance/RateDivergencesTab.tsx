"use client";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useRateDivergences, type RateDivergence } from "@/lib/api/rate-divergences";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatMomentPl, monthTitlePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";

const rowKey = (row: RateDivergence) => `${row.person}|${row.order_number}|${row.leg}`;

/** Finanse → „Rozjazdy stawek”: lista z nocnego raportu. Tylko odczyt, bez poprawek. */
export function RateDivergencesTab() {
  const report = useRateDivergences();

  if (report.isLoading) {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie raportu…</p>;
  }
  if (report.isError) {
    return <QueryStateNotice state="error" onRetry={() => report.refetch()} />;
  }
  const data = report.data;
  if (!data) return null;
  if (data.generated_at === null) {
    return (
      <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        Raport jeszcze nie powstał. Pierwszy przebieg jest w nocy po wdrożeniu.
      </div>
    );
  }
  const real = data.rows.filter((row) => !row.rounding).length;
  const rounding = data.rows.length - real;
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Stan z {formatMomentPl(data.generated_at)} · {data.month ? monthTitlePl(data.month) : "—"} ·{" "}
        {countPl(real, "rozjazd", "rozjazdy", "rozjazdów")}
        {rounding > 0
          ? ` · ${countPl(rounding, "zaokrąglenie", "zaokrąglenia", "zaokrągleń")} stawki godzinowej`
          : ""}
        {data.skipped.no_contract_rate > 0
          ? ` · bez stawki w kontrakcie: ${data.skipped.no_contract_rate}`
          : ""}
        {data.skipped.other_currency > 0
          ? ` · inna waluta: ${data.skipped.other_currency}`
          : ""}
      </p>
      {data.rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          W tym miesiącu stawki kontraktów i zamówień są zgodne.
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card">
          <Table density="compact" className="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className={`${CALM_HEAD} w-[23%]`}>Osoba</TableHead>
                <TableHead className={`${CALM_HEAD} w-[23%]`}>Klient i zamówienie</TableHead>
                <TableHead className={`${CALM_HEAD} w-[10%]`}>Stawka</TableHead>
                <TableHead className={`${CALM_HEAD} w-[12%] text-right`}>Kontrakt /MD</TableHead>
                <TableHead className={`${CALM_HEAD} w-[12%] text-right`}>Zamówienie /MD</TableHead>
                <TableHead className={`${CALM_HEAD} w-[10%] text-right`}>Różnica /MD</TableHead>
                <TableHead className={`${CALM_HEAD} w-[10%] text-right`}>W miesiącu</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.rows.map((row) => (
                <TableRow key={rowKey(row)} className={`${CALM_ROW} align-top`}>
                  <TableCell className="min-w-0">
                    <span className="block truncate">{row.person}</span>
                    {row.rounding ? (
                      <span className={CALM_SUBLINE}>zaokrąglenie stawki godzinowej</span>
                    ) : null}
                  </TableCell>
                  <TableCell className="min-w-0">
                    <a className="block truncate text-primary hover:underline" href={row.link}>
                      {row.client_name}
                    </a>
                    <span className={`${CALM_SUBLINE} truncate`}>{row.order_number}</span>
                  </TableCell>
                  <TableCell className="text-sm">{row.leg_label}</TableCell>
                  <TableCell className={CALM_AMOUNT}>
                    {formatMoney(row.contract_rate, row.currency)}
                  </TableCell>
                  <TableCell className={CALM_AMOUNT}>
                    {formatMoney(row.order_rate, row.currency)}
                  </TableCell>
                  <TableCell className={CALM_AMOUNT}>
                    {formatMoney(row.difference, row.currency)}
                  </TableCell>
                  <TableCell className={CALM_AMOUNT}>
                    {row.effect ? formatMoney(row.effect, row.currency) : "—"}
                    {row.md ? <span className={CALM_SUBLINE}>{row.md} MD</span> : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
