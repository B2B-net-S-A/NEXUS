"use client";
// B · Lista pogrupowana po kliencie: nagłówek grupy z liczbą osób, marżą
// miesięczną i tym, co się kończy/startuje; wiersze w jednej linii (36 px),
// więc przy 1280 × 720 widać ok. 12 osób zamiast 9. Pigułki i wyszukiwarka
// w jednym rzędzie, filtry rzadsze w „Filtry”.
import Link from "next/link";
import { ChevronDown, ChevronRight, Layers, Search, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CALM_AMOUNT, CALM_HEAD } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { useMkContractListAll, type MkListItem } from "../shared/data";
import { daysUntil, fmtDate, fmtDayMonth, fmtNum, fmtPln, OSOBY, plural } from "../shared/format";
import { monthlyMargin } from "./EndingA";
import { listHref, MailButton, QuickPills } from "./ListParts";

interface Group {
  clientId: number;
  name: string;
  items: MkListItem[];
  margin: number;
  ending: number;
  starting: number;
}

function groupByClient(items: MkListItem[]): Group[] {
  const map = new Map<number, Group>();
  for (const c of items) {
    const g = map.get(c.client_id) ?? { clientId: c.client_id, name: c.client_name, items: [], margin: 0, ending: 0, starting: 0 };
    g.items.push(c);
    g.margin += monthlyMargin(c) ?? 0;
    if (c.status === "ending") g.ending += 1;
    if ((daysUntil(c.start_date) ?? 0) > 0) g.starting += 1;
    map.set(c.client_id, g);
  }
  return [...map.values()].sort((a, b) => b.items.length - a.items.length);
}

function StatusCell({ c }: { c: MkListItem }) {
  const startIn = daysUntil(c.start_date) ?? 0;
  if (c.status === "ending")
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-foreground">
        <span aria-hidden className="size-1.5 rounded-full bg-warning" />
        do {fmtDayMonth(c.terminated_at ?? c.end_date)}
      </span>
    );
  if (startIn > 0)
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-foreground">
        <span aria-hidden className="size-1.5 rounded-full bg-info" />
        od {fmtDayMonth(c.start_date)}
      </span>
    );
  return <span className="text-[12px] text-muted-foreground/60">—</span>;
}

const ROWS_IN_OPEN_GROUP = 9;

