"use client";

import { useState, type ChangeEvent } from "react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  useAutomations,
  useRemoveAutomation,
  useSaveAutomation,
  type LineInput,
  type Prepayment,
  type RecurringTemplate,
  type Side,
} from "@/lib/api/accounting";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard, useAccounting } from "./AccountingShell";
import { gr, parseAmount, toGrosze } from "./ledger-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

/** „2026-03” → „03.2026”. */
export function monthLabel(value: string | null): string {
  if (!value) return "—";
  const [year, month] = value.split("-");
  return `${month}.${year}`;
}

interface TemplateLine {
  key: number;
  side: Side;
  account: string;
  amount: string;
  mpk: string;
}

/** Pozycje wzoru → ciało żądania albo problemy (jak serwer: Wn = Ma, min. 2 pozycje). */
export function templateLines(lines: readonly TemplateLine[]): { lines: LineInput[]; problems: string[] } {
  const out: LineInput[] = [];
  const problems: string[] = [];
  let debit = 0;
  let credit = 0;
  lines.forEach((line, index) => {
    if (!line.account.trim() && !line.amount.trim()) return;
    const amount = parseAmount(line.amount);
    if (!line.account.trim() || amount == null || amount.startsWith("-")) {
      problems.push(`Pozycja ${index + 1}: podaj konto i kwotę większą od zera.`);
      return;
    }
    if (line.side === "debit") debit += toGrosze(amount);
    else credit += toGrosze(amount);
    out.push({ side: line.side, account: line.account.trim(), amount, mpk: line.mpk.trim() || null });
  });
  if (out.length < 2 && !problems.length) problems.push("Wzór potrzebuje co najmniej dwóch pozycji.");
  if (out.length >= 2 && debit !== credit) problems.push(`Suma Wn (${gr(debit)} zł) różni się od sumy Ma (${gr(credit)} zł).`);
  return { lines: out, problems };
}

export function AutomationsView() {
  const { config } = useAccounting();
  const open = config.modules.find((module) => module.key === "automations")?.open ?? false;
  const data = useAutomations(open);

  if (!open) {
    return (
      <p className="rounded-md border border-border bg-muted/40 px-3.5 py-2 text-[13px] text-muted-foreground">
        Moduł „Podatki, polisy i PK cykliczne” jest wyłączony — włącza go administrator w Ustawieniach.
      </p>
    );
  }
  if (data.isError) return <QueryStateNotice state="error" onRetry={() => data.refetch()} />;
  if (!data.isSuccess) return <p className="text-sm text-muted-foreground">Wczytywanie automatów…</p>;
  return (
    <div className="space-y-3.5">
      <p className="text-[12px] leading-5 text-muted-foreground">
        Wzory i rozliczenia zakładają osoby z listy „Księgowi”. Dokumenty miesiąca powstają w „Źródłach” („Zaksięguj
        miesiąc”). Wzoru z zatwierdzonym miesiącem nie zmienia się ani nie usuwa — kończy się go datą i zakłada nowy.
      </p>
      <RecurringCard items={data.data.recurring} />
      <PrepaymentsCard items={data.data.prepayments} />
    </div>
  );
}

