"use client";
// B · „Kończące się” na osi czasu: kto odchodzi kiedy, w grupach po miesiącu.
// Pasek kończy się w ostatnim dniu; zamówienie trwające po odejściu widać jako
// przerywany pasek — niespójność od razu rzuca się w oczy.
import Link from "next/link";
import { cn } from "@/lib/utils";
import { useMkContractList } from "../shared/data";
import { daysUntil, fmtDayMonth, fmtMonthYear, fmtPln, OSOBY, plural, terminationReasonLabel, today } from "../shared/format";
import { lastDay, monthlyMargin } from "./EndingA";
import { listHref, MailButton, PageTitleRow, QuickPills } from "./ListParts";

const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

const ms = (iso: string) => Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);

function monthStart(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}
function addMonths(iso: string, n: number): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  d.setUTCMonth(d.getUTCMonth() + n);
  return d.toISOString().slice(0, 10);
}

export function EndingB({ selected }: { selected: number | null }) {
  const list = useMkContractList({ bucket: "ending", page: 1, page_size: 50 }, "a-ending");
  const items = [...(list.data?.items ?? [])].sort((a, b) => (lastDay(a) ?? "").localeCompare(lastDay(b) ?? ""));
  const from = monthStart(today());
  const lastEnd = items.reduce((m, c) => ((lastDay(c) ?? "") > m ? (lastDay(c) as string) : m), today());
  const to = addMonths(monthStart(lastEnd), 2);
  const span = ms(to) - ms(from);
  const pos = (iso: string) => Math.min(100, Math.max(0, ((ms(iso) - ms(from)) / span) * 100));
  const months: string[] = [];
  for (let m = from; m < to; m = addMonths(m, 1)) months.push(m);

  const groups = new Map<string, typeof items>();
  for (const c of items) {
    const key = (lastDay(c) ?? "").slice(0, 7);
    groups.set(key, [...(groups.get(key) ?? []), c]);
  }

  return (
    <div className="space-y-3">
      <PageTitleRow stats={<>Kończące się: {plural(items.length, OSOBY)} na osi czasu</>} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <QuickPills w="b" view="konczace" compact />
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-lg border border-border bg-muted/50 p-0.5 text-[12.5px] font-medium">
            <span className="rounded-md px-2.5 py-1 text-muted-foreground">Tabela</span>
            <span className="rounded-md bg-card px-2.5 py-1 text-foreground shadow-xs">Oś czasu</span>
          </div>
          <MailButton />
        </div>
      </div>

      <div className="rounded-xl border border-border bg-card shadow-xs">
        <div className="grid grid-cols-[230px_minmax(0,1fr)_170px] border-b border-border">
          <div className="px-4 py-2 text-[10.5px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">Osoba</div>
          <div className="relative h-8">
            {months.map((m) => (
              <div key={m} className="absolute inset-y-0 border-l border-border/70 pl-2 pt-2 text-[11.5px] font-medium capitalize text-muted-foreground" style={{ left: `${pos(m)}%` }}>
                {cap(fmtMonthYear(m))}
              </div>
            ))}
          </div>
          <div className="px-4 py-2 text-right text-[10.5px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">Marża / mies.</div>
        </div>

        {[...groups.entries()].map(([month, rows]) => (
          <div key={month}>
            <div className="border-b border-border/70 bg-muted/40 px-4 py-1.5 text-[12.5px] font-semibold capitalize text-foreground">
              {cap(fmtMonthYear(`${month}-01`))}
              <span className="ml-2 font-normal normal-case text-muted-foreground">
                · {plural(rows.length, OSOBY)} · {fmtPln(rows.reduce((s, c) => s + (monthlyMargin(c) ?? 0), 0))} marży / mies.
              </span>
            </div>
            {rows.map((c) => {
              const end = lastDay(c) as string;
              const days = daysUntil(end) ?? 99;
              const futureOrder = c.client_order_end_date && c.client_order_start_date && c.client_order_end_date > end;
              const agreementOpen = c.contract_type === "b2b" && !c.agreement_termination_mode;
              return (
                <div
                  key={c.id}
                  className={cn("grid h-[46px] grid-cols-[230px_minmax(0,1fr)_170px] items-center border-b border-border/60 hover:bg-muted/30", selected === c.id && "bg-primary/6")}
                >
                  <div className="min-w-0 px-4">
                    <Link href={listHref("b", "konczace", c.id)} className="block truncate text-[13px] font-semibold text-foreground hover:text-primary">
                      {c.candidate_name}
                    </Link>
                    <span className="block truncate text-[11.5px] text-muted-foreground">
                      {c.client_name} · {terminationReasonLabel(c.termination_reason)?.toLowerCase()}
                    </span>
                  </div>
                  <div className="relative h-full">
                    {months.map((m) => (
                      <div key={m} className="absolute inset-y-0 border-l border-border/40" style={{ left: `${pos(m)}%` }} />
                    ))}
                    <div className="absolute inset-y-0 w-px bg-foreground/60" style={{ left: `${pos(today())}%` }} />
                    <div
                      className={cn("absolute top-1/2 h-2.5 -translate-y-1/2 rounded-l-none rounded-r-full", days <= 14 ? "bg-destructive/60" : "bg-warning/60")}
                      style={{ left: 0, width: `${pos(end)}%` }}
                    />
                    <span
                      className="absolute top-1/2 -translate-y-1/2 pl-1.5 text-[11.5px] font-semibold tabular-nums text-foreground"
                      style={{ left: `${pos(end)}%` }}
                    >
                      {fmtDayMonth(end)}
                    </span>
                    {futureOrder ? (
                      <div
                        title="Zamówienie klienta trwa po odejściu — sprawdź zakończenie"
                        className="absolute top-[30px] h-1.5 rounded-full border border-dashed border-primary/70 bg-primary/10"
                        style={{ left: `${pos(c.client_order_start_date as string)}%`, width: `${pos(c.client_order_end_date as string) - pos(c.client_order_start_date as string)}%` }}
                      />
                    ) : null}
                  </div>
                  <div className="px-4 text-right">
                    <span className="block text-[13px] font-medium tabular-nums text-foreground">{fmtPln(monthlyMargin(c))}</span>
                    <span className={cn("block text-[11px]", agreementOpen ? "text-warning" : "text-muted-foreground")}>
                      {agreementOpen ? "umowa nierozwiązana" : "umowa wypowiedziana"}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        ))}
        <div className="flex items-center gap-4 px-4 py-2 text-[11.5px] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-5 rounded-full bg-destructive/60" /> do 14 dni
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-5 rounded-full bg-warning/60" /> później
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-5 rounded-full border border-dashed border-primary/70 bg-primary/10" /> zamówienie klienta trwa po odejściu
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-3 w-px bg-foreground/60" /> dziś
          </span>
        </div>
      </div>
    </div>
  );
}
