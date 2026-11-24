"use client";

// „Gdzie są rozliczenia”: wiersz na klienta i wiersz biura, pięć kolumn kroków
// (raport → kontrola → przyjęcie → faktura od osoby → faktura do klienta)
// i „Kto teraz”. Wiersz rozwija osoby z tymi samymi kolumnami (makiety 24.11.2026).

import Link from "next/link";
import { Fragment, useMemo, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";

import { StatusDot } from "@/components/ds/StatusDot";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useSettlementMonth,
  type MonthCloseClient,
  type MonthCloseOverview,
  type TeamMonth,
} from "@/lib/api/client-settlements";
import type { ReminderClient } from "@/lib/api/settlement-reminders";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";

import {
  STEPS,
  STEP_DOT,
  clientInvoiceLook,
  clientMoves,
  personSteps,
  stagesOf,
  teamMoves,
  teamSteps,
  teamSummary,
  type Move,
  type PersonSteps,
  type Segment,
  type Step,
  type StepTone,
} from "./month-model";

const BAR: Record<StepTone, string> = {
  done: "bg-success",
  warn: "bg-warning",
  fail: "bg-destructive",
  todo: "bg-info",
  wait: "bg-muted-foreground/35",
  na: "bg-transparent",
};

const TEXT: Record<StepTone, string> = {
  done: "text-success-muted-foreground",
  warn: "text-warning-muted-foreground",
  fail: "text-destructive",
  todo: "text-info-muted-foreground",
  wait: "text-muted-foreground",
  na: "text-muted-foreground",
};

/** Kolumny tabeli: klient + 5 kroków + „Kto teraz”. */
const COLS = ["w-[17%]", "w-[11%]", "w-[19%]", "w-[11%]", "w-[13%]", "w-[16%]", "w-[13%]"];
const PEOPLE_PREVIEW = 12;

function Bar({ segments, total }: { segments: Segment[]; total: number }) {
  return (
    <span aria-hidden className="mb-1 flex h-1.5 w-full max-w-28 overflow-hidden rounded-full bg-muted">
      {segments.map((s) =>
        s.n > 0 && total > 0 ? (
          <span key={s.title} title={`${s.title}: ${s.n}`} className={BAR[s.tone]} style={{ width: `${(s.n / total) * 100}%` }} />
        ) : null,
      )}
    </span>
  );
}

function Cell({ segments, total, main, note }: { segments?: Segment[]; total?: number; main: ReactNode; note?: ReactNode }) {
  return (
    <div className="min-w-0">
      {segments && total ? <Bar segments={segments} total={total} /> : null}
      <div className="truncate text-[12px] font-medium tabular-nums">{main}</div>
      {note ? <div className="line-clamp-2 text-[11px] leading-4 text-muted-foreground">{note}</div> : null}
    </div>
  );
}

/** Liczby w notce, każda w kolorze swojego stanu, zera pomijane. */
function Parts({ parts }: { parts: [number, string, StepTone][] }) {
  const shown = parts.filter(([n]) => n > 0);
  if (!shown.length) return null;
  return (
    <>
      {shown.map(([n, label, tone], i) => (
        <span key={label} className={TEXT[tone]}>
          {i ? " · " : ""}
          {n} {label}
        </span>
      ))}
    </>
  );
}

function Moves({ moves }: { moves: Move[] }) {
  if (!moves.length) return <StatusDot tone="success">Zamknięte</StatusDot>;
  return (
    <div className="space-y-0.5">
      {moves.slice(0, 2).map((m) => (
        <StatusDot key={m.who} tone={STEP_DOT[m.tone]}>
          {m.who} <span className="tabular-nums text-muted-foreground">{m.count}</span>
        </StatusDot>
      ))}
    </div>
  );
}

