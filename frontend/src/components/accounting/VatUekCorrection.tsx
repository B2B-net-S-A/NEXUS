"use client";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useVatUek, vatUekFilePath, type VatUekPeriod } from "@/lib/api/accounting-vat";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { gr } from "./ledger-model";

function label(year: number, month: number): string {
  return `${String(month).padStart(2, "0")}.${year}`;
}

function amount(value: number | null): string {
  return value === null ? "—" : gr(value * 100);
}

/**
 * VAT-UEK(5) za jeden wcześniejszy okres z korekt miesiąca karty (K5b-3c).
 * „Było” = VAT-UE tamtego okresu z rejestru wraz z korektami z miesięcy przed
 * miesiącem korekt (decyzja Artura 16.11.2026), „jest” = po korektach z tego
 * miesiąca. Plik serwer składa i sprawdza schematem MF przy pobraniu.
 */
export function VatUekCorrection({ period, documents }: { period: VatUekPeriod; documents: string[] }) {
  const { showToast } = useToast();
  const overview = useVatUek(period);
  const name = label(period.year, period.month);
  const fileName = `VAT-UEK_${period.year}-${String(period.month).padStart(2, "0")}_korekty_${period.issuedYear}-${String(period.issuedMonth).padStart(2, "0")}.xml`;
  const download = async () => {
    try {
      await downloadAuthenticatedFile(vatUekFilePath(period), fileName);
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się pobrać pliku VAT-UEK."), "error");
    }
  };
  return (
    <section aria-label={`VAT-UEK za ${name}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-3.5 pb-1 pt-2.5">
        <h3 className="text-[13px] font-medium">VAT-UEK za {name}</h3>
        <span className="text-[12px] text-muted-foreground">korekty: {documents.join(", ")}</span>
      </div>
      {overview.isError ? (
        <div className="px-3.5 pb-2.5">
          <QueryStateNotice state="error" onRetry={() => overview.refetch()} />
        </div>
      ) : !overview.isSuccess ? (
        <p className="px-3.5 pb-2.5 text-[13px] text-muted-foreground">Liczę pozycje korekty…</p>
      ) : (
        <>
          {overview.data.missing.length ? (
            <p className="px-3.5 pb-1.5 text-[13px] text-warning-muted-foreground">
              Do VAT-UEK brakuje: {overview.data.missing.join("; ")}.
            </p>
          ) : null}
          {overview.data.problems.length ? (
            <ul className="space-y-0.5 px-3.5 pb-1.5 text-[13px] text-destructive">
              {overview.data.problems.map((item, index) => (
                <li key={`${item.number}:${index}`}>
                  <span className="font-medium">{item.number}</span> — {item.detail}
                </li>
              ))}
            </ul>
          ) : null}
          {overview.data.lines.length ? (
            <table className="w-full table-fixed text-sm">
              <thead>
                <tr className="border-b border-border/70">
                  <th className={cn(CALM_HEAD, "px-3.5 py-1.5 text-left")}>Kontrahent</th>
                  <th className={cn(CALM_HEAD, "w-[26%] px-2 py-1.5 text-left")}>Sekcja</th>
                  <th className={cn(CALM_HEAD, "w-[15%] px-2 py-1.5 text-right")}>Było zł</th>
                  <th className={cn(CALM_HEAD, "w-[15%] py-1.5 pl-2 pr-3.5 text-right")}>Jest zł</th>
                </tr>
              </thead>
              <tbody>
                {overview.data.lines.map((line) => (
                  <tr key={`${line.section}:${line.country}${line.number}`} className={cn(CALM_ROW, "last:border-0")}>
                    <td className="min-w-0 px-3.5 py-1.5">
                      <span className="block truncate">{line.name || "—"}</span>
                      <span className={CALM_SUBLINE}>{`${line.country} ${line.number}`}</span>
                    </td>
                    <td className="min-w-0 px-2 py-1.5 text-[13px]">
                      <span className="block truncate">{line.section_label}</span>
                    </td>
                    <td className={cn(CALM_AMOUNT, "px-2 py-1.5 text-right")}>{amount(line.before)}</td>
                    <td className={cn(CALM_AMOUNT, "py-1.5 pl-2 pr-3.5 text-right")}>{amount(line.after)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : !overview.data.problems.length ? (
            <p className="px-3.5 pb-1.5 text-[13px] text-muted-foreground">
              Korekty nie zmieniają kwot VAT-UE za {name} w pełnych złotych — VAT-UEK nie trzeba składać.
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2.5 px-3.5 py-2 text-[12px]">
            <Button size="sm" variant="outline" disabled={!overview.data.can_download} onClick={download}>
              Pobierz VAT-UEK za {name} (XML)
            </Button>
            {overview.data.blockers.length ? (
              <p className="text-warning-muted-foreground">
                Plik powstanie po zamknięciu listy „Do sprawdzenia”: {overview.data.blockers.join("; ")}.
              </p>
            ) : null}
            {overview.data.lines.some((line) => line.before === null || line.after === null) ? (
              <p className="text-muted-foreground">
                „—” w „Było” = kontrahent dopisany, w „Jest” = kontrahent znika z informacji.
              </p>
            ) : null}
            {overview.data.earlier_months.length ? (
              <p className="text-muted-foreground">
                „Było” obejmuje korekty z{" "}
                {overview.data.earlier_months
                  .map((item) => {
                    const [year, month] = item.split("-");
                    return `${month}.${year}`;
                  })
                  .join(", ")}
                .
              </p>
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}
