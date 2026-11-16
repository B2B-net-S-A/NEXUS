"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Pencil, X } from "lucide-react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useChart } from "@/lib/api/accounting";
import {
  useAssignBankLine,
  useBank,
  useBankImport,
  useBankStatement,
  usePostBankStatement,
  type BankLine,
  type BankSettings,
  type BankStatement,
  type BankStatementRow,
} from "@/lib/api/accounting-bank";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard, useAccounting } from "./AccountingShell";
import {
  canAssign,
  curAmount,
  lineTone,
  operationsLabel,
  postBlocker,
  postMessage,
  rateLabel,
  readStatement,
  statementPeriod,
  visibleLines,
} from "./bank-model";
import { datePl, gr, monthTitle } from "./ledger-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const LINES_SHOWN = 100;

/** Suma wyciągu z jednostką: „1 234,56 zł” albo „1 234,56 EUR”. */
function money(value: number, currency: string | undefined): string {
  return currency && currency !== "PLN" ? curAmount(value, currency) : `${gr(value)} zł`;
}
const ACCOUNTS_LIST = "bank-ledger-accounts";

function writeStatement(id: number | null) {
  const params = new URLSearchParams(window.location.search);
  if (id == null) params.delete("statement");
  else params.set("statement", String(id));
  const query = params.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
}

/**
 * Zakładka „Bank” (K4a): wyciąg wgrywa się raz, tutaj. Serwer przepuszcza plik
 * przez dopasowania zapłat faktur kosztowych, wypłat dla zespołu (tylko
 * z Płacami) i wpłat klientów, resztę rozpoznaje regułą (ZUS, urząd skarbowy,
 * opłaty banku). Operacje bez konta czekają na przypisanie, potem
 * „Zaksięguj wyciąg” robi WB w buforze.
 */
export function BankView() {
  const { config, period } = useAccounting();
  const open = config.modules.find((module) => module.key === "bank")?.open ?? false;
  const bank = useBank(period.year, period.month, open);
  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => setSelected(readStatement(window.location.search)), []);
  const select = useCallback((id: number | null) => {
    setSelected(id);
    writeStatement(id);
  }, []);

  if (!open) {
    return (
      <p className="rounded-md border border-border bg-muted/40 px-3.5 py-2 text-[13px] text-muted-foreground">
        Moduł „Bank” jest wyłączony — włącza go administrator w Ustawieniach.
      </p>
    );
  }
  if (bank.isError) return <QueryStateNotice state="error" onRetry={() => bank.refetch()} />;
  if (!bank.isSuccess) return <p className="text-sm text-muted-foreground">Wczytywanie wyciągów…</p>;
  const data = bank.data;
  return (
    <div className="space-y-3.5">
      <div className="grid gap-3.5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <StatementsCard
          rows={data.statements}
          selected={selected}
          onSelect={select}
          title={monthTitle(period.year, period.month)}
        />
        <ImportCard settings={data.settings} onImported={(statement) => select(statement.id)} />
      </div>
      {selected != null ? <StatementCard key={selected} id={selected} onClose={() => select(null)} /> : null}
    </div>
  );
}