function StepDot({ step }: { step: Step }) {
  if (step.tone === "na" && step.label === "—") return <span className="text-[11px] text-muted-foreground">—</span>;
  return (
    <StatusDot tone={STEP_DOT[step.tone]} className="max-w-full" note={step.note ? <span className="block truncate">{step.note}</span> : undefined}>
      <span className={cn("truncate", step.tone === "na" && "font-normal text-muted-foreground")}>{step.label}</span>
    </StatusDot>
  );
}

function PersonRow({ name, sub, steps, href }: { name: string; sub?: ReactNode; steps: PersonSteps; href?: string }) {
  return (
    <tr className="bg-muted/20 text-[12px]">
      <td className="truncate py-1.5 pl-9 pr-2">
        {href ? (
          <Link href={href} className="block truncate font-medium hover:underline">
            {name}
          </Link>
        ) : (
          <span className="block truncate font-medium">{name}</span>
        )}
        {sub ? <span className="block truncate text-[11px] text-muted-foreground">{sub}</span> : null}
      </td>
      {(["report", "check", "accept", "contractor", "client", "who"] as const).map((key) => (
        <td key={key} className="px-2 py-1.5 align-top">
          <StepDot step={steps[key]} />
        </td>
      ))}
    </tr>
  );
}

const WHO_ORDER: Record<StepTone, number> = { fail: 0, warn: 1, todo: 2, wait: 3, na: 4, done: 5 };

function ClientPeople({ client, month, hrefFor }: { client: MonthCloseClient; month: string; hrefFor: (contractId: number) => string }) {
  const query = useSettlementMonth(client.client_id, month);
  const [all, setAll] = useState(false);
  const rows = useMemo(
    () =>
      (query.data?.rows ?? [])
        .map((r) => ({ r, steps: personSteps(r) }))
        .sort((a, b) => WHO_ORDER[a.steps.who.tone] - WHO_ORDER[b.steps.who.tone] || a.r.person.localeCompare(b.r.person, "pl")),
    [query.data],
  );
  if (query.isError) {
    return (
      <tr>
        <td colSpan={7} className="bg-muted/20 py-2 pl-9 text-[12px] text-destructive">
          {apiErrorMessage(query.error, "Nie udało się pobrać osób klienta.")}
        </td>
      </tr>
    );
  }
  if (!query.isSuccess) {
    return (
      <tr>
        <td colSpan={7} className="bg-muted/20 py-2 pl-9 text-[12px] text-muted-foreground">
          Ładowanie osób…
        </td>
      </tr>
    );
  }
  const shown = all ? rows : rows.slice(0, PEOPLE_PREVIEW);
  return (
    <>
      {shown.map(({ r, steps }) => (
        <PersonRow key={r.contract_id} name={r.person} sub={r.order_number ?? "brak numeru zamówienia"} steps={steps} href={hrefFor(r.contract_id)} />
      ))}
      {rows.length > shown.length ? (
        <tr>
          <td colSpan={7} className="bg-muted/20 py-1.5 pl-9">
            <button type="button" onClick={() => setAll(true)} className="text-[12px] font-medium text-primary hover:underline">
              Pokaż wszystkich ({rows.length})
            </button>
          </td>
        </tr>
      ) : null}
    </>
  );
}

function TeamPeople({ team }: { team: TeamMonth }) {
  const [all, setAll] = useState(false);
  const rows = team.people
    .map((p) => ({ p, steps: teamSteps(p) }))
    .sort((a, b) => WHO_ORDER[a.steps.who.tone] - WHO_ORDER[b.steps.who.tone] || a.p.person.localeCompare(b.p.person, "pl"));
  const shown = all ? rows : rows.slice(0, PEOPLE_PREVIEW);
  return (
    <>
      {shown.map(({ p, steps }) => (
        <PersonRow
          key={p.user_id}
          name={p.person}
          sub="B2B · biuro"
          steps={{ ...steps, client: { tone: "na", label: "—" } }}
        />
      ))}
      {rows.length > shown.length ? (
        <tr>
          <td colSpan={7} className="bg-muted/20 py-1.5 pl-9">
            <button type="button" onClick={() => setAll(true)} className="text-[12px] font-medium text-primary hover:underline">
              Pokaż wszystkich ({rows.length})
            </button>
          </td>
        </tr>
      ) : null}
    </>
  );
}

