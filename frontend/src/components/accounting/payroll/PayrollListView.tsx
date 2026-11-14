"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

import { InlineStats, QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  downloadPayrollFile,
  payrollPaths,
  useApproveList,
  useCancelList,
  usePayrollMonth,
  type PayrollLine,
  type PayrollList,
  type PayrollMonth,
  type PersonSubject,
} from "@/lib/api/payroll-lists";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { datePl, gr } from "../ledger-model";
import { ComputeDialog } from "./ComputeDialog";
import { FileProblemDialog } from "./FileProblemDialog";
import { PayrollLinePanel } from "./PayrollLinePanel";
import { PersonDataDialog } from "./PersonDataDialog";
import { TransfersDialog } from "./TransfersDialog";
import {
  AMOUNT_COLUMNS,
  LIST_STATUS,
  basisText,
  fileProblem,
  groupLines,
  groupProblems,
  inputsAfterCompute,
  kindsTitle,
  kpiStats,
  lineMarker,
  listActions,
  peoplePayrollHref,
  peopleText,
  periodLabel,
  personSubline,
  statusNote,
  zl,
  type ActionState,
  type FileProblem,
} from "./payroll-model";

const PROBLEMS_SHOWN = 3;

/** „Lista płac” miesiąca z nagłówka Księgowości: stan, liczby, problemy, pozycje. */
export function PayrollListView({ year, month }: { year: number; month: number }) {
  const query = usePayrollMonth(year, month);
  if (query.isError) return <QueryStateNotice state="error" onRetry={() => query.refetch()} />;
  if (!query.isSuccess) return <p className="text-sm text-muted-foreground">Wczytywanie listy płac…</p>;
  return <MonthScreen key={`${year}-${month}`} data={query.data} />;
}

function MonthScreen({ data }: { data: PayrollMonth }) {
  const [computing, setComputing] = useState(false);
  const list = data.list;
  const title = periodLabel(data.year, data.month);

  if (!list) {
    return (
      <div className="space-y-3.5">
        {data.period_status !== "closed" ? (
          <div role="status" className="rounded-lg border border-dashed border-border px-6 py-10 text-center">
            <p className="text-sm font-medium">Miesiąc {title} nie jest jeszcze zamknięty</p>
            <p className="mx-auto mt-1 max-w-lg text-sm text-muted-foreground">
              Najpierw zamknij miesiąc w Rozliczeniach (Ludzie → Rozliczenia) — lista płac liczy się z zamrożonych
              godzin, stawek i premii.
            </p>
            <Button size="sm" variant="outline" className="mt-3" asChild>
              <Link href={peoplePayrollHref(data.year, data.month)}>Otwórz Rozliczenia {title}</Link>
            </Button>
          </div>
        ) : (
          <div role="status" className="rounded-lg border border-dashed border-border px-6 py-10 text-center">
            <p className="text-sm font-medium">Lista płac {title} nie jest jeszcze policzona</p>
            <p className="mx-auto mt-1 max-w-lg text-sm text-muted-foreground">
              Miesiąc w Rozliczeniach jest zamknięty. „Przelicz” zbierze kwoty UoP, zleceń i rozliczeń klientów, policzy
              składki i zaliczki PIT; zatwierdza druga osoba z Rozliczeń.
            </p>
            {data.can_compute ? (
              <Button size="sm" className="mt-3" onClick={() => setComputing(true)}>
                Przelicz listę
              </Button>
            ) : null}
          </div>
        )}
        <CancelledLists items={data.cancelled} />
        <ComputeDialog month={data} open={computing} onOpenChange={setComputing} />
      </div>
    );
  }
  return <ListScreen data={data} list={list} />;
}

