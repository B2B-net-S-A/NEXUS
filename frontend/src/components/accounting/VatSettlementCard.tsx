"use client";

import Link from "next/link";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  usePrepareVatSettlement,
  useVatSettlement,
  type VatSettlement,
  type VatSettlementOutcome,
} from "@/lib/api/accounting-vat";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard } from "./AccountingShell";
import { gr, MONTHS_PL } from "./ledger-model";

const NOTE = "px-3.5 py-2.5 text-[13px] text-muted-foreground";

const OUTCOMES: Record<VatSettlementOutcome, string> = {
  created: "Dokument rozliczenia VAT jest w buforze.",
  rebuilt: "Szkic rozliczenia VAT przeliczony na nowo.",
  unchanged: "Szkic rozliczenia VAT bez zmian.",
  removed: "Miesiąc nie ma kwot — szkic usunięty.",
  approved: "Rozliczenie VAT jest już zatwierdzone.",
  none: "Miesiąc nie ma kwot do rozliczenia.",
};

/** Stan karty jednym zdaniem: co z dokumentem rozliczenia miesiąca. */
export function settlementState(data: VatSettlement): { text: string; tone: "ok" | "todo" | "problem" } {
  const doc = data.document;
  if (data.problem) return { text: data.problem, tone: "problem" };
  if (data.changed && doc) {
    return {
      text: `${doc.number} jest zatwierdzony, a z JPK wychodzą dziś inne kwoty — zrób storno i przygotuj rozliczenie ponownie.`,
      tone: "problem",
    };
  }
  if (data.blocker) return { text: data.blocker, tone: "todo" };
  if (doc && doc.status !== "approved" && data.stale_draft) {
    return { text: `${doc.number} w buforze jest nieaktualny — przelicz go przed zatwierdzeniem.`, tone: "todo" };
  }
  if (doc && doc.status !== "approved") {
    const who = doc.payroll ? " — dokument obejmuje faktury osób zespołu, zatwierdza osoba z Płacami" : "";
    return { text: `${doc.number} w buforze — zatwierdza lista „Księgowi”${who}.`, tone: "todo" };
  }
  if (doc) return { text: `${doc.number} zatwierdzony.`, tone: "ok" };
  if (!data.to_book) return { text: "Miesiąc nie ma kwot do rozliczenia.", tone: "ok" };
  return { text: "Dokument jeszcze nie powstał.", tone: "todo" };
}

/** Saldo deklaracji miesiąca (pełne złote) jak w JPK: do zapłaty albo nadwyżka. */
export function dueText(due: number | null): string {
  if (due == null) return "—";
  return due >= 0 ? `do zapłaty ${gr(due * 100)} zł` : `nadwyżka naliczonego ${gr(-due * 100)} zł`;
}

/**
 * Rozliczenie VAT miesiąca z nagłówka (K5b-3c): dokument typu VAT z kwot JPK —
 * VAT należny i naliczony na „VAT do zapłaty”, grosze na konta różnic
 * z zaokrągleń. Przed dokumentem obroty kont VAT z księgi muszą zgadzać się
 * z JPK. Kwoty widzi osoba z Płacami (D2), reszta — stan dokumentu.
 */
