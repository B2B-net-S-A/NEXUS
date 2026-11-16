"use client";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useVatUe, vatUeFilePath } from "@/lib/api/accounting-vat";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard } from "./AccountingShell";
import { gr, MONTHS_PL } from "./ledger-model";
import { VatUekCorrection } from "./VatUekCorrection";

const NOTE = "px-3.5 py-2.5 text-[13px] text-muted-foreground";

/**
 * VAT-UE(5) miesiąca (K5b-3a): kontrahenci z UE z rejestru sprzedaży (usługi
 * np II i WDT) z kwotą w pełnych złotych. Plik serwer składa i sprawdza
 * schematem MF przy pobraniu; NEXUS niczego nie wysyła. Korekty faktur
 * z wcześniejszych okresów idą na VAT-UEK za tamte okresy (K5b-3c) — lista
 * „Do VAT-UEK” z plikiem per okres.
 */
export function VatUeCard({ year, month }: { year: number; month: number }) {
  const { showToast } = useToast();
  const overview = useVatUe(year, month);
  if (overview.isError) {
    return (
      <SectionCard title="VAT-UE">
        <div className="p-3.5">
          <QueryStateNotice state="error" onRetry={() => overview.refetch()} />
        </div>
      </SectionCard>
    );
  }
  if (!overview.isSuccess) return null;
  const data = overview.data;
  const download = async () => {
    try {
      await downloadAuthenticatedFile(vatUeFilePath(year, month), `VAT-UE_${year}-${String(month).padStart(2, "0")}.xml`);
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się pobrać pliku VAT-UE."), "error");
    }
  };
  // Korekty wcześniejszych okresów: VAT-UEK per okres faktury pierwotnej.
  // Okres nie wcześniejszy niż miesiąc karty (korekta sprzed daty sprzedaży
  // faktury pierwotnej) zostaje na liście problemów — VAT-UEK go nie obejmie.
  const current = `${year}-${String(month).padStart(2, "0")}`;
  const toUek = (item: (typeof data.problems)[number]) =>
    item.kind === "earlier" && !!item.period && item.period < current;
  const uek = new Map<string, string[]>();
  for (const item of data.problems) {
    if (toUek(item) && item.period) uek.set(item.period, [...(uek.get(item.period) ?? []), item.number]);
  }
  const problems = data.problems.filter((item) => !toUek(item));
  const empty = !data.lines.length && !data.problems.length;
  return (
    <SectionCard
      title={`VAT-UE za ${MONTHS_PL[month - 1]?.toLowerCase() ?? month} ${year}`}
      aside="informacja podsumowująca · termin 25."
    >
      {data.missing.length ? (
        <p className="border-b border-border/70 px-3.5 py-2 text-[13px] text-warning-muted-foreground">
          Do VAT-UE brakuje: {data.missing.join("; ")}.
        </p>
      ) : null}
      {problems.length ? (
        <ul className="space-y-0.5 border-b border-border/70 px-3.5 py-2 text-[13px]">
          {problems.map((item, index) => (
            <li
              key={`${item.number}:${index}`}
              className={item.kind === "earlier" ? "text-warning-muted-foreground" : "text-destructive-text"}
            >
              <span className="font-medium">{item.number}</span> — {item.detail}
            </li>
          ))}
        </ul>
      ) : null}
      {data.lines.length ? (
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-border/70">
              <th className={cn(CALM_HEAD, "px-3.5 py-2 text-left")}>Kontrahent</th>
              <th className={cn(CALM_HEAD, "w-[26%] px-2 py-2 text-left")}>Sekcja</th>
              <th className={cn(CALM_HEAD, "w-[12%] px-2 py-2 text-right")}>Faktury</th>
              <th className={cn(CALM_HEAD, "w-[16%] py-2 pl-2 pr-3.5 text-right")}>Kwota zł</th>
            </tr>
          </thead>
          <tbody>
            {data.lines.map((line) => (
              <tr key={`${line.section}:${line.country}${line.number}`} className={cn(CALM_ROW, "last:border-0")}>
                <td className="min-w-0 px-3.5 py-1.5">
                  <span className="block truncate">{line.name || "—"}</span>
                  <span className={CALM_SUBLINE}>{`${line.country} ${line.number}`}</span>
                </td>
                <td className="min-w-0 px-2 py-1.5 text-[13px]">
                  <span className="block truncate">{line.section_label}</span>
                </td>
                <td className="px-2 py-1.5 text-right text-[13px] tabular-nums" title={line.documents.join(", ")}>
                  {line.documents_count}
                </td>
                <td className={cn(CALM_AMOUNT, "py-1.5 pl-2 pr-3.5 text-right")}>{gr(line.amount * 100)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : empty ? (
        <p className={NOTE}>W tym miesiącu nie ma usług dla podatników z UE ani WDT — VAT-UE się nie składa.</p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2.5 border-t border-border/70 px-3.5 py-2.5 text-[13px]">
        <Button size="sm" variant="outline" disabled={!data.can_download} onClick={download}>
          Pobierz VAT-UE (XML)
        </Button>
        {data.blockers.length ? (
          <p className="text-[12px] text-warning-muted-foreground">
            VAT-UE powstanie po zamknięciu listy „Do sprawdzenia”: {data.blockers.join("; ")}.
          </p>
        ) : null}
      </div>
      {uek.size ? (
        <div className="border-t border-border/70">
          <p className="px-3.5 pt-2.5 text-[12px] font-medium uppercase tracking-wide text-muted-foreground">
            Do VAT-UEK
          </p>
          <div className="divide-y divide-border/70">
            {[...uek.entries()]
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([period, documents]) => {
                const [periodYear, periodMonth] = period.split("-").map(Number);
                return (
                  <VatUekCorrection
                    key={period}
                    period={{ year: periodYear, month: periodMonth, issuedYear: year, issuedMonth: month }}
                    documents={documents}
                  />
                );
              })}
          </div>
        </div>
      ) : null}
      {data.notes.length ? (
        <ul className="space-y-0.5 border-t border-border/70 px-3.5 py-2 text-[12px] text-muted-foreground">
          {data.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </SectionCard>
  );
}