function RecurringCard({ items }: { items: RecurringTemplate[] }) {
  const { config } = useAccounting();
  const { showToast } = useToast();
  const { askConfirm, askReason, confirmDialog } = useConfirmV2();
  const save = useSaveAutomation();
  const remove = useRemoveAutomation();
  const [adding, setAdding] = useState(false);

  const end = async (item: RecurringTemplate) => {
    const value = await askReason({
      title: `Zakończyć wzór „${item.name}”?`,
      description: "Ostatni miesiąc wzoru (RRRR-MM), nie wcześniejszy niż ostatni zatwierdzony.",
      confirmLabel: "Zakończ wzór",
      field: { label: "Ostatni miesiąc", placeholder: "np. 2026-12", minLength: 7, maxLength: 7 },
    });
    if (!value) return;
    if (!MONTH_RE.test(value.trim())) {
      showToast("Podaj miesiąc jako RRRR-MM, np. 2026-12.", "error");
      return;
    }
    save.mutate(
      { kind: "recurring", id: item.id, body: { end_month: `${value.trim()}-01` } },
      {
        onSuccess: () => showToast(`Wzór „${item.name}” kończy się w ${monthLabel(value.trim())}.`),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zakończyć wzoru."), "error"),
      },
    );
  };

  const drop = async (item: RecurringTemplate) => {
    const ok = await askConfirm({
      title: `Usunąć wzór „${item.name}”?`,
      description: "Szkice z tego wzoru znikną przy następnym księgowaniu miesiąca.",
      confirmLabel: "Usuń wzór",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(
      { kind: "recurring", id: item.id },
      {
        onSuccess: () => showToast(`Usunięto wzór „${item.name}”.`),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się usunąć wzoru."), "error"),
      },
    );
  };

  const active = items.filter((item) => item.active);
  return (
    <SectionCard title="PK cykliczne" aside="jeden PK na wzór w ostatnim dniu miesiąca">
      {active.length ? (
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-border/70">
              <th className={cn(CALM_HEAD, "px-3.5 py-2 text-left")}>Wzór</th>
              <th className={cn(CALM_HEAD, "w-[18%] px-2 py-2 text-left")}>Miesiące</th>
              <th className={cn(CALM_HEAD, "w-[14%] px-2 py-2 text-right")}>Kwota, zł</th>
              <th className={cn(CALM_HEAD, "w-[14%] px-2 py-2 text-left")}>Bufor · zatw.</th>
              <th className={cn(CALM_HEAD, "w-[150px] px-3.5 py-2")} />
            </tr>
          </thead>
          <tbody>
            {active.map((item) => (
              <tr key={item.id} className={cn(CALM_ROW, "align-top last:border-0")}>
                <td className="min-w-0 px-3.5 py-2">
                  <span className="block truncate font-medium">{item.name}</span>
                  <span className={CALM_SUBLINE}>
                    {item.lines.map((line) => `${line.side === "debit" ? "Wn" : "Ma"} ${line.account}`).join(" · ")}
                  </span>
                </td>
                <td className="px-2 py-2 tabular-nums">
                  {monthLabel(item.start_month)} – {item.end_month ? monthLabel(item.end_month) : "bez końca"}
                </td>
                <td className={cn(CALM_AMOUNT, "px-2 py-2")}>{gr(item.total)}</td>
                <td className="px-2 py-2 tabular-nums">
                  {item.draft} · {item.approved}
                </td>
                <td className="px-3.5 py-2 text-right">
                  {config.me.approver ? (
                    <span className="inline-flex gap-1.5">
                      <Button size="sm" variant="outline" onClick={() => void end(item)}>
                        Zakończ
                      </Button>
                      {item.approved === 0 ? (
                        <Button size="sm" variant="ghost" onClick={() => void drop(item)}>
                          Usuń
                        </Button>
                      ) : null}
                    </span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="px-3.5 py-3 text-[13px] text-muted-foreground">Nie ma jeszcze wzorów PK cyklicznych.</p>
      )}
      {config.me.approver ? (
        <div className="border-t border-border/70 px-3.5 py-3">
          {adding ? (
            <RecurringForm onDone={() => setAdding(false)} />
          ) : (
            <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
              Nowy wzór
            </Button>
          )}
        </div>
      ) : null}
      {confirmDialog}
    </SectionCard>
  );
}

let lineSeq = 0;
function emptyLine(side: Side): TemplateLine {
  lineSeq += 1;
  return { key: lineSeq, side, account: "", amount: "", mpk: "" };
}

function RecurringForm({ onDone }: { onDone: () => void }) {
  const { period } = useAccounting();
  const { showToast } = useToast();
  const save = useSaveAutomation();
  const [name, setName] = useState("");
  const [start, setStart] = useState(`${period.year}-${String(period.month).padStart(2, "0")}`);
  const [end, setEnd] = useState("");
  const [lines, setLines] = useState<TemplateLine[]>(() => [emptyLine("debit"), emptyLine("credit")]);
  const [touched, setTouched] = useState(false);
  const check = templateLines(lines);
  const problems = [...(name.trim() ? [] : ["Podaj nazwę wzoru."]), ...check.problems];

  const update = (key: number, patch: Partial<TemplateLine>) =>
    setLines((current) => current.map((line) => (line.key === key ? { ...line, ...patch } : line)));

  const submit = () => {
    setTouched(true);
    if (problems.length) return;
    save.mutate(
      {
        kind: "recurring",
        body: { name: name.trim(), lines: check.lines, start_month: `${start}-01`, end_month: end ? `${end}-01` : null },
      },
      {
        onSuccess: () => {
          showToast(`Zapisano wzór „${name.trim()}”.`);
          onDone();
        },
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać wzoru."), "error"),
      },
    );
  };

  return (
    <div className="space-y-2.5 text-[13px]">
      <div className="flex flex-wrap items-center gap-2">
        <input aria-label="Nazwa wzoru" className={cn(CONTROL, "w-64")} placeholder="np. Najem biura" value={name} onChange={(e) => setName(e.target.value)} />
        <label className="inline-flex items-center gap-1.5">
          od
          <input aria-label="Pierwszy miesiąc" type="month" className={CONTROL} value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="inline-flex items-center gap-1.5">
          do
          <input aria-label="Ostatni miesiąc" type="month" className={CONTROL} value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
      </div>
      {lines.map((line, index) => (
        <div key={line.key} className="flex flex-wrap items-center gap-2">
          <select
            aria-label={`Strona pozycji ${index + 1}`}
            className={CONTROL}
            value={line.side}
            onChange={(e) => update(line.key, { side: e.target.value as Side })}
          >
            <option value="debit">Wn</option>
            <option value="credit">Ma</option>
          </select>
          <input aria-label={`Konto pozycji ${index + 1}`} className={cn(CONTROL, "w-36 font-mono")} placeholder="konto" value={line.account} onChange={(e) => update(line.key, { account: e.target.value })} />
          <input aria-label={`Kwota pozycji ${index + 1}`} className={cn(CONTROL, "w-32 text-right tabular-nums")} placeholder="0,00" value={line.amount} onChange={(e) => update(line.key, { amount: e.target.value })} />
          <input aria-label={`MPK pozycji ${index + 1}`} className={cn(CONTROL, "w-24")} placeholder="MPK" value={line.mpk} onChange={(e) => update(line.key, { mpk: e.target.value })} />
          {lines.length > 2 ? (
            <button type="button" className="text-[12px] text-muted-foreground hover:text-foreground" onClick={() => setLines((current) => current.filter((item) => item.key !== line.key))}>
              usuń
            </button>
          ) : null}
        </div>
      ))}
      <button type="button" className="text-[12px] text-primary hover:underline" onClick={() => setLines((current) => [...current, emptyLine("credit")])}>
        + pozycja
      </button>
      {touched && problems.length ? <p className="text-[12px] text-destructive">{problems[0]}</p> : null}
      <div className="flex gap-2">
        <Button size="sm" loading={save.isPending} onClick={submit}>
          Zapisz wzór
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Anuluj
        </Button>
      </div>
    </div>
  );
}

function PrepaymentsCard({ items }: { items: Prepayment[] }) {
  const { config } = useAccounting();
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const remove = useRemoveAutomation();
  const [adding, setAdding] = useState(false);
  const active = items.filter((item) => item.active);

  const drop = async (item: Prepayment) => {
    const ok = await askConfirm({
      title: `Usunąć rozliczenie „${item.name}”?`,
      description: "Szkice rat znikną przy następnym księgowaniu miesiąca.",
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(
      { kind: "prepayments", id: item.id },
      {
        onSuccess: () => showToast(`Usunięto rozliczenie „${item.name}”.`),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się usunąć rozliczenia."), "error"),
      },
    );
  };

  return (
    <SectionCard title="RMK — rozliczenia międzyokresowe kosztów" aside="np. polisy opłacone z góry">
      {active.length ? (
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-border/70">
              <th className={cn(CALM_HEAD, "px-3.5 py-2 text-left")}>Rozliczenie</th>
              <th className={cn(CALM_HEAD, "w-[20%] px-2 py-2 text-left")}>Konta</th>
              <th className={cn(CALM_HEAD, "w-[13%] px-2 py-2 text-right")}>Kwota, zł</th>
              <th className={cn(CALM_HEAD, "w-[17%] px-2 py-2 text-left")}>Raty</th>
              <th className={cn(CALM_HEAD, "w-[11%] px-2 py-2 text-left")}>Bufor · zatw.</th>
              <th className={cn(CALM_HEAD, "w-[80px] px-3.5 py-2")} />
            </tr>
          </thead>
          <tbody>
            {active.map((item) => (
              <tr key={item.id} className={cn(CALM_ROW, "align-top last:border-0")}>
                <td className="min-w-0 px-3.5 py-2">
                  <span className="block truncate font-medium">{item.name}</span>
                  <span className={CALM_SUBLINE}>{[item.reference, item.counterparty?.name].filter(Boolean).join(" · ") || "—"}</span>
                </td>
                <td className="px-2 py-2 font-mono text-[12px]">
                  Wn {item.cost_account}
                  <span className={CALM_SUBLINE}>Ma {item.prepaid_account}</span>
                </td>
                <td className={cn(CALM_AMOUNT, "px-2 py-2")}>{gr(item.total_amount)}</td>
                <td className="px-2 py-2 tabular-nums">
                  {item.months} × {gr(item.installment)}
                  <span className={CALM_SUBLINE}>od {monthLabel(item.start_month)}</span>
                </td>
                <td className="px-2 py-2 tabular-nums">
                  {item.draft} · {item.approved}
                </td>
                <td className="px-3.5 py-2 text-right">
                  {config.me.approver && item.approved === 0 ? (
                    <Button size="sm" variant="ghost" onClick={() => void drop(item)}>
                      Usuń
                    </Button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="px-3.5 py-3 text-[13px] text-muted-foreground">Nie ma jeszcze rozliczeń RMK.</p>
      )}
      {config.me.approver ? (
        <div className="border-t border-border/70 px-3.5 py-3">
          {adding ? (
            <PrepaymentForm onDone={() => setAdding(false)} />
          ) : (
            <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
              Nowe RMK
            </Button>
          )}
        </div>
      ) : null}
      {confirmDialog}
    </SectionCard>
  );
}

function PrepaymentForm({ onDone }: { onDone: () => void }) {
  const { period } = useAccounting();
  const { showToast } = useToast();
  const save = useSaveAutomation();
  const [values, setValues] = useState({
    name: "",
    reference: "",
    cost_account: "",
    prepaid_account: "640",
    mpk: "",
    total: "",
    start: `${period.year}-${String(period.month).padStart(2, "0")}`,
    months: "12",
  });
  const amount = parseAmount(values.total);
  const months = Number(values.months);
  const problems = [
    !values.name.trim() && "Podaj nazwę.",
    !values.cost_account.trim() && "Podaj konto kosztu.",
    !values.prepaid_account.trim() && "Podaj konto RMK.",
    (amount == null || amount.startsWith("-")) && "Podaj kwotę większą od zera.",
    !(Number.isInteger(months) && months >= 1 && months <= 120) && "Liczba miesięcy: od 1 do 120.",
    !MONTH_RE.test(values.start) && "Podaj pierwszy miesiąc.",
  ].filter(Boolean) as string[];
  const set = (key: keyof typeof values) => (e: ChangeEvent<HTMLInputElement>) =>
    setValues((current) => ({ ...current, [key]: e.target.value }));

  const submit = () => {
    if (problems.length || amount == null) return;
    save.mutate(
      {
        kind: "prepayments",
        body: {
          name: values.name.trim(),
          reference: values.reference.trim(),
          cost_account: values.cost_account.trim(),
          prepaid_account: values.prepaid_account.trim(),
          mpk: values.mpk.trim() || null,
          total_amount: amount,
          start_month: `${values.start}-01`,
          months,
        },
      },
      {
        onSuccess: () => {
          showToast(`Zapisano rozliczenie „${values.name.trim()}”.`);
          onDone();
        },
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać rozliczenia."), "error"),
      },
    );
  };

  return (
    <div className="space-y-2.5 text-[13px]">
      <div className="flex flex-wrap items-center gap-2">
        <input aria-label="Nazwa rozliczenia" className={cn(CONTROL, "w-56")} placeholder="np. Polisa OC 2026/2027" value={values.name} onChange={set("name")} />
        <input aria-label="Numer polisy albo faktury" className={cn(CONTROL, "w-40")} placeholder="nr polisy / faktury" value={values.reference} onChange={set("reference")} />
        <input aria-label="Konto kosztu" className={cn(CONTROL, "w-28 font-mono")} placeholder="koszt, np. 402" value={values.cost_account} onChange={set("cost_account")} />
        <input aria-label="Konto RMK" className={cn(CONTROL, "w-24 font-mono")} value={values.prepaid_account} onChange={set("prepaid_account")} />
        <input aria-label="MPK rozliczenia" className={cn(CONTROL, "w-20")} placeholder="MPK" value={values.mpk} onChange={set("mpk")} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input aria-label="Kwota całkowita" className={cn(CONTROL, "w-32 text-right tabular-nums")} placeholder="kwota" value={values.total} onChange={set("total")} />
        <label className="inline-flex items-center gap-1.5">
          od
          <input aria-label="Pierwszy miesiąc rozliczenia" type="month" className={CONTROL} value={values.start} onChange={set("start")} />
        </label>
        <label className="inline-flex items-center gap-1.5">
          miesięcy
          <input aria-label="Liczba miesięcy" className={cn(CONTROL, "w-16 tabular-nums")} inputMode="numeric" value={values.months} onChange={set("months")} />
        </label>
        {amount != null && months > 0 && !problems.length ? (
          <span className="text-[12px] text-muted-foreground">
            rata {gr(Math.floor(toGrosze(amount) / months))} zł, ostatnia domyka kwotę
          </span>
        ) : null}
      </div>
      {problems.length && values.name ? <p className="text-[12px] text-destructive">{problems[0]}</p> : null}
      <div className="flex gap-2">
        <Button size="sm" disabled={problems.length > 0} loading={save.isPending} onClick={submit}>
          Zapisz RMK
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Anuluj
        </Button>
      </div>
    </div>
  );
}