export function VatSettlementCard({ year, month }: { year: number; month: number }) {
  const { showToast } = useToast();
  const settlement = useVatSettlement(year, month);
  const prepare = usePrepareVatSettlement();
  if (settlement.isError) {
    return (
      <SectionCard title="Rozliczenie VAT">
        <div className="p-3.5">
          <QueryStateNotice state="error" onRetry={() => settlement.refetch()} />
        </div>
      </SectionCard>
    );
  }
  if (!settlement.isSuccess) return null;
  const data = settlement.data;
  const state = settlementState(data);
  const approved = data.document?.status === "approved";
  // Zatwierdzonego się nie podmienia — po korekcie JPK najpierw storno (serwer: 409).
  const ready = data.can_prepare && !data.blocker && !data.problem && !approved;
  return (
    <SectionCard
      title={`Rozliczenie VAT za ${MONTHS_PL[month - 1]?.toLowerCase() ?? month} ${year}`}
      aside={data.jpk ? `z JPK v${data.jpk.version}${data.jpk.status === "sent" ? " (wysłany)" : ""}` : "z JPK miesiąca"}
    >
      <p
        className={cn(
          "border-b border-border/70 px-3.5 py-2 text-[13px]",
          state.tone === "problem" && "text-destructive",
          state.tone === "todo" && "text-warning-muted-foreground",
          state.tone === "ok" && "text-success-muted-foreground",
        )}
      >
        {state.text}
        {data.document ? (
          <>
            {" "}
            <Link
              className="underline underline-offset-2"
              href={`/accounting/documents?year=${year}&month=${month}&status=${data.document.status}`}
            >
              Pokaż w Dokumentach
            </Link>
          </>
        ) : null}
      </p>
      {data.amounts ? <Amounts data={data} /> : <p className={NOTE}>Kwoty rozliczenia widzi osoba z Płacami — obejmują faktury osób zespołu.</p>}
      {data.can_prepare ? (
        <div className="flex flex-wrap items-center gap-2.5 border-t border-border/70 px-3.5 py-2.5">
          <Button
            size="sm"
            disabled={!ready}
            loading={prepare.isPending}
            onClick={() =>
              prepare.mutate(
                { year, month },
                {
                  onSuccess: (result) => showToast(OUTCOMES[result.outcome]),
                  onError: (error) => showToast(apiErrorMessage(error, "Nie udało się przygotować rozliczenia VAT."), "error"),
                },
              )
            }
          >
            {data.document && !approved ? "Przelicz rozliczenie VAT" : "Przygotuj rozliczenie VAT"}
          </Button>
          <span className="text-[12px] text-muted-foreground">
            Dokument trafia do bufora z datą {data.day.split("-").reverse().join(".")}; 221 i 222 zerują się, saldo
            idzie na „VAT do zapłaty”.
          </span>
        </div>
      ) : null}
    </SectionCard>
  );
}

function Amounts({ data }: { data: VatSettlement }) {
  const amounts = data.amounts!;
  return (
    <>
      <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 px-3.5 py-2.5 text-[13px]">
        <dt className="text-muted-foreground">VAT należny — księga / JPK</dt>
        <dd className="tabular-nums">
          {gr(amounts.ledger_output)} / {gr(amounts.output_tax)} zł
        </dd>
        <dt className="text-muted-foreground">VAT naliczony — księga / JPK</dt>
        <dd className="tabular-nums">
          {gr(amounts.ledger_input)} / {gr(amounts.input_tax)} zł
        </dd>
        <dt className="text-muted-foreground">Deklaracja (bez nadwyżki z poprzedniego okresu)</dt>
        <dd className="tabular-nums">{dueText(amounts.due)}</dd>
        <dt className="text-muted-foreground">Różnica z zaokrągleń</dt>
        <dd className="tabular-nums">
          {amounts.rounding == null
            ? "—"
            : amounts.rounding === 0
              ? "brak"
              : `${gr(Math.abs(amounts.rounding))} zł ${amounts.rounding > 0 ? "koszt" : "przychód"}`}
        </dd>
      </dl>
      {data.lines.length ? (
        <table className="w-full table-fixed border-t border-border/70 text-sm">
          <thead>
            <tr className="border-b border-border/70">
              <th className={cn(CALM_HEAD, "w-[14%] px-3.5 py-2 text-left")}>Strona</th>
              <th className={cn(CALM_HEAD, "px-2 py-2 text-left")}>Konto</th>
              <th className={cn(CALM_HEAD, "w-[30%] py-2 pl-2 pr-3.5 text-right")}>Kwota</th>
            </tr>
          </thead>
          <tbody>
            {data.lines.map((line) => (
              <tr key={`${line.side}-${line.account}`} className={cn(CALM_ROW, "last:border-0")}>
                <td className="px-3.5 py-1.5 text-[13px]">{line.side === "debit" ? "Wn" : "Ma"}</td>
                <td className="min-w-0 px-2 py-1.5">
                  <span className="tabular-nums">{line.account}</span>
                  {line.name ? <span className={cn(CALM_SUBLINE, "truncate")}>{line.name}</span> : null}
                </td>
                <td className={cn(CALM_AMOUNT, "py-1.5 pl-2 pr-3.5")}>{gr(line.amount)} zł</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </>
  );
}