export function ListB({ selected }: { selected: number | null }) {
  const { done, items } = useMkContractListAll({ status: ["active", "ending"] }, 6);
  const groups = groupByClient(items);
  const totalMargin = groups.reduce((s, g) => s + g.margin, 0);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-3">
          <h1 className="text-[22px] font-semibold tracking-tight text-foreground">Kontrakty</h1>
          <p className="text-[13px] text-muted-foreground">
            {done ? (
              <>
                {plural(items.length, ["umowa", "umowy", "umów"])} u {groups.length} klientów · marża {fmtPln(totalMargin)}/mies.
              </>
            ) : (
              "Ładowanie…"
            )}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <MailButton />
          <Button type="button" variant="ghost" size="sm">
            Analityka
          </Button>
          <Button type="button" variant="ghost" size="sm">
            Eksport
          </Button>
          <Button type="button" variant="primary" size="sm">
            + Nowy kontrakt
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <label className="flex h-9 w-[260px] shrink-0 items-center gap-2 rounded-md border border-border bg-card px-3 text-[13px] text-muted-foreground">
          <Search className="size-4 shrink-0" aria-hidden />
          <span className="truncate">Szukaj osoby, klienta…</span>
        </label>
        <QuickPills w="b" view="aktywne" compact />
        <div className="ml-auto flex items-center gap-1.5">
          <Button type="button" variant="outline" size="sm" className="h-9">
            <SlidersHorizontal className="mr-1.5 size-3.5 text-muted-foreground" aria-hidden />
            Filtry
          </Button>
          <Button type="button" variant="outline" size="sm" className="h-9">
            <Layers className="mr-1.5 size-3.5 text-muted-foreground" aria-hidden />
            Grupuj: klient
            <ChevronDown className="ml-1 size-3.5 text-muted-foreground" aria-hidden />
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-xs">
        <table className="w-full min-w-[920px] table-fixed text-[13px]">
          <colgroup>
            <col className="w-[23%]" />
            <col className="w-[27%]" />
            <col className="w-[11%]" />
            <col className="w-[9%]" />
            <col className="w-[9%]" />
            <col className="w-[9%]" />
            <col />
          </colgroup>
          <thead>
            <tr className="border-b border-border">
              <th className={cn(CALM_HEAD, "px-4 py-2 text-left")}>Osoba</th>
              <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Rekrutacja</th>
              <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Od</th>
              <th className={cn(CALM_HEAD, "px-3 py-1.5 text-right leading-4")}>
                Konsultant<span className="block text-[10.5px] font-normal normal-case tracking-normal">zł/h</span>
              </th>
              <th className={cn(CALM_HEAD, "px-3 py-1.5 text-right leading-4")}>
                Klient<span className="block text-[10.5px] font-normal normal-case tracking-normal">zł/h</span>
              </th>
              <th className={cn(CALM_HEAD, "px-3 py-1.5 text-right leading-4")}>
                Marża<span className="block text-[10.5px] font-normal normal-case tracking-normal">zł/h</span>
              </th>
              <th className={cn(CALM_HEAD, "px-4 py-2 text-left")}>Wkrótce</th>
            </tr>
          </thead>
          {groups.map((g, gi) => {
            const open = gi === 0;
            return (
              <tbody key={g.clientId}>
                <tr className="border-b border-border bg-muted/40">
                  <td colSpan={7} className="px-4 py-2">
                    <div className="flex items-center gap-2 text-[13px]">
                      {open ? <ChevronDown className="size-4 text-muted-foreground" aria-hidden /> : <ChevronRight className="size-4 text-muted-foreground" aria-hidden />}
                      <span className="font-semibold text-foreground">{g.name}</span>
                      <span className="text-muted-foreground">· {plural(g.items.length, OSOBY)}</span>
                      <span className="text-muted-foreground">· marża {fmtPln(g.margin)}/mies.</span>
                      {g.ending ? <span className="font-medium text-warning">· {g.ending} odchodzi</span> : null}
                      {g.starting ? <span className="font-medium text-info">· {g.starting} startuje</span> : null}
                    </div>
                  </td>
                </tr>
                {open
                  ? g.items.slice(0, ROWS_IN_OPEN_GROUP).map((c) => (
                      <tr key={c.id} className={cn("h-9 border-b border-border/60 hover:bg-muted/40", selected === c.id && "bg-primary/6")}>
                        <td className="truncate px-4 pl-10">
                          <Link href={listHref("b", "aktywne", c.id)} className="font-medium text-foreground hover:text-primary">
                            {c.candidate_name}
                          </Link>
                        </td>
                        <td className="truncate px-3 text-muted-foreground" title={c.job_title ?? undefined}>
                          {c.job_title ?? "—"}
                        </td>
                        <td className="px-3 tabular-nums text-foreground">{fmtDate(c.start_date)}</td>
                        <td className={cn(CALM_AMOUNT, "px-3")}>{fmtNum(c.rate_candidate)}</td>
                        <td className={cn(CALM_AMOUNT, "px-3", c.rate_client == null && "text-muted-foreground/50")}>{fmtNum(c.rate_client)}</td>
                        <td className={cn(CALM_AMOUNT, "px-3 font-medium")}>{fmtNum(c.margin)}</td>
                        <td className="px-4">
                          <StatusCell c={c} />
                        </td>
                      </tr>
                    ))
                  : null}
                {open && g.items.length > ROWS_IN_OPEN_GROUP ? (
                  <tr className="border-b border-border">
                    <td colSpan={7} className="px-4 py-1.5 pl-10 text-[12.5px] font-medium text-primary">
                      Pokaż wszystkie {plural(g.items.length, OSOBY)} u klienta {g.name} →
                    </td>
                  </tr>
                ) : null}
              </tbody>
            );
          })}
        </table>
      </div>
    </div>
  );
}
