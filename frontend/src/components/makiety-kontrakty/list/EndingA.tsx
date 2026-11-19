"use client";
// A · „Kończące się” jako odejścia do domknięcia: ostatni dzień i ile zostało,
// powód, czy umowa B2B jest rozwiązana, ile marży odchodzi i co się nie zgadza
// (np. zakończenie przy zamówieniu, które trwa dalej). Dziś ten widok to ta sama
// tabela co „Aktywne” z datą końca drobnym drukiem pod datą startu.
import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_UNIT } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { useMkContractList, type MkListItem } from "../shared/data";
import { daysUntil, fmtDate, fmtPln, OSOBY, plural, relDays, terminationReasonLabel } from "../shared/format";
import { listHref, MailButton, PageTitleRow, QuickPills } from "./ListParts";

export function lastDay(c: MkListItem): string | null {
  return c.terminated_at ?? c.end_date ?? c.latest_order_end_date ?? c.client_order_end_date;
}

export function monthlyMargin(c: MkListItem): number | null {
  if (c.monthly_margin != null) return c.monthly_margin;
  if (c.margin == null) return null;
  return c.margin * (c.billing_hours_per_month ?? 168);
}

/** Niespójność do sprawdzenia: zamówienie klienta trwa po ostatnim dniu. */
export function conflict(c: MkListItem): string | null {
  const end = lastDay(c);
  if (!end) return null;
  if (c.client_order_end_date && c.client_order_start_date && c.client_order_end_date > end) {
    return `Zamówienie ${fmtDate(c.client_order_start_date)} – ${fmtDate(c.client_order_end_date)} trwa po odejściu — sprawdź zakończenie`;
  }
  return null;
}

export function EndingA({ selected }: { selected: number | null }) {
  const list = useMkContractList({ bucket: "ending", page: 1, page_size: 50 }, "a-ending");
  const items = [...(list.data?.items ?? [])].sort((a, b) => (lastDay(a) ?? "").localeCompare(lastDay(b) ?? ""));
  const lost = items.reduce((s, c) => s + (monthlyMargin(c) ?? 0), 0);
  const open = items.filter((c) => c.contract_type === "b2b" && !c.agreement_termination_mode).length;
  const latest = items.length ? lastDay(items[items.length - 1]) : null;

  return (
    <div className="space-y-3">
      <PageTitleRow stats={<>Kończące się: {plural(items.length, OSOBY)} odchodzi{latest ? ` do ${fmtDate(latest)}` : ""}</>} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <QuickPills w="a" view="konczace" />
        <MailButton />
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 rounded-xl border border-border bg-card px-4 py-2.5 text-[13px] shadow-xs">
        <span>
          <strong className="text-[15px] font-semibold tabular-nums text-foreground">{plural(items.length, OSOBY)}</strong>{" "}
          <span className="text-muted-foreground">odchodzi do {fmtDate(latest)}</span>
        </span>
        <span>
          <strong className="text-[15px] font-semibold tabular-nums text-foreground">{fmtPln(lost)}</strong>{" "}
          <span className="text-muted-foreground">marży miesięcznie odejdzie</span>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden className="size-1.5 rounded-full bg-warning" />
          <strong className="text-[15px] font-semibold tabular-nums text-foreground">{open}</strong>{" "}
          <span className="text-muted-foreground">z {items.length} umów B2B bez zapisanego rozwiązania</span>
        </span>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-xs">
        <table className="w-full min-w-[920px] table-fixed text-[13px]">
          <colgroup>
            <col className="w-[22%]" />
            <col className="w-[13%]" />
            <col className="w-[16%]" />
            <col className="w-[13%]" />
            <col className="w-[11%]" />
            <col />
          </colgroup>
          <thead>
            <tr className="border-b border-border">
              <th className={cn(CALM_HEAD, "px-4 py-2.5 text-left")}>Osoba i klient</th>
              <th className={cn(CALM_HEAD, "px-3 py-2.5 text-left")}>Ostatni dzień</th>
              <th className={cn(CALM_HEAD, "px-3 py-2.5 text-left")}>Powód</th>
              <th className={cn(CALM_HEAD, "px-3 py-2.5 text-left")}>Umowa B2B</th>
              <th className={cn(CALM_HEAD, "px-3 py-2.5 text-right")}>
                Marża<span className={CALM_UNIT}>zł/mies.</span>
              </th>
              <th className={cn(CALM_HEAD, "px-4 py-2.5 text-left")}>Do zrobienia</th>
            </tr>
          </thead>
          <tbody>
            {items.map((c) => {
              const end = lastDay(c);
              const days = daysUntil(end) ?? 99;
              const agreementOpen = c.contract_type === "b2b" && !c.agreement_termination_mode;
              const warn = conflict(c);
              return (
                <tr key={c.id} className={cn(CALM_ROW, "h-[54px] align-middle hover:bg-muted/40", selected === c.id && "bg-primary/6")}>
                  <td className="px-4 py-2">
                    <Link href={listHref("a", "konczace", c.id)} className="block font-semibold leading-5 text-foreground hover:text-primary">
                      {c.candidate_name}
                    </Link>
                    <span className="block truncate text-[11.5px] text-muted-foreground" title={c.client_name}>
                      {c.client_name}
                    </span>
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    <span className="block font-semibold text-foreground">{fmtDate(end)}</span>
                    <span className={cn("block text-[11.5px] font-medium", days <= 14 ? "text-destructive" : "text-muted-foreground")}>{relDays(end)}</span>
                  </td>
                  <td className="px-3 py-2 text-foreground">{terminationReasonLabel(c.termination_reason) ?? "—"}</td>
                  <td className="px-3 py-2">
                    <span className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-foreground">
                      <span aria-hidden className={cn("size-1.5 rounded-full", agreementOpen ? "bg-warning" : "bg-success")} />
                      {agreementOpen ? "nierozwiązana" : c.agreement_termination_mode === "notice" ? "wypowiedziana" : "rozwiązana"}
                    </span>
                  </td>
                  <td className={cn(CALM_AMOUNT, "px-3 py-2 font-medium text-foreground")}>{fmtPln(monthlyMargin(c)).replace(" zł", "")}</td>
                  <td className="px-4 py-2">
                    {warn ? (
                      <span className="flex min-w-0 items-start gap-1.5 text-[12px] leading-4 text-foreground">
                        <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden />
                        <span className="line-clamp-2">{warn}</span>
                      </span>
                    ) : agreementOpen ? (
                      <Button type="button" variant="outline" size="sm">
                        Zapisz rozwiązanie umowy
                      </Button>
                    ) : (
                      <span className="text-[12.5px] text-muted-foreground/60">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[12.5px] text-muted-foreground">
        „Kończące się” to osoby z zapisanym zakończeniem współpracy albo umową kończącą się w 30 dni — ta sama reguła co licznik na pigułce.
      </p>
    </div>
  );
}
