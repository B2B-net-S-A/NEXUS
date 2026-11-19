"use client";
// A · Lista „Aktywne” z kolumną „Co dalej”: pełne nazwiska, bez kolumn „Typ”
// i „Status” (prawie zawsze „B2B” i „Aktywny”), bez filtra „Status: 2”
// dublującego pigułki. To, co trzeba zrobić, stoi w wierszu słowami.
import Link from "next/link";
import { ChevronDown, Search, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { useMkContractList, type MkListItem } from "../shared/data";
import {
  daysUntil,
  fmtDate,
  fmtDayMonth,
  curUnit,
  fmtNum,
  marginPct,
  PROLONGATION_LABEL,
  relDays,
  terminationReasonLabel,
} from "../shared/format";
import { listHref, MailButton, PageTitleRow, QuickPills } from "./ListParts";

type Tone = "info" | "warning" | "danger" | "muted";
interface Next {
  tone: Tone;
  text: string;
}

/** „Co dalej” z faktów wiersza — najpilniejsze pierwsze. */
export function nextSteps(c: MkListItem): Next[] {
  const out: Next[] = [];
  const startIn = daysUntil(c.start_date);
  const orderEnd = c.latest_order_end_date ?? c.client_order_end_date;
  const orderIn = daysUntil(orderEnd);
  if (c.status === "ending" || (c.terminated_at && (daysUntil(c.terminated_at) ?? -1) >= 0)) {
    const end = c.terminated_at ?? c.end_date;
    const reason = terminationReasonLabel(c.termination_reason);
    out.push({
      tone: (daysUntil(end) ?? 99) <= 14 ? "danger" : "warning",
      text: `Odchodzi ${fmtDayMonth(end)} (${relDays(end)})${reason ? ` · ${reason.toLowerCase()}` : ""}`,
    });
  } else if (orderIn != null && orderIn >= 0 && orderIn <= 45) {
    out.push({
      tone: orderIn <= 14 ? "danger" : "warning",
      text: `Zamówienie do ${fmtDayMonth(orderEnd)} · ${(PROLONGATION_LABEL[c.prolongation_status ?? "unknown"] ?? "").toLowerCase()}`,
    });
  }
  if (startIn != null && startIn > 0) out.push({ tone: "info", text: `Startuje ${fmtDayMonth(c.start_date)} (${relDays(c.start_date)})` });
  if ((c.missing_fields ?? []).length > 0) out.push({ tone: "warning", text: `Uzupełnij: ${c.missing_fields!.length} braki` });
  if (c.rate_client == null) out.push({ tone: "muted", text: "Brak stawki klienta" });
  if (!orderEnd && startIn != null && startIn <= 0 && c.status === "active") out.push({ tone: "muted", text: "Bez zamówienia klienta" });
  return out;
}

const DOT: Record<Tone, string> = {
  info: "bg-info",
  warning: "bg-warning",
  danger: "bg-destructive",
  muted: "bg-muted-foreground/40",
};

export function NextCell({ steps }: { steps: Next[] }) {
  if (steps.length === 0) return <span className="text-muted-foreground/50">—</span>;
  const [first, ...rest] = steps;
  return (
    <div className="min-w-0">
      <p className={cn("flex items-center gap-1.5 text-[12.5px] font-medium", first.tone === "muted" ? "text-muted-foreground" : "text-foreground")}>
        <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", DOT[first.tone])} />
        <span className="truncate">{first.text}</span>
      </p>
      {rest.length ? <p className="truncate pl-3 text-[11.5px] text-muted-foreground">{rest.map((r) => r.text).join(" · ")}</p> : null}
    </div>
  );
}

export function ListA({ selected }: { selected: number | null }) {
  const list = useMkContractList({ status: ["active", "ending"], page: 1, page_size: 20 }, "a-active");
  const data = list.data;
  const futureStarts = data?.future_start_total ?? null;

  return (
    <div className="space-y-3">
      <PageTitleRow
        stats={
          data ? (
            <>
              {data.contractors_total ?? "…"} osób · {data.contracts_total ?? data.total} umów obowiązuje
              {futureStarts ? ` · ${futureStarts} startuje wkrótce` : ""}
            </>
          ) : (
            "…"
          )
        }
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <QuickPills w="a" view="aktywne" />
        <MailButton />
      </div>
      <div className="flex items-center gap-2">
        <label className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border border-border bg-card px-3 text-[13px] text-muted-foreground">
          <Search className="size-4 shrink-0" aria-hidden />
          <span className="truncate">Szukaj osoby, klienta albo rekrutacji…</span>
        </label>
        <Button type="button" variant="outline" size="sm" className="h-9">
          Klient: wszyscy
          <ChevronDown className="ml-1.5 size-3.5 text-muted-foreground" aria-hidden />
        </Button>
        <Button type="button" variant="outline" size="sm" className="h-9" title="Typ umowy, daty startu i końca, umowa nierozwiązana">
          <SlidersHorizontal className="mr-1.5 size-3.5 text-muted-foreground" aria-hidden />
          Więcej filtrów
        </Button>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-xs">
        <table className="w-full min-w-[920px] table-fixed text-[13px]">
          <colgroup>
            <col className="w-[19%]" />
            <col className="w-[19%]" />
            <col className="w-[12%]" />
            <col className="w-[8%]" />
            <col className="w-[8%]" />
            <col className="w-[8%]" />
            <col />
          </colgroup>
          <thead>
            <tr className="border-b border-border">
              <th className={cn(CALM_HEAD, "px-4 py-2.5 text-left")}>Osoba</th>
              <th className={cn(CALM_HEAD, "px-3 py-2.5 text-left")}>Klient</th>
              <th className={cn(CALM_HEAD, "px-3 py-2.5 text-left")} title="Start umowy → koniec bieżącego zamówienia klienta">Okres</th>
              <th className={cn(CALM_HEAD, "px-3 py-2 text-right leading-4")}>
                Konsultant<span className="block text-[10.5px] font-normal normal-case tracking-normal">zł/h</span>
              </th>
              <th className={cn(CALM_HEAD, "px-3 py-2 text-right leading-4")}>
                Klient<span className="block text-[10.5px] font-normal normal-case tracking-normal">zł/h</span>
              </th>
              <th className={cn(CALM_HEAD, "px-3 py-2 text-right leading-4")}>
                Marża<span className="block text-[10.5px] font-normal normal-case tracking-normal">zł/h</span>
              </th>
              <th className={cn(CALM_HEAD, "px-4 py-2.5 text-left")}>Co dalej</th>
            </tr>
          </thead>
          <tbody>
            {(data?.items ?? []).map((c) => {
              const orderEnd = c.latest_order_end_date ?? c.client_order_end_date;
              const active = selected === c.id;
              return (
                <tr key={c.id} className={cn(CALM_ROW, "h-[48px] align-middle hover:bg-muted/40", active && "bg-primary/6")}>
                  <td className="px-4 py-1.5">
                    <Link href={listHref("a", "aktywne", c.id)} className="block font-semibold leading-5 text-foreground hover:text-primary">
                      {c.candidate_name}
                    </Link>
                    {c.contract_type !== "b2b" ? <span className="text-[11px] text-muted-foreground">{c.contract_type.toUpperCase()}</span> : null}
                  </td>
                  <td className="px-3 py-1.5">
                    <span className="block truncate font-medium text-foreground" title={c.client_name}>
                      {c.client_name}
                    </span>
                    {c.job_title ? (
                      <span className="block truncate text-[11.5px] text-muted-foreground" title={c.job_title}>
                        {c.job_title}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-1.5 tabular-nums">
                    <span className="block text-foreground">{fmtDate(c.start_date)}</span>
                    <span className="block text-[11.5px] text-muted-foreground" title={orderEnd ? "koniec bieżącego zamówienia klienta" : undefined}>
                      → {orderEnd ? fmtDate(orderEnd) : c.end_date ? fmtDate(c.end_date) : "—"}
                    </span>
                  </td>
                  <td className={cn(CALM_AMOUNT, "px-3 py-1.5")}>{fmtNum(c.rate_candidate)}</td>
                  <td className={cn(CALM_AMOUNT, "px-3 py-1.5", c.rate_client == null && "text-muted-foreground/50")}>
                    {fmtNum(c.rate_client)}
                    {c.rate_client != null && curUnit(c.rate_client_currency) !== "zł" ? <span className="ml-1 text-[11px] text-muted-foreground">{curUnit(c.rate_client_currency)}</span> : null}
                  </td>
                  <td className={cn(CALM_AMOUNT, "px-3 py-1.5")}>
                    {c.margin != null ? (
                      <>
                        <span className="block font-medium text-foreground">{fmtNum(c.margin)}</span>
                        <span className="block text-[11px] text-muted-foreground">{marginPct(c.rate_client, c.rate_candidate, c.rate_client_currency, c.rate_candidate_currency)}</span>
                      </>
                    ) : (
                      <span className="text-muted-foreground/50">—</span>
                    )}
                  </td>
                  <td className="px-4 py-1.5">
                    <NextCell steps={nextSteps(c)} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[12.5px] text-muted-foreground">
        Strona 1 z {data ? Math.ceil(data.total / 20) : "…"} · sortowanie: najnowszy start
      </p>
    </div>
  );
}