function ListScreen({ data, list }: { data: PayrollMonth; list: PayrollList }) {
  const { showToast } = useToast();
  const { askConfirm, askReason, confirmDialog } = useConfirmV2();
  const approve = useApproveList();
  const cancel = useCancelList();
  const [computing, setComputing] = useState(false);
  const [transfers, setTransfers] = useState(false);
  const [lineId, setLineId] = useState<number | null>(null);
  const [person, setPerson] = useState<{ subject: PersonSubject; kind: string } | null>(null);
  const [problem, setProblem] = useState<FileProblem | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const actions = listActions(data);
  const status = LIST_STATUS[list.status];
  const kinds = kindsTitle(list.lines);
  const line = list.lines.find((item) => item.id === lineId) ?? null;
  const declarationMonth = list.totals.deadlines?.declaration_month ?? list.pay_date.slice(0, 7);
  const fileName = list.number.replaceAll("/", "-");

  const download = async (key: string, path: string, fallback: string) => {
    setBusy(key);
    try {
      await downloadPayrollFile(path, fallback);
    } catch (error) {
      const found = fileProblem(error);
      if (found) setProblem(found);
      else showToast(apiErrorMessage(error, "Nie udało się pobrać pliku."), "error");
    } finally {
      setBusy(null);
    }
  };

  const doApprove = async () => {
    const ok = await askConfirm({
      title: `Zatwierdzić listę ${list.number}?`,
      description:
        "Kwoty pójdą do pasków, przelewów i deklaracji ZUS. Zmiana po zatwierdzeniu to anulowanie listy z powodem i nowe przeliczenie.",
      confirmLabel: "Zatwierdź listę",
    });
    if (!ok) return;
    approve.mutate(list.id, {
      onSuccess: () => showToast(`Zatwierdzono listę ${list.number}.`),
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zatwierdzić listy."), "error"),
    });
  };

  const doCancel = async () => {
    const reason = await askReason({
      title: `Anulować listę ${list.number}?`,
      description:
        list.status === "approved"
          ? "Zatwierdzona lista przestanie się liczyć: paski, przelewy i deklaracje zrobisz z nowej listy. Powód zostaje w śladzie."
          : "Szkic zniknie z miesiąca; nową listę policzysz przyciskiem „Przelicz”. Powód zostaje w śladzie.",
      confirmLabel: "Anuluj listę",
      variant: "destructive",
      field: { label: "Powód", placeholder: "np. korekta kwoty po zatwierdzeniu", minLength: 3, maxLength: 500 },
    });
    if (!reason) return;
    cancel.mutate(
      { listId: list.id, reason },
      {
        onSuccess: () => showToast(`Anulowano listę ${list.number}.`),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się anulować listy."), "error"),
      },
    );
  };

  const openPerson = (item: PayrollLine) => {
    const subject: PersonSubject | null =
      item.candidate_id != null
        ? { candidateId: item.candidate_id }
        : item.user_id != null
          ? { userId: item.user_id }
          : null;
    if (subject) setPerson({ subject, kind: item.kind });
  };

  return (
    <div className="space-y-2.5">
      {/* Przyciski obok tytułu (jak w makiecie): przy 1280 × 720 tabela ma zacząć się w górnych 60% okna. */}
      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-72">
          <h2 className="text-[15px] font-semibold leading-6" title={list.number}>
            Lista płac {periodLabel(list.year, list.month)}
            {kinds ? ` · ${kinds}` : ""}
          </h2>
          <StatusDot
            tone={status.tone}
            className="mt-0.5"
            note={
              <>
                {statusNote(list)}
                {actions.cancel.visible ? (
                  <>
                    {" · "}
                    <button
                      type="button"
                      disabled={cancel.isPending}
                      className="hit-area text-muted-foreground underline-offset-2 hover:text-destructive hover:underline disabled:opacity-50"
                      onClick={() => void doCancel()}
                    >
                      Anuluj listę
                    </button>
                  </>
                ) : null}
              </>
            }
          >
            <span className="text-[13px]">{status.label}</span>
          </StatusDot>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <div className="flex flex-wrap justify-end gap-1.5">
            <Action state={actions.compute} onClick={() => setComputing(true)}>
              Przelicz
            </Action>
            <Action
              state={actions.payslips}
              loading={busy === "payslips"}
              onClick={() => void download("payslips", payrollPaths.payslips(list.id), `paski-${fileName}.pdf`)}
            >
              Paski PDF
            </Action>
            <Action
              state={actions.kedu}
              loading={busy === "kedu"}
              onClick={() => void download("kedu", payrollPaths.kedu(declarationMonth), `kedu-${declarationMonth}.xml`)}
            >
              ZUS DRA + RCA (KEDU)
            </Action>
            <Action state={actions.transfers} onClick={() => setTransfers(true)}>
              Przelewy
            </Action>
            {actions.approve.visible ? (
              <Action
                primary
                state={actions.approve}
                loading={approve.isPending}
                onClick={() => void doApprove()}
              >
                Zatwierdź listę
              </Action>
            ) : null}
          </div>
          {actions.approve.visible && actions.approve.reason ? (
            <p id="payroll-approve-refusal" className="max-w-md text-right text-[11.5px] leading-4 text-muted-foreground">
              {actions.approve.reason}
            </p>
          ) : null}
        </div>
      </header>

      {data.period_status !== "closed" ? (
        <Notice tone="danger">
          Miesiąc w Rozliczeniach jest ponownie otwarty — zamknij go i przelicz listę.{" "}
          <Link href={peoplePayrollHref(data.year, data.month)} className="font-medium text-primary hover:underline">
            Rozliczenia {periodLabel(data.year, data.month)}
          </Link>
        </Notice>
      ) : inputsAfterCompute(data) ? (
        <Notice tone="warning">
          Kwoty wpisane przez Rozliczenia zmieniły się po przeliczeniu — przelicz listę, zanim ktoś ją zatwierdzi.{" "}
          <button type="button" className="font-medium text-primary hover:underline" onClick={() => setComputing(true)}>
            Przelicz
          </button>
        </Notice>
      ) : null}

      <InlineStats stats={kpiStats(list)} />

      <ProblemsPanel list={list} />

      <LinesTable list={list} onOpen={(item) => setLineId(item.id)} />

      <CancelledLists items={data.cancelled} />

      <PayrollLinePanel month={data} line={line} onClose={() => setLineId(null)} onPersonData={openPerson} />
      <PersonDataDialog
        subject={person?.subject ?? null}
        kind={person?.kind}
        open={person != null}
        onOpenChange={(open) => {
          if (!open) setPerson(null);
        }}
      />
      <ComputeDialog month={data} open={computing} onOpenChange={setComputing} />
      <TransfersDialog list={list} open={transfers} onOpenChange={setTransfers} />
      <FileProblemDialog problem={problem} onClose={() => setProblem(null)} />
      {confirmDialog}
    </div>
  );
}