function Toggle({ open, onClick, children, sub, href }: { open: boolean; onClick: () => void; children: ReactNode; sub: ReactNode; href?: string }) {
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <div className="flex min-w-0 items-start gap-1.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={onClick}
        data-tour="finance.month-close.expand"
        className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <Icon aria-hidden className="size-4" />
        <span className="sr-only">{open ? "Zwiń osoby" : "Pokaż osoby"}</span>
      </button>
      <span className="min-w-0">
        <span className="flex min-w-0 items-center gap-1">
          <button type="button" onClick={onClick} className="truncate text-left font-medium hover:underline">
            {children}
          </button>
          {href ? (
            <Link href={href} title="Otwórz ekran klienta" className="shrink-0 text-muted-foreground hover:text-primary">
              <ExternalLink aria-hidden className="size-3.5" />
              <span className="sr-only">Otwórz ekran klienta</span>
            </Link>
          ) : null}
        </span>
        <span className="block truncate text-[11px] text-muted-foreground">{sub}</span>
      </span>
    </div>
  );
}

interface StageTableProps {
  data: MonthCloseOverview;
  month: string;
  team: TeamMonth | null;
  teamError: string | null;
  reminders: Map<number, ReminderClient>;
  clientHref: (clientId: number, extra?: Record<string, string>) => string;
  reminderNote: (r: ReminderClient | undefined) => string | undefined;
}

