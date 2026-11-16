"use client";

import { useState } from "react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useBasisHistory,
  useImportBasisHistory,
  useMonthAbsences,
  useSalaries,
  useSetAbsenceMark,
  useSetComponent,
  useSetSalary,
  type ComponentKind,
  type HistoryImport,
  type MonthAbsence,
  type SickRate,
} from "@/lib/api/payroll-k7b";
import { usePayrollMonth } from "@/lib/api/payroll-lists";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard } from "../AccountingShell";
import { datePl } from "../ledger-model";
import {
  COMPONENT_KINDS,
  COMPONENT_SHORT,
  SICK_RATE_OPTIONS,
  componentFor,
  firstOfMonth,
  fteLabel,
  monthOf,
  parseFte,
  parseSalary,
  salaryHistory,
  salaryOn,
} from "./k7b-model";
import { amountInput, parseGross, periodLabel, plural, zl } from "./payroll-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";

/**
 * „Pensje i nieobecności” (K7b): pensje osób na UoP z historią, nieobecności
 * miesiąca z modułu urlopów z oznaczeniem L4 (80/100%, zasiłek ZUS),
 * składniki miesiąca i historia podstaw z Enovy. Rodzaj nieobecności widzą
 * tylko Rozliczenia (D6) — trasa sprawdza uprawnienie.
 */
export function PayrollSalariesView({ year, month }: { year: number; month: number }) {
  return (
    <div className="space-y-3">
      <SalariesCard year={year} month={month} />
      <AbsencesCard year={year} month={month} />
      <HistoryCard />
    </div>
  );
}

