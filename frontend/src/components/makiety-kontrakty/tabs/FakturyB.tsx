"use client";
// B · Faktury — faktury konsultanta z KSeF zamiast dzisiejszej zakładki, która
// czyta tabelę `invoices` (na kopii produkcji 19.11.2026: 0 wierszy) i zawsze
// pokazuje „Brak faktur”. Faktury z KSeF leżą w rozliczeniach osoby, miesiąc po
// miesiącu (`/api/finance/settlements/contract/{id}?month=`), więc makieta
// zbiera ostatnie 12 miesięcy od startu kontraktu. Liczby w jednej linii,
// zwarta tabela, uwagi z rozliczenia pod tabelą. Hook i tabelę bierze też
// zakładka „Pieniądze” kierunku A.
import { useQueries } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE, CALM_UNIT } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { warsawDateOf } from "@/lib/warsaw-date";
import { useMkContract } from "../shared/data";
import { fmtDate, fmtMonthShort, fmtMonthYear, fmtPln, relDays, today } from "../shared/format";
import type { TabProps } from "./types";

export interface KsefInvoice {
  id: number;
  ksef_number: string;
  invoice_number: string | null;
  issue_date: string | null;
  acquired_at: string | null;
  seller_name: string | null;
  seller_nip: string;
  /** `known` — NIP z kontraktu, `confirmed` — zatwierdzony ręcznie, `suggested` — do zatwierdzenia. */
  nip_state: "known" | "suggested" | "confirmed";
  is_correction?: boolean;
  net_amount: string | null;
  gross_amount: string | null;
  due_date: string | null;
  /** Miesiąc rozliczenia „RRRR-MM”. */
  period: string;
}

export interface KsefCheck {
  state: "ok" | "warn" | "fail" | "none";
  title: string;
  detail?: string | null;
  period: string;
}

interface SettlementDetail {
  contractor_invoice?: {
    state: string;
    invoices: Omit<KsefInvoice, "period">[];
    checks: Omit<KsefCheck, "period">[];
  };
}

/** Miesiące rozliczeń od bieżącego wstecz (najwyżej `max`), nie wcześniej niż start kontraktu. */
function settlementMonths(start: string | null | undefined, max = 12): string[] {
  const now = today().slice(0, 7);
  const first = start ? start.slice(0, 7) : now;
  const out: string[] = [];
  let [y, m] = now.split("-").map(Number);
  while (out.length < max) {
    const key = `${y}-${String(m).padStart(2, "0")}`;
    if (key < first) break;
    out.push(key);
    m -= 1;
    if (m === 0) {
      m = 12;
      y -= 1;
    }
  }
  return out;
}

/** Faktury konsultanta z KSeF z rozliczeń kontraktu (tylko GET, miesiąc po miesiącu). */
export function useKsefInvoices(contractId: number, start: string | null | undefined, ready: boolean) {
  const months = ready ? settlementMonths(start) : [];
  const results = useQueries({
    queries: months.map((month) => ({
      queryKey: ["mk-ksef-invoices", contractId, month],
      queryFn: () =>
        api
          .get<SettlementDetail>(`/api/finance/settlements/contract/${contractId}`, { params: { month } })
          .then((r) => r.data),
      retry: false,
      staleTime: 60_000,
    })),
  });
  const failed = results.find((r) => r.isError);
  const isLoading = !ready || results.some((r) => r.isLoading);
  const invoices: KsefInvoice[] = [];
  const checks: KsefCheck[] = [];
  results.forEach((r, i) => {
    const block = r.data?.contractor_invoice;
    if (!block) return;
    for (const inv of block.invoices) invoices.push({ ...inv, period: months[i] });
    for (const ch of block.checks) checks.push({ ...ch, period: months[i] });
  });
  invoices.sort((a, b) => (b.acquired_at ?? b.issue_date ?? "").localeCompare(a.acquired_at ?? a.issue_date ?? ""));
  return {
    months,
    invoices,
    checks,
    isLoading,
    error: failed ? apiErrorMessage(failed.error, "Nie udało się pobrać faktur z KSeF.") : null,
    isSuccess: ready && !isLoading && !failed,
  };
}

const NUM2 = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** „1 234,50”, „−144,00” — kwota z groszami bez waluty (waluta w nagłówku kolumny). */
export function amount2(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  const s = NUM2.format(Math.abs(n)).replace(/^(\d)(\d{3}),/, "$1 $2,");
  return n < 0 ? `−${s}` : s;
}