export function StageTable({ data, month, team, teamError, reminders, clientHref, reminderNote }: StageTableProps) {
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div className="relative overflow-x-auto rounded-xl border bg-card">
      <table className="w-full min-w-[960px] table-fixed text-[13px]">
        <colgroup>
          {COLS.map((w, i) => (
            <col key={i} className={w} />
          ))}
        </colgroup>
        <thead className="border-b bg-muted/40 text-left text-[11px] text-muted-foreground">
          <tr>
            <th className="px-3 py-1.5 font-medium">Klient / biuro</th>
            {STEPS.map((s, i) => (
              <th key={s.key} className="px-2 py-1.5 font-medium">
                <span className="mr-1 inline-flex size-4 items-center justify-center rounded-full bg-muted text-[10px] font-semibold tabular-nums text-foreground">
                  {i + 1}
                </span>
                {s.label}
              </th>
            ))}
            <th className="px-2 py-1.5 font-medium">Kto teraz</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {(team && team.people.length > 0) || teamError ? (
            <TeamRows team={team} error={teamError} open={open.has("team")} onToggle={() => toggle("team")} />
          ) : null}
          {data.clients.map((c) => {
            const key = String(c.client_id);
            return (
              <Fragment key={key}>
                <ClientRow
                  c={c}
                  open={open.has(key)}
                  onToggle={() => toggle(key)}
                  href={clientHref(c.client_id, c.client_report ? { stSub: "t4t" } : {})}
                  reminder={reminderNote(reminders.get(c.client_id))}
                />
                {open.has(key) && !c.client_report ? (
                  <ClientPeople client={c} month={month} hrefFor={(contractId) => clientHref(c.client_id, { stContract: String(contractId) })} />
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ClientRow({ c, open, onToggle, href, reminder }: { c: MonthCloseClient; open: boolean; onToggle: () => void; href: string; reminder?: string }) {
  const report = c.client_report;
  if (report) {
    return (
      <tr className="hover:bg-muted/30">
        <td className="px-3 py-2 align-top">
          <Toggle open={open} onClick={onToggle} sub={`raport klienta (T4T) · ${report.all} os.`} href={href}>
            {c.name}
          </Toggle>
        </td>
        <td className="px-2 py-2 align-top">
          <Cell main={report.all ? "Raport klienta" : "Brak raportu"} note={`${report.all - report.unmatched} z ${report.all} rozpoznanych`} />
        </td>
        <td className="px-2 py-2 align-top">
          <Cell
            main={countPl(report.ok, "zgodna z fakturą", "zgodne z fakturą", "zgodnych z fakturą")}
            note={<Parts parts={[[report.differs, "różnice godzin", "warn"], [report.no_invoice, "bez faktury", "wait"]]} />}
          />
        </td>
        <td className="px-2 py-2 align-top text-[11px] text-muted-foreground">z raportu</td>
        <td className="px-2 py-2 align-top">
          <Cell main={`${c.contractor_in_ksef} w KSeF`} />
        </td>
        <td className="px-2 py-2 align-top">
          <StatusDot tone="neutral" note="godziny z T4T">
            Z raportu klienta
          </StatusDot>
        </td>
        <td className="px-2 py-2 align-top">
          <Moves moves={report.differs ? [{ who: "Finanse", count: report.differs, tone: "warn" }] : []} />
        </td>
      </tr>
    );
  }
  const s = stagesOf(c);
  const inv = clientInvoiceLook(c);
  const ksef = s.contractor_invoice.match + s.contractor_invoice.differs + s.contractor_invoice.nip;
  return (
    <tr className={cn("hover:bg-muted/30", open && "bg-muted/30")}>
      <td className="px-3 py-2 align-top">
        <Toggle open={open} onClick={onToggle} sub={`${s.people} os.`} href={href}>
          {c.name}
        </Toggle>
      </td>
      <td className="px-2 py-2 align-top">
        <Cell
          segments={[
            { n: s.report.in, tone: "done", title: "raport jest" },
            { n: s.report.missing, tone: "wait", title: "brak raportu" },
          ]}
          total={s.people}
          main={`${s.report.in}/${s.people}`}
          note={
            s.report.missing ? (
              <>
                <span className="block">{s.report.missing} brak</span>
                {reminder ? <span className="block truncate">{reminder}</span> : null}
              </>
            ) : (
              "komplet"
            )
          }
        />
      </td>
      <td className="px-2 py-2 align-top">
        <Cell
          segments={[
            { n: s.check.clean + s.check.resolved, tone: "done", title: "bez uwag albo rozstrzygnięte" },
            { n: s.check.warn, tone: "warn", title: "uwagi" },
            { n: s.check.fail + s.check.no_md, tone: "fail", title: "błędy" },
            { n: s.check.unread, tone: "todo", title: "nieodczytane" },
            { n: s.check.returned, tone: "wait", title: "odesłane" },
          ]}
          total={s.people}
          main={`${s.check.clean} bez uwag`}
          note={
            <Parts
              parts={[
                [s.check.resolved, "rozstrzygn.", "done"],
                [s.check.fail, s.check.fail === 1 ? "błąd" : "błędy", "fail"],
                [s.check.warn, s.check.warn === 1 ? "uwaga" : "uwagi", "warn"],
                [s.check.unread, "nieodczyt.", "todo"],
                [s.check.no_md, "bez MD zam.", "fail"],
                [s.check.returned, "odesłane", "wait"],
              ]}
            />
          }
        />
      </td>
      <td className="px-2 py-2 align-top">
        <Cell
          segments={[
            { n: s.accept.done, tone: "done", title: "przyjęte" },
            { n: s.accept.ready, tone: "todo", title: "do przyjęcia" },
          ]}
          total={s.people}
          main={`${s.accept.done}/${s.people}`}
          note={
            s.accept.ready ? (
              <span className={TEXT.todo}>{s.accept.ready} do przyjęcia</span>
            ) : s.accept.auto ? (
              `automat ${s.accept.auto}`
            ) : undefined
          }
        />
      </td>
      <td className="px-2 py-2 align-top">
        <Cell
          segments={[
            { n: s.contractor_invoice.match, tone: "done", title: "zgodne" },
            { n: s.contractor_invoice.nip, tone: "warn", title: "NIP" },
            { n: s.contractor_invoice.differs, tone: "fail", title: "inna kwota" },
          ]}
          total={s.people}
          main={`${ksef}/${s.people} w KSeF`}
          note={
            s.contractor_invoice.differs + s.contractor_invoice.nip ? (
              <Parts
                parts={[
                  [s.contractor_invoice.differs, "inna kwota", "fail"],
                  [s.contractor_invoice.nip, "NIP do zatw.", "warn"],
                ]}
              />
            ) : s.accept.done ? undefined : (
              "po przyjęciu RCP"
            )
          }
        />
      </td>
      <td className="px-2 py-2 align-top">
        <StatusDot tone={STEP_DOT[inv.tone]} note={inv.note} className="max-w-full">
          <span className="truncate">{inv.label}</span>
        </StatusDot>
      </td>
      <td className="px-2 py-2 align-top">
        <Moves moves={clientMoves(s)} />
      </td>
    </tr>
  );
}

function TeamRows({ team, error, open, onToggle }: { team: TeamMonth | null; error: string | null; open: boolean; onToggle: () => void }) {
  if (!team) {
    return (
      <tr className="bg-primary/[0.03]">
        <td className="px-3 py-2 align-top">
          <span className="block font-medium">Biuro — B2B.Net</span>
          <span className="block text-[11px] text-muted-foreground">nasi ludzie na B2B</span>
        </td>
        <td colSpan={6} className="px-2 py-2 align-top text-[12px] text-muted-foreground">
          {error}
        </td>
      </tr>
    );
  }
  const t = teamSummary(team);
  const toPay = t.invoices - t.differs - t.paid;
  return (
    <>
      <tr className={cn("bg-primary/[0.03] hover:bg-muted/30", open && "bg-muted/30")}>
        <td className="px-3 py-2 align-top">
          <Toggle open={open} onClick={onToggle} sub={`${t.people} os. na B2B`}>
            Biuro — B2B.Net
          </Toggle>
        </td>
        <td className="px-2 py-2 align-top">
          <Cell
            segments={[
              { n: t.timesheets, tone: "done", title: "ewidencja" },
              { n: t.people - t.timesheets, tone: "wait", title: "brak ewidencji" },
            ]}
            total={t.people}
            main={`${t.timesheets}/${t.people}`}
            note={t.people - t.timesheets ? `${t.people - t.timesheets} bez ewidencji` : "komplet"}
          />
        </td>
        <td className="px-2 py-2 align-top text-[11px] text-muted-foreground">bez reguł klienta</td>
        <td className="px-2 py-2 align-top">
          <Cell
            segments={[{ n: t.approved, tone: "done", title: "zatwierdzone" }]}
            total={t.people}
            main={`${t.approved}/${t.people}`}
            note="ewidencja zatwierdzona"
          />
        </td>
        <td className="px-2 py-2 align-top">
          <Cell
            segments={[
              { n: t.paid, tone: "done", title: "zapłacone" },
              { n: toPay, tone: "todo", title: "do zapłaty" },
              { n: t.differs, tone: "fail", title: "inna kwota" },
            ]}
            total={t.people}
            main={`${t.invoices}/${t.people} w KSeF`}
            note={
              <Parts
                parts={[
                  [t.noNip, "bez NIP-u", "fail"],
                  [t.paid, "zapłacone", "done"],
                  [toPay, "do zapłaty", "todo"],
                  [t.differs, "inna kwota", "fail"],
                ]}
              />
            }
          />
        </td>
        <td className="px-2 py-2 align-top">
          <StatusDot tone="neutral" note="klientem jesteśmy my">
            <span className="font-normal text-muted-foreground">Nie dotyczy</span>
          </StatusDot>
        </td>
        <td className="px-2 py-2 align-top">
          <Moves moves={teamMoves(t)} />
        </td>
      </tr>
      {open ? <TeamPeople team={team} /> : null}
    </>
  );
}