function StatementsCard({
  rows,
  selected,
  onSelect,
  title,
}: {
  rows: BankStatementRow[];
  selected: number | null;
  onSelect: (id: number) => void;
  title: string;
}) {
  return (
    <SectionCard title="Wyciągi" aside={`operacje w miesiącu: ${title} · kwoty w walucie rachunku`}>
      {rows.length ? (
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-border/70">
              <th className={cn(CALM_HEAD, "px-3.5 py-2 text-left")}>Rachunek</th>
              <th className={cn(CALM_HEAD, "w-[19%] px-2 py-2 text-left")}>Okres</th>
              <th className={cn(CALM_HEAD, "w-[10%] px-2 py-2 text-right")}>Operacje</th>
              <th className={cn(CALM_HEAD, "w-[15%] px-2 py-2 text-right")}>Obciążenia</th>
              <th className={cn(CALM_HEAD, "w-[14%] px-2 py-2 text-right")}>Uznania</th>
              <th className={cn(CALM_HEAD, "w-[20%] px-3.5 py-2 text-left")}>WB</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.id}
                className={cn(CALM_ROW, "cursor-pointer align-top last:border-0 hover:bg-muted/40", selected === row.id && "bg-muted/60")}
                onClick={() => onSelect(row.id)}
              >
                <td className="min-w-0 px-3.5 py-2">
                  <button
                    type="button"
                    className="block max-w-full truncate text-left font-medium hover:underline"
                    aria-current={selected === row.id ? "true" : undefined}
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelect(row.id);
                    }}
                  >
                    …{row.bank_account_last4}
                  </button>
                  <span className={cn(CALM_SUBLINE, "truncate")} title={`konto ${row.ledger_account}`}>
                    {row.account_name || `konto ${row.ledger_account}`}
                  </span>
                </td>
                <td className="whitespace-nowrap px-2 py-2 tabular-nums">{statementPeriod(row.first_day, row.last_day)}</td>
                <td className={cn(CALM_AMOUNT, "px-2 py-2")}>
                  {row.operations}
                  {row.unresolved ? (
                    <span className={cn(CALM_SUBLINE, "text-warning-muted-foreground")}>bez konta: {row.unresolved}</span>
                  ) : null}
                </td>
                <td className={cn(CALM_AMOUNT, "px-2 py-2")}>{curAmount(row.debit_total, row.currency ?? "PLN")}</td>
                <td className={cn(CALM_AMOUNT, "px-2 py-2")}>{curAmount(row.credit_total, row.currency ?? "PLN")}</td>
                <td className="whitespace-nowrap px-3.5 py-2">
                  {row.to_post ? (
                    <StatusDot tone="warning">
                      <span className="text-[13px]">bez WB</span>
                    </StatusDot>
                  ) : row.wb ? (
                    <StatusDot tone={row.wb === "approved" ? "success" : "info"}>
                      <span className="text-[13px]">{row.wb === "approved" ? "zatwierdzony" : "w buforze"}</span>
                    </StatusDot>
                  ) : (
                    <span className={CALM_EMPTY}>—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="px-3.5 py-6 text-center text-[13px] text-muted-foreground">
          W tym miesiącu nie ma jeszcze wyciągów — wgraj plik z banku.
        </p>
      )}
    </SectionCard>
  );
}