function SalariesCard({ year, month }: { year: number; month: number }) {
  const salaries = useSalaries();
  const monthQuery = usePayrollMonth(year, month);
  const [editing, setEditing] = useState<{ userId: number; name: string } | null>(null);
  const [components, setComponents] = useState<{ userId: number; name: string } | null>(null);
  const on = firstOfMonth(year, month);

  if (salaries.isError) return <QueryStateNotice state="error" onRetry={() => salaries.refetch()} />;
  if (!salaries.isSuccess) return <p className="text-sm text-muted-foreground">Wczytywanie pensji…</p>;
  const { people, salaries: rows } = salaries.data;
  const monthComponents = monthQuery.data?.components ?? [];

  return (
    <SectionCard
      title="Pensje — umowa o pracę"
      aside={`${plural(people.length, "osoba", "osoby", "osób")} · ${periodLabel(year, month)}`}
    >
      <p className="border-b border-border/70 px-3.5 py-2 text-[12.5px] text-muted-foreground">
        Osoba z pensją liczy się na liście z pensji: przepracowana część miesiąca, wynagrodzenie chorobowe z L4, urlopowe
        za składniki zmienne i ekwiwalent przy odejściu. Premie z „Mojego miesiąca” dochodzą do brutto, ale nie wchodzą do
        podstaw. Pensja obowiązuje od 1. dnia miesiąca.
      </p>
      {people.length ? (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[720px] table-fixed text-sm">
            <thead>
              <tr className="border-b border-border/70">
                <th className={cn(CALM_HEAD, "w-[28%] px-3.5 py-2 text-left")}>Osoba</th>
                <th className={cn(CALM_HEAD, "w-[22%] px-2 py-2 text-right")}>Pensja w miesiącu</th>
                <th className={cn(CALM_HEAD, "px-2 py-2 text-left")}>Składniki miesiąca</th>
                <th className={cn(CALM_HEAD, "w-[190px] px-3.5 py-2 text-right")}>
                  <span className="sr-only">Akcje</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {people.map((person) => {
                const current = salaryOn(rows, person.user_id, on);
                const history = salaryHistory(rows, person.user_id);
                const entered = COMPONENT_KINDS.map((kind) => componentFor(monthComponents, person.user_id, kind)).filter(
                  (item) => item != null,
                );
                return (
                  <tr key={person.user_id} className={CALM_ROW}>
                    <td className="px-3.5 py-2 align-top">
                      <div className="truncate font-medium">{person.name}</div>
                      <div className={CALM_SUBLINE}>
                        {history.length
                          ? `${plural(history.length, "pensja", "pensje", "pensji")} w historii`
                          : "bez pensji — lista liczy godziny × stawkę albo kwotę Rozliczeń"}
                      </div>
                    </td>
                    <td className="px-2 py-2 text-right align-top tabular-nums">
                      {current ? (
                        <>
                          <div>{zl(current.monthly_amount)} zł</div>
                          <div className={CALM_SUBLINE}>
                            {fteLabel(current.fte)} · od {monthOf(current.effective_from)}
                          </div>
                        </>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-2 py-2 align-top text-[12.5px]">
                      {entered.length ? (
                        <ul className="space-y-0.5">
                          {entered.map((item) => (
                            <li key={item.kind}>
                              {COMPONENT_SHORT[item.kind]}:{" "}
                              <span className="tabular-nums">
                                {item.kind === "equivalent_days" ? item.amount.replace(/\.00$/, "") : `${zl(item.amount)} zł`}
                              </span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <span className="text-muted-foreground">brak</span>
                      )}
                    </td>
                    <td className="px-3.5 py-2 text-right align-top">
                      <div className="flex justify-end gap-1.5">
                        <Button size="sm" variant="outline" onClick={() => setEditing({ userId: person.user_id, name: person.name })}>
                          Pensja
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={!current}
                          title={current ? undefined : "Najpierw pensja"}
                          onClick={() => setComponents({ userId: person.user_id, name: person.name })}
                        >
                          Składniki
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-3.5 py-3 text-[13px] text-muted-foreground">Nikt w kartotece nie jest na umowie o pracę.</p>
      )}
      <SalaryDialog
        target={editing}
        defaultFrom={on}
        current={editing ? salaryOn(rows, editing.userId, on) : null}
        onClose={() => setEditing(null)}
      />
      <ComponentsDialog
        target={components}
        year={year}
        month={month}
        rows={monthComponents}
        labels={salaries.data.component_labels}
        onClose={() => setComponents(null)}
      />
    </SectionCard>
  );
}

function SalaryDialog({
  target,
  defaultFrom,
  current,
  onClose,
}: {
  target: { userId: number; name: string } | null;
  defaultFrom: string;
  current: { monthly_amount: string; fte: string } | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={target != null} onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent size="sm">
        {target ? (
          <SalaryForm
            key={target.userId}
            target={target}
            defaultFrom={defaultFrom}
            current={current}
            onDone={onClose}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function SalaryForm({
  target,
  defaultFrom,
  current,
  onDone,
}: {
  target: { userId: number; name: string };
  defaultFrom: string;
  current: { monthly_amount: string; fte: string } | null;
  onDone: () => void;
}) {
  const { showToast } = useToast();
  const save = useSetSalary();
  const [amount, setAmount] = useState(current ? amountInput(current.monthly_amount) : "");
  const [fte, setFte] = useState(current ? String(Number(current.fte)).replace(".", ",") : "1");
  const [from, setFrom] = useState(defaultFrom.slice(0, 7));
  const [note, setNote] = useState("");
  const parsedAmount = parseSalary(amount);
  const parsedFte = parseFte(fte);
  const ready = parsedAmount != null && parsedFte != null && /^\d{4}-\d{2}$/.test(from);

  const submit = () => {
    if (!ready) return;
    save.mutate(
      {
        userId: target.userId,
        monthlyAmount: parsedAmount,
        fte: parsedFte,
        effectiveFrom: `${from}-01`,
        note: note.trim(),
      },
      {
        onSuccess: () => {
          showToast(`Zapisano pensję: ${target.name}, od ${from.slice(5)}.${from.slice(0, 4)}.`);
          onDone();
        },
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać pensji."), "error"),
      },
    );
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle className="text-lg">Pensja — {target.name}</DialogTitle>
        <DialogDescription>
          Kwota za pełny miesiąc i wymiar etatu. Poprzednia pensja kończy się dzień wcześniej; miesiąca z zatwierdzoną
          listą nie zmienia się.
        </DialogDescription>
      </DialogHeader>
      <DialogBody className="grid gap-2.5 text-[13px] sm:grid-cols-3">
        <label className="grid gap-1">
          <span className="font-medium">Pensja brutto, zł</span>
          <input aria-label="Pensja brutto" className={CONTROL} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label className="grid gap-1">
          <span className="font-medium">Etat</span>
          <input aria-label="Etat" className={CONTROL} placeholder="1 albo 1/2" value={fte} onChange={(e) => setFte(e.target.value)} />
        </label>
        <label className="grid gap-1">
          <span className="font-medium">Od miesiąca</span>
          <input type="month" aria-label="Od miesiąca" className={CONTROL} value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="grid gap-1 sm:col-span-3">
          <span className="font-medium">Opis (opcjonalnie)</span>
          <input aria-label="Opis pensji" className={CONTROL} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {!ready && amount ? (
          <p className="text-[12px] text-destructive sm:col-span-3">Pensja: kwota większa od zera; etat od 0,01 do 1.</p>
        ) : null}
      </DialogBody>
      <DialogFooter>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Anuluj
        </Button>
        <Button size="sm" disabled={!ready} loading={save.isPending} onClick={submit}>
          Zapisz pensję
        </Button>
      </DialogFooter>
    </>
  );
}

function ComponentsDialog({
  target,
  year,
  month,
  rows,
  labels,
  onClose,
}: {
  target: { userId: number; name: string } | null;
  year: number;
  month: number;
  rows: Parameters<typeof componentFor>[0];
  labels: Record<ComponentKind, string>;
  onClose: () => void;
}) {
  return (
    <Dialog open={target != null} onOpenChange={(open) => (!open ? onClose() : undefined)}>
      <DialogContent size="md">
        {target ? (
          <>
            <DialogHeader>
              <DialogTitle className="text-lg">
                Składniki {periodLabel(year, month)} — {target.name}
              </DialogTitle>
              <DialogDescription>
                Zmienne (np. nadgodziny) wchodzą do podstawy chorobowego i do średniej urlopowej; „poza podstawami” — tylko
                do brutto. Podstawę L4 i dni ekwiwalentu wpisuje się, gdy wyliczenie NEXUSA trzeba zastąpić. Po zmianie
                przelicz listę.
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="space-y-3 text-[13px]">
              {COMPONENT_KINDS.map((kind) => (
                <ComponentRow
                  key={kind}
                  kind={kind}
                  label={labels[kind]}
                  year={year}
                  month={month}
                  userId={target.userId}
                  current={componentFor(rows, target.userId, kind)}
                />
              ))}
            </DialogBody>
            <DialogFooter>
              <Button size="sm" variant="ghost" onClick={onClose}>
                Zamknij
              </Button>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function ComponentRow({
  kind,
  label,
  year,
  month,
  userId,
  current,
}: {
  kind: ComponentKind;
  label: string;
  year: number;
  month: number;
  userId: number;
  current: { amount: string; note: string } | null;
}) {
  const { showToast } = useToast();
  const save = useSetComponent();
  const [amount, setAmount] = useState(current ? amountInput(current.amount) : "");
  const [note, setNote] = useState(current?.note ?? "");
  const days = kind === "equivalent_days";
  const parsed = days ? (/^\d{1,3}$/.test(amount.trim()) ? amount.trim() : null) : parseGross(amount);
  const ready = parsed != null && note.trim().length >= 3;

  const send = (value: string | null) =>
    save.mutate(
      { year, month, userId, kind, amount: value, note: note.trim() },
      {
        onSuccess: () => showToast(value == null ? "Usunięto składnik." : "Zapisano składnik — przelicz listę."),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać składnika."), "error"),
      },
    );

  return (
    <fieldset className="grid gap-1.5 rounded-md border border-border/70 p-2.5 sm:grid-cols-[140px_minmax(0,1fr)_auto]">
      <legend className="px-1 text-[12px] font-medium">{label}</legend>
      <input
        aria-label={`${label} — ${days ? "dni" : "kwota"}`}
        className={CONTROL}
        inputMode="decimal"
        placeholder={days ? "dni" : "zł"}
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
      />
      <input
        aria-label={`${label} — opis`}
        className={CONTROL}
        placeholder="Opis (skąd kwota)"
        maxLength={500}
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="flex gap-1">
        <Button size="sm" disabled={!ready} loading={save.isPending} onClick={() => parsed && send(parsed)}>
          Zapisz
        </Button>
        {current ? (
          <Button size="sm" variant="ghost" disabled={save.isPending} onClick={() => send(null)}>
            Usuń
          </Button>
        ) : null}
      </div>
    </fieldset>
  );
}

function AbsencesCard({ year, month }: { year: number; month: number }) {
  const absences = useMonthAbsences(year, month);
  if (absences.isError) return <QueryStateNotice state="error" onRetry={() => absences.refetch()} />;
  if (!absences.isSuccess) return <p className="text-sm text-muted-foreground">Wczytywanie nieobecności…</p>;
  const rows = absences.data;
  return (
    <SectionCard title="Nieobecności miesiąca" aside={`z modułu urlopów · ${periodLabel(year, month)}`}>
      <p className="border-b border-border/70 px-3.5 py-2 text-[12.5px] text-muted-foreground">
        Zatwierdzone nieobecności osób z pensją. Przy L4 oznacz stawkę z e-ZLA: 100% przy ciąży, wypadku w drodze
        i dawstwie, „zasiłek z ZUS” przy opiece nad dzieckiem. Od 34. dnia w roku (od 15. po 50. roku życia) płaci ZUS —
        lista pokaże „Z-3”.
      </p>
      {rows.length ? (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[760px] table-fixed text-sm">
            <thead>
              <tr className="border-b border-border/70">
                <th className={cn(CALM_HEAD, "w-[24%] px-3.5 py-2 text-left")}>Osoba</th>
                <th className={cn(CALM_HEAD, "w-[24%] px-2 py-2 text-left")}>Nieobecność</th>
                <th className={cn(CALM_HEAD, "px-2 py-2 text-left")}>Na liście płac</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className={CALM_ROW}>
                  <td className="truncate px-3.5 py-2 align-top font-medium">{row.person}</td>
                  <td className="px-2 py-2 align-top">
                    <div>{row.label}</div>
                    <div className={CALM_SUBLINE}>
                      {datePl(row.start)} – {datePl(row.end)}
                    </div>
                  </td>
                  <td className="px-2 py-2 align-top">
                    {row.sick ? <SickMark absence={row} /> : <span className="text-[12.5px] text-muted-foreground">{leaveEffect(row.leave_type)}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-3.5 py-3 text-[13px] text-muted-foreground">
          Brak zatwierdzonych nieobecności osób z pensją w tym miesiącu.
        </p>
      )}
    </SectionCard>
  );
}

function leaveEffect(kind: string): string {
  if (["unpaid_leave", "care_leave", "childrearing"].includes(kind)) return "bez wynagrodzenia — pensja metodą godzinową";
  if (["maternity", "paternity", "parental_leave"].includes(kind)) return "zasiłek z ZUS — pensja minus 1/30 za dzień";
  if (kind === "force_majeure") return "połowa wynagrodzenia";
  if (kind === "other") return "pensja bez zmian — sprawdź, czy płatna";
  return "pensja bez zmian (urlopowe za zmienne ze średniej)";
}

function SickMark({ absence }: { absence: MonthAbsence }) {
  const { showToast } = useToast();
  const save = useSetAbsenceMark();
  const [rate, setRate] = useState<SickRate>(absence.sick_rate);
  const [exempt, setExempt] = useState(absence.waiting_exempt);
  const changed = rate !== absence.sick_rate || exempt !== absence.waiting_exempt;

  return (
    <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
      <select
        aria-label={`Stawka L4 — ${absence.person}`}
        className={cn(CONTROL, "h-7 max-w-[260px]")}
        value={rate}
        onChange={(e) => setRate(e.target.value as SickRate)}
      >
        {SICK_RATE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <label className="inline-flex items-center gap-1.5">
        <Checkbox aria-label="Bez okresu wyczekiwania" checked={exempt} onCheckedChange={(value) => setExempt(value === true)} />
        bez okresu wyczekiwania
      </label>
      {changed ? (
        <Button
          size="sm"
          loading={save.isPending}
          onClick={() =>
            save.mutate(
              { id: absence.id, sickRate: rate, waitingExempt: exempt, note: absence.note },
              {
                onSuccess: () => showToast("Zapisano oznaczenie L4 — przelicz listę."),
                onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać oznaczenia."), "error"),
              },
            )
          }
        >
          Zapisz
        </Button>
      ) : null}
    </div>
  );
}

function HistoryCard() {
  const history = useBasisHistory();
  const run = useImportBasisHistory();
  const { showToast } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<HistoryImport | null>(null);
  const [saving, setSaving] = useState(false);

  const send = (save: boolean) => {
    if (!file) return;
    setSaving(save);
    run.mutate(
      { file, save },
      {
        onSuccess: (data) => {
          setResult(data);
          if (data.saved) showToast(`Zapisano historię: ${plural(data.rows.length, "miesiąc", "miesiące", "miesięcy")}.`);
        },
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się wczytać historii."), "error"),
      },
    );
  };
  const rows = history.data ?? [];
  const people = new Set(rows.map((row) => row.user_id)).size;

  return (
    <SectionCard
      title="Historia podstaw z Enovy"
      aside={history.isSuccess ? `${plural(rows.length, "miesiąc", "miesiące", "miesięcy")} · ${plural(people, "osoba", "osoby", "osób")}` : undefined}
    >
      <div className="space-y-2.5 px-3.5 py-3 text-[13px]">
        <p className="text-muted-foreground">
          Jednorazowo: 12 miesięcy sprzed pierwszej listy w NEXUSIE (podstawa chorobowego) z Enovy. Kolumny: „Pracownik”,
          „Okres” (RRRR-MM), „Stałe wypłacone”, „Stałe za pełny miesiąc”, „Zmienne”, „Godziny nominalne”, „Godziny
          przepracowane”; opcjonalnie „Godziny płatne”, „Urlopowe za zmienne”, „Pełny miesiąc”. Miesiąc z listą NEXUSA
          bierze się z listy.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="file"
            accept=".xlsx,.csv"
            aria-label="Plik historii podstaw"
            className="max-w-[260px] text-[12px]"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setResult(null);
            }}
          />
          <Button size="sm" variant="outline" disabled={!file} loading={run.isPending && !saving} onClick={() => send(false)}>
            Sprawdź plik
          </Button>
          <Button
            size="sm"
            disabled={!result || result.saved || result.errors_total > 0 || !result.rows.length}
            loading={run.isPending && saving}
            onClick={() => send(true)}
          >
            Zapisz historię
          </Button>
        </div>
        {result ? (
          <div className="space-y-1">
            <p className="tabular-nums">
              Rozpoznane miesiące: {result.rows.length}
              {result.errors_total ? ` · błędy: ${result.errors_total}` : ""}
              {result.saved ? " · zapisano" : ""}
            </p>
            {result.errors.length ? (
              <ul className="space-y-0.5">
                {result.errors.map((item) => (
                  <li key={`${item.line}-${item.message}`} className="flex items-start gap-1.5">
                    <span aria-hidden className="mt-[7px] size-1.5 shrink-0 rounded-full bg-destructive" />
                    <span>
                      Wiersz {item.line}: {item.message}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
        {history.isError ? <QueryStateNotice state="error" onRetry={() => history.refetch()} /> : null}
      </div>
    </SectionCard>
  );
}
