"use client";

import { useState } from "react";

import { InlineStats } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import {
  downloadPayrollFile,
  payrollPaths,
  useSetGrossInput,
  type PayrollLine,
  type PayrollList,
  type PayrollMonth,
} from "@/lib/api/payroll-lists";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";

import {
  FILE_FIELD_LABELS,
  SETTLEMENT_STATUS,
  SOURCE_LABELS,
  amountInput,
  breakdown,
  grosze,
  inputBody,
  inputFor,
  parseGross,
  personSubline,
  quantity,
  zl,
} from "./payroll-model";

const CONTROL = "h-8 w-full rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const SECTION_TITLE = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

/**
 * Pozycja listy płac: skąd kwota, pełne rozpisanie (składki, podatek, PPK,
 * pracodawca), uwagi silnika i problemy. W szkicu — „Kwota brutto Rozliczeń”,
 * która zastępuje źródło pozycji przy następnym przeliczeniu.
 */
export function PayrollLinePanel({
  month,
  line,
  onClose,
  onPersonData,
}: {
  month: PayrollMonth;
  line: PayrollLine | null;
  onClose: () => void;
  onPersonData: (line: PayrollLine) => void;
}) {
  const list = month.list;
  return (
    <Sheet
      open={line != null && list != null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent size="md">
        {line && list ? (
          <LineBody key={line.id} month={month} list={list} line={line} onPersonData={onPersonData} />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function facts(line: PayrollLine): [string, string][] {
  const basis = line.basis ?? {};
  const out: [string, string][] = [["Źródło kwoty", line.source_label]];
  if (Number(basis.hours) > 0) {
    const overtime = Number(basis.overtime_hours) > 0 ? `, w tym nadgodziny ${quantity(basis.overtime_hours)} h` : "";
    out.push(["Godziny", `${quantity(basis.hours)} h${overtime}`]);
  }
  if (basis.hourly_rate) out.push(["Stawka", `${zl(basis.hourly_rate)} zł/h`]);
  if (basis.hours_amount) out.push(["Za godziny", `${zl(basis.hours_amount)} zł`]);
  if (grosze(basis.bonus_total)) out.push(["Premie", `${zl(basis.bonus_total)} zł`]);
  if (basis.settlement_status) {
    out.push(["Rozliczenie klienta", SETTLEMENT_STATUS[basis.settlement_status] ?? basis.settlement_status]);
  }
  if (basis.md_charged) out.push(["MD u klienta", quantity(basis.md_charged)]);
  if (line.source === "manual" && basis.note) out.push(["Opis kwoty Rozliczeń", basis.note]);
  if (basis.outside_month) out.push(["Umowa", "zakończona przed tym miesiącem — kwota wpisana przez Rozliczenia"]);
  if (basis.replaced_source) {
    const before = basis.replaced_gross ? ` (${zl(basis.replaced_gross)} zł)` : "";
    out.push(["Zastąpiła", `${SOURCE_LABELS[basis.replaced_source] ?? basis.replaced_source}${before}`]);
  }
  if (line.payee_last4) out.push(["Rachunek do wypłaty", `•••• ${line.payee_last4}`]);
  const missing = (basis.missing_files ?? []).map((code) => FILE_FIELD_LABELS[code] ?? code);
  if (missing.length) out.push(["Brakuje do KEDU i PIT-11", missing.join(", ")]);
  return out;
}

function LineBody({
  month,
  list,
  line,
  onPersonData,
}: {
  month: PayrollMonth;
  list: PayrollList;
  line: PayrollLine;
  onPersonData: (line: PayrollLine) => void;
}) {
  const { showToast } = useToast();
  const [downloading, setDownloading] = useState(false);
  const sections = breakdown(line.result ?? {});
  const withAmount = line.gross != null;

  const downloadSlip = async () => {
    setDownloading(true);
    try {
      await downloadPayrollFile(
        payrollPaths.payslips(list.id, line.id),
        `pasek-${list.number.replaceAll("/", "-")}.pdf`,
      );
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się pobrać paska."), "error");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <>
      <SheetHeader className="pr-12">
        <SheetTitle className="truncate">{line.person_name}</SheetTitle>
        <SheetDescription>
          {personSubline(line)} · lista {list.number}
        </SheetDescription>
      </SheetHeader>
      <SheetBody className="space-y-4 text-[13px]">
        {line.problems.length ? (
          <ul aria-label="Problemy pozycji" className="space-y-1">
            {line.problems.map((problem) => (
              <li key={problem.code} className="flex items-start gap-2">
                <span
                  aria-hidden
                  className={cn("mt-[7px] size-1.5 shrink-0 rounded-full", problem.blocking ? "bg-destructive" : "bg-warning")}
                />
                <span className="min-w-0 break-words">
                  {problem.label}
                  {problem.blocking ? <span className="ml-1 text-[11.5px] text-destructive">blokuje zatwierdzenie</span> : null}
                </span>
              </li>
            ))}
          </ul>
        ) : null}

        {withAmount ? (
          <InlineStats
            stats={[
              { id: "gross", label: "Brutto", value: `${zl(line.gross)} zł` },
              { id: "net", label: "Do wypłaty", value: `${zl(line.net)} zł` },
              { id: "cost", label: "Koszt pracodawcy", value: `${zl(line.employer_cost)} zł` },
            ]}
          />
        ) : (
          <p className="rounded-md bg-muted/60 px-3 py-2 text-muted-foreground">
            Pozycja bez kwoty — lista jej nie policzy, dopóki nie przyjdzie rozliczenie albo Rozliczenia nie wpiszą kwoty brutto.
          </p>
        )}

        <section>
          <h3 className={SECTION_TITLE}>Podstawa</h3>
          <dl className="mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
            {facts(line).map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="min-w-0 break-words">{value}</dd>
              </div>
            ))}
          </dl>
        </section>

        {sections.length ? (
          <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
            {sections.map((section) => (
              <section key={section.title}>
                <h3 className={SECTION_TITLE}>{section.title}</h3>
                <dl className="mt-1 divide-y divide-border/60">
                  {section.rows.map((row) => (
                    <div key={row.label} className="flex items-baseline justify-between gap-3 py-1">
                      <dt className={row.strong ? "font-medium" : "text-muted-foreground"}>{row.label}</dt>
                      <dd className={cn("shrink-0 tabular-nums", row.strong && "font-semibold")}>{row.value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
          </div>
        ) : null}

        {line.notes.length ? (
          <section>
            <h3 className={SECTION_TITLE}>Uwagi do wyliczenia</h3>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-muted-foreground">
              {line.notes.map((note) => (
                <li key={note.code}>{note.label}</li>
              ))}
            </ul>
          </section>
        ) : null}

        {list.status === "draft" ? <GrossInputForm month={month} line={line} /> : null}
      </SheetBody>
      <SheetFooter>
        <Button size="sm" variant="outline" onClick={() => onPersonData(line)}>
          Dane płacowe osoby
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={!withAmount}
          title={withAmount ? undefined : "Pozycja bez kwoty nie ma paska"}
          loading={downloading}
          onClick={() => void downloadSlip()}
        >
          Pasek PDF
        </Button>
      </SheetFooter>
    </>
  );
}

/** Kwota brutto Rozliczeń na ten miesiąc — zastępuje źródło pozycji (wymaga opisu). */
function GrossInputForm({ month, line }: { month: PayrollMonth; line: PayrollLine }) {
  const { showToast } = useToast();
  const save = useSetGrossInput();
  const current = inputFor(line, month.inputs);
  const [gross, setGross] = useState(current ? amountInput(current.gross) : "");
  const [fund, setFund] = useState(current?.fund_basis ? amountInput(current.fund_basis) : "");
  const [note, setNote] = useState(current?.note ?? "");
  const parsed = parseGross(gross);
  const fundParsed = fund.trim() ? parseGross(fund) : null;
  const fundOk = !fund.trim() || fundParsed != null;
  const noteOk = note.trim().length >= 3;
  const ready = parsed != null && noteOk && fundOk;
  // Fundusz Pracy dotyczy umowy o pracę i zlecenia — dzieło go nie ma.
  const withFund = line.kind !== "dzielo";

  const submit = (value: string | null) => {
    const body = inputBody(line, value, value != null ? note.trim() : undefined, withFund ? fundParsed : null);
    if (!body) return;
    save.mutate(
      { year: month.year, month: month.month, body },
      {
        onSuccess: () =>
          showToast(
            value == null
              ? "Usunięto kwotę Rozliczeń — przelicz listę, żeby wrócić do źródła."
              : "Zapisano kwotę Rozliczeń — przelicz listę, żeby ją uwzględnić.",
          ),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać kwoty."), "error"),
      },
    );
  };

  return (
    <section className="space-y-2 rounded-md border border-border px-3 py-2.5">
      <div>
        <h3 className={SECTION_TITLE}>Kwota brutto Rozliczeń</h3>
        <p className="mt-0.5 text-[12px] leading-5 text-muted-foreground">
          Zastępuje kwotę ze źródła w tym miesiącu (np. brak stawki, rozliczenie w walucie). 0 = osoba pominięta.
          {current?.entered_at ? ` Wpisana ${current.entered_at.slice(0, 10).split("-").reverse().join(".")}.` : ""}
        </p>
      </div>
      <div className="grid gap-2 sm:grid-cols-[10rem_minmax(0,1fr)]">
        <label className="grid gap-1">
          <span className="text-[12px] font-medium">Brutto, zł</span>
          <input
            aria-label="Kwota brutto Rozliczeń"
            inputMode="decimal"
            className={cn(CONTROL, "text-right tabular-nums")}
            placeholder="0,00"
            value={gross}
            onChange={(event) => setGross(event.target.value)}
          />
        </label>
        <label className="grid gap-1">
          <span className="text-[12px] font-medium">Skąd kwota</span>
          <Textarea
            aria-label="Opis kwoty Rozliczeń"
            rows={2}
            className="min-h-[2.5rem]"
            placeholder="np. stawka z aneksu do umowy"
            maxLength={500}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
      </div>
      {withFund ? (
        <label className="grid gap-1 sm:grid-cols-[10rem_minmax(0,1fr)] sm:items-start sm:gap-x-2">
          <span className="grid gap-1">
            <span className="text-[12px] font-medium">Podstawa do FP, zł</span>
            <input
              aria-label="Podstawa do Funduszu Pracy"
              inputMode="decimal"
              className={cn(CONTROL, "text-right tabular-nums")}
              placeholder="jak brutto"
              value={fund}
              onChange={(event) => setFund(event.target.value)}
            />
          </span>
          <span className="text-[11.5px] leading-4 text-muted-foreground sm:pt-6">
            Podstawa do Funduszu Pracy w przeliczeniu na pełny miesiąc — np. pełna pensja, gdy brutto to pół miesiąca
            L4. Puste = kwota brutto.
          </span>
        </label>
      ) : null}
      {(gross.trim() && parsed == null) || !fundOk ? (
        <p className="text-[12px] text-destructive">Kwota: od 0 do 10 000 000 zł, najwyżej dwa miejsca po przecinku.</p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          disabled={!ready}
          title={ready ? undefined : "Podaj kwotę i opisz, skąd jest (co najmniej 3 znaki)"}
          loading={save.isPending}
          onClick={() => submit(parsed)}
        >
          Zapisz kwotę
        </Button>
        {current ? (
          <Button size="sm" variant="quiet" disabled={save.isPending} onClick={() => submit(null)}>
            Usuń wpis
          </Button>
        ) : null}
      </div>
    </section>
  );
}