/** Przycisk nagłówka z powodem, gdy nieaktywny (dymek na opakowaniu — wyłączony przycisk nie łapie myszy). */
function Action({
  state,
  primary,
  loading,
  onClick,
  children,
}: {
  state: ActionState;
  primary?: boolean;
  loading?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  const button = (
    <Button
      size="sm"
      variant={primary ? "primary" : "outline"}
      disabled={!state.enabled}
      loading={loading}
      aria-describedby={primary && !state.enabled ? "payroll-approve-refusal" : undefined}
      onClick={onClick}
    >
      {children}
    </Button>
  );
  if (state.enabled || !state.reason) return button;
  return (
    <span className="inline-flex" title={state.reason}>
      {button}
    </span>
  );
}

function Notice({ tone, children }: { tone: "warning" | "danger"; children: ReactNode }) {
  return (
    <p
      role="status"
      className={cn(
        "rounded-md px-3.5 py-2 text-[13px]",
        tone === "danger"
          ? "bg-destructive-muted text-destructive-muted-foreground"
          : "bg-warning-muted text-warning-muted-foreground",
      )}
    >
      {children}
    </p>
  );
}

/**
 * Problemy listy nad tabelą: blokujące zatwierdzenie zawsze widać (z osobami),
 * „do uwagi” po kliknięciu — przy 1280 × 720 tabela ma zostać w górnych 60% okna.
 */
function ProblemsPanel({ list }: { list: PayrollList }) {
  const [open, setOpen] = useState(false);
  const groups = groupProblems(list.problems);
  if (!groups.length) return null;
  const blocking = groups.filter((group) => group.blocking);
  const notes = groups.filter((group) => !group.blocking);
  const shown = open ? groups : blocking.slice(0, PROBLEMS_SHOWN);
  const hidden = groups.length - shown.length;
  return (
    <section
      aria-label="Problemy listy"
      className={cn(
        "rounded-lg border px-3.5 py-1.5",
        blocking.length ? "border-destructive/40 bg-destructive-muted/40" : "border-border bg-muted/30",
      )}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="text-[13px] font-semibold">
          {blocking.length
            ? `Do rozwiązania przed zatwierdzeniem: ${blocking.length}`
            : `Do uwagi, nie blokuje zatwierdzenia: ${notes.length}`}
        </h3>
        {hidden > 0 || open ? (
          <button type="button" className="text-[12px] text-primary hover:underline" onClick={() => setOpen((value) => !value)}>
            {open ? "Pokaż mniej" : blocking.length ? `Pokaż wszystkie (${groups.length})` : "Pokaż"}
          </button>
        ) : null}
      </div>
      {shown.length ? (
        <ul className="mt-0.5 space-y-0.5">
          {shown.map((group) => (
            <li key={`${group.blocking}-${group.code}`} className="flex items-start gap-2 text-[12.5px] leading-5">
              <span
                aria-hidden
                className={cn("mt-[7px] size-1.5 shrink-0 rounded-full", group.blocking ? "bg-destructive" : "bg-warning")}
              />
              <span className="min-w-0 break-words">
                {group.label}
                {group.people.length ? <span className="text-muted-foreground"> — {peopleText(group.people)}</span> : null}
                {!group.blocking ? <span className="ml-1 text-[11.5px] text-muted-foreground">(nie blokuje)</span> : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function LinesTable({ list, onOpen }: { list: PayrollList; onOpen: (line: PayrollLine) => void }) {
  const groups = groupLines(list.lines);
  if (!groups.length) {
    return (
      <p className="rounded-lg border border-dashed border-border px-6 py-8 text-center text-sm text-muted-foreground">
        Na liście nie ma pozycji — w zamkniętym miesiącu nie było UoP, zleceń ani rozliczeń klientów.
      </p>
    );
  }
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full min-w-[900px] table-fixed text-sm">
        <thead>
          <tr className="border-b border-border/70">
            <th className={cn(CALM_HEAD, "sticky left-0 z-10 w-[21%] bg-card px-3.5 py-2 text-left")}>Osoba</th>
            <th className={cn(CALM_HEAD, "w-[15%] px-2 py-2 text-left")}>Podstawa</th>
            {AMOUNT_COLUMNS.map((column, index) => (
              <th
                key={column.key}
                className={cn(CALM_HEAD, "px-2 py-2 text-right", index === AMOUNT_COLUMNS.length - 1 && "pr-3.5")}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        {groups.map((group) => (
          <tbody key={group.kind}>
            <tr className="border-b border-border/70 bg-muted/40">
              <th scope="rowgroup" colSpan={2} className="px-3.5 py-2 text-left text-[13px] font-semibold">
                {group.label} · {group.lines.length}
              </th>
              {AMOUNT_COLUMNS.map((column, index) => (
                <td
                  key={column.key}
                  className={cn(
                    CALM_AMOUNT,
                    "px-2 py-2 text-[13px]",
                    (column.key === "gross" || column.key === "net") && "font-semibold",
                    index === AMOUNT_COLUMNS.length - 1 && "pr-3.5",
                  )}
                >
                  {gr(group.sums[column.key])}
                </td>
              ))}
            </tr>
            {group.lines.map((line) => (
              <LineRow key={line.id} line={line} onOpen={onOpen} />
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

function LineRow({ line, onOpen }: { line: PayrollLine; onOpen: (line: PayrollLine) => void }) {
  const marker = lineMarker(line);
  const basis = basisText(line);
  const problems = line.problems.map((problem) => problem.label).join(" ");
  return (
    <tr onClick={() => onOpen(line)} className={cn(CALM_ROW, "group cursor-pointer align-top hover:bg-accent/60")}>
      <td className="sticky left-0 z-10 min-w-0 bg-card px-3.5 py-2 group-hover:bg-accent">
        <span className="flex min-w-0 items-center gap-1.5">
          <button
            type="button"
            className="min-w-0 truncate text-left font-medium text-foreground hover:text-primary hover:underline"
            title={line.person_name}
            onClick={(event) => {
              event.stopPropagation();
              onOpen(line);
            }}
          >
            {line.person_name}
          </button>
          {marker ? (
            <span
              role="img"
              aria-label={`${marker === "blocking" ? "Problem blokujący" : "Do uwagi"}: ${problems}`}
              title={problems}
              className={cn("inline-flex shrink-0", marker === "blocking" ? "text-destructive" : "text-warning-muted-foreground")}
            >
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
            </span>
          ) : null}
        </span>
        <span className={cn(CALM_SUBLINE, "truncate")} title={`${personSubline(line)} · ${line.source_label}`}>
          {personSubline(line)}
        </span>
      </td>
      <td className="min-w-0 px-2 py-2">
        <span className="block truncate tabular-nums" title={basis.main}>
          {basis.main}
        </span>
        {basis.sub ? (
          <span className={cn(CALM_SUBLINE, "truncate")} title={basis.sub}>
            {basis.sub}
          </span>
        ) : null}
      </td>
      {AMOUNT_COLUMNS.map((column, index) => {
        const value = line[column.key];
        return (
          <td
            key={column.key}
            className={cn(
              CALM_AMOUNT,
              "px-2 py-2",
              column.key === "net" && "font-semibold",
              index === AMOUNT_COLUMNS.length - 1 && "pr-3.5",
            )}
          >
            {value == null ? <span className={CALM_EMPTY}>—</span> : zl(value)}
          </td>
        );
      })}
    </tr>
  );
}

function CancelledLists({ items }: { items: PayrollMonth["cancelled"] }) {
  if (!items.length) return null;
  return (
    <section aria-label="Anulowane listy" className="text-[12.5px] text-muted-foreground">
      <h3 className="font-medium text-foreground">Anulowane listy tego miesiąca</h3>
      <ul className="mt-1 space-y-0.5">
        {items.map((item) => (
          <li key={item.id}>
            {item.number} · {datePl(item.cancelled_at)}
            {item.cancel_reason ? ` · ${item.cancel_reason}` : ""}
          </li>
        ))}
      </ul>
    </section>
  );
}