const NIP_STATE: Record<KsefInvoice["nip_state"], { label: string; tone: StatusDotTone }> = {
  known: { label: "zgodny z kontraktem", tone: "success" },
  confirmed: { label: "zatwierdzony ręcznie", tone: "success" },
  suggested: { label: "do zatwierdzenia", tone: "warning" },
};

const MONTHS_GEN = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września", "października", "listopada", "grudnia"];

/** „października 2026” — do „od …”. */
export function monthGen(period: string): string {
  const [y, m] = period.split("-");
  return `${MONTHS_GEN[Number(m) - 1] ?? m} ${y}`;
}

function sameName(a: string | null | undefined, b: string | null | undefined): boolean {
  const norm = (s: string) => s.toLocaleLowerCase("pl-PL").replace(/\s+/g, " ").trim();
  return Boolean(a && b && norm(a) === norm(b));
}

/** Tabela faktur: Okres · Numer · Netto · Brutto · Zgodność NIP · Wpłynęła. */
export function KsefInvoiceTable({
  invoices,
  candidateName,
  dense = false,
}: {
  invoices: KsefInvoice[];
  candidateName?: string | null;
  dense?: boolean;
}) {
  const cell = dense ? "py-2 pr-3" : "py-2 pr-4";
  return (
    <table className={cn("w-full text-[13px]", dense && "table-fixed")}>
      {dense ? (
        <colgroup>
          <col className="w-[76px]" />
          <col />
          <col className="w-[70px]" />
          <col className="w-[76px]" />
          <col className="w-[156px]" />
          <col className="w-[84px]" />
        </colgroup>
      ) : null}
      <thead>
        <tr className="border-b border-border">
          <th className={cn(CALM_HEAD, cell, "text-left")}>Okres</th>
          <th className={cn(CALM_HEAD, cell, "text-left")}>Numer</th>
          <th className={cn(CALM_HEAD, cell, "text-right")}>
            Netto<span className={CALM_UNIT}>zł</span>
          </th>
          <th className={cn(CALM_HEAD, cell, "text-right")}>
            Brutto<span className={CALM_UNIT}>zł</span>
          </th>
          <th className={cn(CALM_HEAD, cell, "text-left")}>Zgodność NIP</th>
          <th className={cn(CALM_HEAD, "py-2 text-left")}>Wpłynęła</th>
        </tr>
      </thead>
      <tbody>
        {invoices.map((inv) => {
          const nip = NIP_STATE[inv.nip_state] ?? { label: inv.nip_state, tone: "neutral" as const };
          const arrived = warsawDateOf(inv.acquired_at);
          const issued = inv.issue_date && inv.issue_date !== arrived ? `wystawiona ${fmtDate(inv.issue_date)}` : null;
          const seller = sameName(inv.seller_name, candidateName) ? null : inv.seller_name;
          const subline = [inv.is_correction ? "korekta" : null, seller].filter(Boolean).join(" · ");
          return (
            <tr key={inv.id} className={cn(CALM_ROW, "align-middle")}>
              <td className={cn(cell, "whitespace-nowrap text-foreground")}>{dense ? fmtMonthShort(inv.period) : fmtMonthYear(inv.period)}</td>
              <td className={cn(cell, "min-w-0")}>
                <span className="block truncate font-medium text-foreground" title={`Numer KSeF: ${inv.ksef_number}`}>
                  {inv.invoice_number ?? inv.ksef_number}
                </span>
                {subline ? (
                  <span className={cn(CALM_SUBLINE, "truncate", !dense && "max-w-[260px]")} title={subline}>
                    {subline}
                  </span>
                ) : null}
              </td>
              <td className={cn(cell, CALM_AMOUNT)}>{amount2(inv.net_amount)}</td>
              <td className={cn(cell, CALM_AMOUNT)}>{amount2(inv.gross_amount)}</td>
              <td className={cell}>
                <StatusDot tone={nip.tone} note={inv.nip_state === "suggested" ? `NIP ${inv.seller_nip}` : undefined}>
                  {nip.label}
                </StatusDot>
              </td>
              <td className="whitespace-nowrap py-2 tabular-nums text-foreground">
                {fmtDate(arrived)}
                {issued ? <span className={CALM_SUBLINE}>{issued}</span> : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** Uwagi z rozliczenia (ostrzeżenia z API), bez podpowiedzi NIP — tę pokazuje kolumna „Zgodność NIP”. */
export function KsefChecks({ checks }: { checks: KsefCheck[] }) {
  const open = checks.filter((c) => (c.state === "warn" || c.state === "fail") && c.title !== "NIP z KSeF do zatwierdzenia");
  if (open.length === 0) return null;
  const periods = [...new Set(open.map((c) => c.period))];
  return (
    <div className="mt-3 space-y-1">
      <p className="text-[12px] font-medium text-foreground">
        Do wyjaśnienia w rozliczeniu za {periods.map((p) => fmtMonthYear(p)).join(", ")}
      </p>
      <ul className="space-y-1">
        {open.map((c, i) => (
          <li key={`${c.period}-${i}`} className="flex min-w-0 items-baseline gap-2 text-[12.5px] leading-5">
            <span
              aria-hidden
              className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", c.state === "fail" ? "bg-destructive" : "bg-warning")}
            />
            <span className="min-w-0 truncate" title={c.detail ? `${c.title}. ${c.detail}` : c.title}>
              <span className="text-foreground">{c.title}</span>
              {c.detail ? <span className="text-muted-foreground"> — {c.detail}</span> : null}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Pusty stan: skąd biorą się faktury i co zrobić, gdy brak. */
export const KSEF_EMPTY = "Faktury konsultanta przychodzą z KSeF; ta osoba nie ma jeszcze żadnej.";

export function FakturyB({ contractId }: TabProps) {
  const c = useMkContract(contractId).data;
  const ksef = useKsefInvoices(contractId, c?.start_date, Boolean(c));
  if (!c) return null;

  const year = today().slice(0, 4);
  const netYear = ksef.invoices
    .filter((i) => i.period.startsWith(year) && i.net_amount != null)
    .reduce((sum, i) => sum + Number(i.net_amount), 0);
  const corrections = ksef.invoices.filter((i) => i.is_correction).length;
  const last = ksef.invoices[0];
  const lastDay = warsawDateOf(last?.acquired_at ?? last?.issue_date ?? null);
  const firstMonth = ksef.months[ksef.months.length - 1];
  const strong = "font-semibold tabular-nums text-foreground";

  return (
    <section className="rounded-xl border border-border bg-card p-4 shadow-xs">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {ksef.isSuccess && ksef.invoices.length > 0 ? (
            <p className="text-[13px] leading-6 text-muted-foreground">
              Faktur: <span className={strong}>{ksef.invoices.length}</span>
              {corrections ? ` (korekty: ${corrections})` : ""}
              <span aria-hidden className="mx-2">·</span>
              Suma netto {year}: <span className={strong}>{fmtPln(netYear, 2)}</span>
              <span aria-hidden className="mx-2">·</span>
              Ostatnia: <span className={strong} title={lastDay ? relDays(lastDay) : undefined}>{fmtDate(lastDay)}</span>
            </p>
          ) : (
            <h2 className="text-[13.5px] font-semibold leading-6 text-foreground">Faktury konsultanta</h2>
          )}
          {ksef.invoices.length > 0 ? (
            <p className="text-[12px] text-muted-foreground">
              Z KSeF, dopasowane po NIP z kontraktu{firstMonth ? ` · sprawdzono od ${monthGen(firstMonth)}` : ""}
            </p>
          ) : null}
        </div>
        <Button type="button" variant="outline" size="sm">
          <Plus className="mr-1 size-3.5" aria-hidden />
          Dodaj fakturę
        </Button>
      </div>

      <div className="mt-3">
        {ksef.isLoading ? (
          <p className="text-[13px] text-muted-foreground">Ładowanie faktur z KSeF…</p>
        ) : ksef.error ? (
          <p role="alert" className="text-[13px] text-destructive">
            {ksef.error}
          </p>
        ) : ksef.invoices.length === 0 ? (
          <p className="text-[13px] text-muted-foreground">
            Faktury konsultanta przychodzą z KSeF same, dopasowane po NIP z kontraktu; ta osoba nie ma jeszcze żadnej
            {firstMonth ? ` (sprawdzono od ${monthGen(firstMonth)})` : ""}. Fakturę spoza KSeF można dodać ręcznie.
          </p>
        ) : (
          <>
            <KsefInvoiceTable invoices={ksef.invoices} candidateName={c.candidate_name} dense />
            <KsefChecks checks={ksef.checks} />
            {corrections ? (
              <p className="mt-3 text-[12px] text-muted-foreground">Kwoty korekt to różnice do faktury korygowanej.</p>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}