function ImportCard({ settings, onImported }: { settings: BankSettings; onImported: (statement: BankStatement) => void }) {
  const { config } = useAccounting();
  const { showToast } = useToast();
  const run = useBankImport();
  const [file, setFile] = useState<File | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const ready = settings.accounts.length > 0;

  const send = () => {
    if (!file) return;
    run.mutate(file, {
      onSuccess: (statement) => {
        setFile(null);
        setInputKey((value) => value + 1);
        onImported(statement);
        showToast(
          statement.already_imported
            ? "Ten wyciąg był już wczytany — pokazuję go poniżej."
            : statement.unresolved
              ? `Wczytano wyciąg: ${operationsLabel(statement.lines.length)}, bez konta: ${statement.unresolved}.`
              : `Wczytano wyciąg: ${operationsLabel(statement.lines.length)}, wszystkie rozpoznane.`,
        );
      },
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się wczytać wyciągu."), "error"),
    });
  };

  return (
    <SectionCard title="Wgraj wyciąg" aside="MT940 albo CAMT.053">
      <div className="space-y-3 px-3.5 py-3 text-[13px]">
        <p className="leading-5 text-muted-foreground">
          Plik z banku wgrywasz raz, tutaj: od razu oznacza zapłacone faktury kosztowe, wpłaty klientów
          {config.me.payroll ? " i wypłaty dla zespołu" : ""}, a ZUS, urząd skarbowy i opłaty banku rozpoznaje reguła.
        </p>
        {ready ? (
          <div className="space-y-2">
            <input
              key={inputKey}
              type="file"
              accept=".sta,.txt,.940,.mt940,.xml"
              aria-label="Plik wyciągu"
              className="block w-full max-w-full text-[12px]"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <Button size="sm" disabled={!file} loading={run.isPending} onClick={send}>
              Wczytaj wyciąg
            </Button>
          </div>
        ) : (
          <p className="rounded-md border border-dashed border-border px-3 py-2 leading-5">
            Najpierw rachunki firmy: numer rachunku i jego konto w planie (130-x).{" "}
            {config.me.admin ? (
              <Link href="/accounting/settings" className="text-primary hover:underline">
                Dodaj w Ustawieniach
              </Link>
            ) : (
              "Dodaje je administrator w Ustawieniach Księgowości."
            )}
          </p>
        )}
        {!config.me.payroll ? (
          <p className="text-[12px] leading-5 text-muted-foreground">
            Wypłat dla osób z zespołu nie widzisz — rozpoznaje i księguje je osoba z Płacami.
          </p>
        ) : null}
        {ready ? (
          <div>
            <p className={CALM_HEAD}>Rachunki firmy</p>
            <ul className="mt-1 space-y-0.5">
              {settings.accounts.map((account) => (
                <li key={account.number} className="flex items-baseline justify-between gap-2 text-[12.5px]">
                  <span className="min-w-0 truncate">
                    …{account.number.slice(-4)} {account.name}
                  </span>
                  <span className="shrink-0 tabular-nums text-muted-foreground">{account.account}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </SectionCard>
  );
}

function StatementCard({ id, onClose }: { id: number; onClose: () => void }) {
  const statement = useBankStatement(id);

  if (statement.isError) {
    return (
      <SectionCard title="Wyciąg" aside={<CloseButton onClose={onClose} />}>
        <div className="p-3.5">
          <QueryStateNotice state="error" onRetry={() => statement.refetch()} />
        </div>
      </SectionCard>
    );
  }
  if (!statement.isSuccess) return <p className="text-sm text-muted-foreground">Wczytywanie wyciągu…</p>;
  return <StatementBody statement={statement.data} onClose={onClose} />;
}

function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      aria-label="Zamknij wyciąg"
      onClick={onClose}
      className="grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
    >
      <X className="h-3.5 w-3.5" />
    </button>
  );
}

function StatementBody({ statement, onClose }: { statement: BankStatement; onClose: () => void }) {
  const { showToast } = useToast();
  const post = usePostBankStatement();
  const chart = useChart();
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [all, setAll] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const lines = visibleLines(statement.lines, onlyOpen && statement.unresolved > 0);
  const shown = all ? lines : lines.slice(0, LINES_SHOWN);
  const blocker = postBlocker(statement);
  const postable = useMemo(
    () => (chart.data ?? []).filter((account) => account.active && (account.postable || account.dictionary)),
    [chart.data],
  );
  const kinds = Object.entries(statement.counts)
    .filter(([, count]) => count)
    .map(([kind, count]) => {
      const label = statement.lines.find((line) => line.kind === kind)?.kind_label ?? kind;
      return `${label}: ${count}`;
    });
  const wbMonth = statement.last_day.slice(0, 7).split("-");

  const run = () =>
    post.mutate(statement.id, {
      onSuccess: (result) => showToast(postMessage(result)),
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zaksięgować wyciągu."), "error"),
    });

  return (
    <SectionCard
      title={`Wyciąg …${statement.bank_account_last4} ${statement.account_name} · ${statementPeriod(statement.first_day, statement.last_day)}`}
      aside={<CloseButton onClose={onClose} />}
    >
      <div className="grid gap-3 border-b border-border/70 px-3.5 py-2.5 text-[13px] sm:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0 space-y-0.5">
          <p className="tabular-nums">
            Obciążenia <b className="font-semibold">{money(statement.debit_total, statement.currency)}</b> · Uznania{" "}
            <b className="font-semibold">{money(statement.credit_total, statement.currency)}</b> · konto{" "}
            {statement.ledger_account}
            {statement.currency && statement.currency !== "PLN" ? ` · rachunek w ${statement.currency}` : ""}
          </p>
          <p className="text-[12px] text-muted-foreground">{kinds.join(" · ") || "Brak operacji w Twoim zakresie."}</p>
          {statement.payroll_hidden ? (
            <p className="text-[12px] text-muted-foreground">
              Wypłaty dla osób z zespołu widzi i księguje osoba z Płacami.
            </p>
          ) : null}
          {statement.documents.some((doc) => doc.status === "approved") ? (
            <p className="text-[12px] text-muted-foreground">
              Zatwierdzony WB blokuje zmianę kont jego operacji — poprawka to storno dokumentu.
            </p>
          ) : null}
        </div>
        <div className="flex flex-col items-start gap-1.5 sm:items-end">
          <Button size="sm" disabled={blocker != null} title={blocker ?? undefined} loading={post.isPending} onClick={run}>
            Zaksięguj wyciąg
          </Button>
          {blocker ? <span className="max-w-[300px] text-[12px] text-warning-muted-foreground sm:text-right">{blocker}</span> : null}
          {statement.documents.length ? (
            <span className="text-[12px] text-muted-foreground">
              {statement.documents.map((doc, index) => (
                <span key={doc.id}>
                  {index ? ", " : ""}
                  <Link
                    className="text-primary hover:underline"
                    href={`/accounting/documents?year=${wbMonth[0]}&month=${Number(wbMonth[1])}&type=WB&status=${doc.status}`}
                  >
                    {doc.number}
                  </Link>{" "}
                  {doc.status === "approved" ? "zatwierdzony" : "w buforze"}
                  {doc.payroll ? " (płacowy)" : ""}
                </span>
              ))}
            </span>
          ) : null}
        </div>
      </div>
      {statement.unresolved ? (
        <div className="flex items-center gap-1 border-b border-border/70 px-3.5 py-1.5 text-[12px]">
          {[false, true].map((open) => (
            <button
              key={String(open)}
              type="button"
              aria-pressed={onlyOpen === open}
              onClick={() => setOnlyOpen(open)}
              className={cn(
                "rounded px-2 py-0.5",
                onlyOpen === open ? "bg-muted font-semibold text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {open ? `Bez konta (${statement.unresolved})` : `Wszystkie (${statement.lines.length})`}
            </button>
          ))}
        </div>
      ) : null}
      <datalist id={ACCOUNTS_LIST}>
        {postable.map((account) => (
          <option key={account.id} value={account.dictionary ? `${account.number}-` : account.number}>
            {account.name}
          </option>
        ))}
      </datalist>
      {shown.length ? (
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-border/70">
              <th className={cn(CALM_HEAD, "w-[44px] px-3.5 py-2 text-left")}>Poz.</th>
              <th className={cn(CALM_HEAD, "w-[84px] px-2 py-2 text-left")}>Data</th>
              <th className={cn(CALM_HEAD, "px-2 py-2 text-left")}>Kontrahent i tytuł</th>
              <th className={cn(CALM_HEAD, "w-[22%] px-2 py-2 text-left")}>Rozpoznanie</th>
              <th className={cn(CALM_HEAD, "w-[11%] px-2 py-2 text-right")}>Obciążenie</th>
              <th className={cn(CALM_HEAD, "w-[11%] px-2 py-2 text-right")}>Uznanie</th>
              <th className={cn(CALM_HEAD, "w-[170px] px-3.5 py-2 text-left")}>Konto</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((line) => (
              <LineRow
                key={line.id}
                line={line}
                editable={canAssign(line, statement.documents)}
                editing={editing === line.id}
                onEdit={(open) => setEditing(open ? line.id : null)}
              />
            ))}
          </tbody>
        </table>
      ) : (
        <p className="px-3.5 py-6 text-center text-[13px] text-muted-foreground">
          {statement.payroll_hidden ? "Wszystkie operacje tego wyciągu to wypłaty dla zespołu." : "Brak operacji."}
        </p>
      )}
      {lines.length > LINES_SHOWN ? (
        <div className="border-t border-border/70 px-3.5 py-2 text-right text-[12px]">
          <button type="button" className="text-primary hover:underline" onClick={() => setAll((value) => !value)}>
            {all ? "Pokaż mniej" : `Pokaż wszystkie (${lines.length})`}
          </button>
        </div>
      ) : null}
    </SectionCard>
  );
}

function LineRow({
  line,
  editable,
  editing,
  onEdit,
}: {
  line: BankLine;
  editable: boolean;
  editing: boolean;
  onEdit: (open: boolean) => void;
}) {
  const duplicate = line.kind === "duplicate";
  const foreign = Boolean(line.currency) && line.currency !== "PLN";
  const amount = (
    <>
      {curAmount(line.amount, line.currency ?? "PLN")}
      {foreign ? (
        <span className={CALM_SUBLINE} title={`kurs NBP z ${datePl(line.fx_date)}`}>
          {gr(line.amount_pln)} zł · {rateLabel(line.fx_rate)}
        </span>
      ) : null}
    </>
  );
  return (
    <tr className={cn(CALM_ROW, "align-top last:border-0", duplicate && "text-muted-foreground")}>
      <td className="px-3.5 py-1.5 tabular-nums text-muted-foreground">{line.position}</td>
      <td className="px-2 py-1.5 tabular-nums">{datePl(line.booked_on).slice(0, 5)}</td>
      <td className="min-w-0 px-2 py-1.5">
        <span className="block truncate font-medium" title={line.counterparty_name}>
          {line.counterparty_name || "—"}
          {line.counterparty_last4 ? (
            <span className="ml-1 font-normal text-muted-foreground">…{line.counterparty_last4}</span>
          ) : null}
        </span>
        <span className={cn(CALM_SUBLINE, "truncate")} title={line.title}>
          {line.title || "bez tytułu"}
        </span>
      </td>
      <td className="min-w-0 px-2 py-1.5">
        <StatusDot tone={lineTone(line)}>
          <span className="text-[13px]">{line.kind_label}</span>
        </StatusDot>
        {line.note ? <span className={cn(CALM_SUBLINE, !line.resolved && "text-warning-muted-foreground")}>{line.note}</span> : null}
      </td>
      <td className={cn(CALM_AMOUNT, "px-2 py-1.5")}>{line.direction === "debit" ? amount : ""}</td>
      <td className={cn(CALM_AMOUNT, "px-2 py-1.5")}>{line.direction === "credit" ? amount : ""}</td>
      <td className="px-3.5 py-1.5">
        {editable && (editing || !line.resolved) ? (
          <AssignControl line={line} onDone={() => onEdit(false)} onCancel={line.resolved ? () => onEdit(false) : undefined} />
        ) : (
          <span className="flex items-center gap-1">
            <span className="tabular-nums">{line.counter_account ?? <span className={CALM_EMPTY}>—</span>}</span>
            {editable ? (
              <button
                type="button"
                aria-label={`Zmień konto operacji ${line.position}`}
                onClick={() => onEdit(true)}
                className="grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <Pencil className="h-3 w-3" />
              </button>
            ) : null}
          </span>
        )}
      </td>
    </tr>
  );
}

function AssignControl({ line, onDone, onCancel }: { line: BankLine; onDone: () => void; onCancel?: () => void }) {
  const { showToast } = useToast();
  const assign = useAssignBankLine();
  const [account, setAccount] = useState(line.counter_account ?? "");
  const value = account.trim();

  const save = () => {
    if (!value) return;
    assign.mutate(
      { lineId: line.id, account: value },
      {
        onSuccess: () => onDone(),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się przypisać konta."), "error"),
      },
    );
  };

  return (
    <form
      className="flex items-center gap-1"
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <input
        aria-label={`Konto operacji ${line.position}`}
        list={ACCOUNTS_LIST}
        className={cn(CONTROL, "h-7 w-[92px] min-w-0 px-2 tabular-nums")}
        placeholder="konto"
        value={account}
        onChange={(event) => setAccount(event.target.value)}
      />
      <Button type="submit" size="sm" variant="outline" className="h-7 px-2" disabled={!value} loading={assign.isPending}>
        OK
      </Button>
      {onCancel ? (
        <button
          type="button"
          aria-label="Anuluj zmianę konta"
          onClick={onCancel}
          className="grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <X className="h-3 w-3" />
        </button>
      ) : null}
    </form>
  );
}
