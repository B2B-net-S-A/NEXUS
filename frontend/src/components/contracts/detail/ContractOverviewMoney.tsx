"use client";
// Karta „Pieniądze” w Przeglądzie kontraktu (przebudowa 19.11.2026, wariant A):
// trzy liczby po ludzku, marża miesięczna, ostatnia zmiana stawek bez kroków
// „zastąpionych tego samego dnia” i porównanie jednym zdaniem. Pełne stawki,
// harmonogram, premie i faktury są w zakładce „Pieniądze”.
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { contractsApi } from "@/lib/api";
import { fmtDatePl } from "@/lib/contract-happening";
import { formatNbpDate, formatNbpRate, formatWholeAmount } from "@/components/contracts/rates/rate-format";

/** Kurs EUR → PLN z tabeli A NBP, który API kontraktu zwraca przy umowie w EUR. */
export interface OverviewEurPlnRate {
  rate: number;
  effective_date: string;
  source: string;
  table: string;
}

interface RateStep {
  rate: number;
  effective_from: string | null;
}

export interface ContractOverviewMoneyProps {
  contractId: number;
  rateClient: number | null;
  rateCandidate: number | null;
  margin: number | null;
  monthlyMargin: number | null;
  hoursPerMonth: number | null;
  clientCurrency: string | null;
  candidateCurrency: string | null;
  frameworkRate: number | null;
  clientSchedule: RateStep[];
  candidateSchedule: RateStep[];
  showBenchmark: boolean;
  eurPlnRate: OverviewEurPlnRate | null;
  onOpenMoney: () => void;
}

interface Benchmark {
  contract_rate_monthly?: number | null;
  internal_median_monthly?: number | null;
  internal_sample_size?: number | null;
  role_used?: string | null;
}

const num = (v: number | null | undefined) =>
  v == null ? "—" : v.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pln = (v: number) => `${Math.round(v).toLocaleString("pl-PL").replace(/^(\d)(\d{3})$/, "$1 $2")} zł`;
const unit = (cur: string | null) => (!cur || cur === "PLN" ? "zł" : cur);

/** Kroki bez wpisów zastąpionych krokiem z tą samą datą (ostatni wpis z daty wygrywa). */
function liveSteps(steps: RateStep[]): RateStep[] {
  const byDate = new Map<string, RateStep>();
  for (const s of steps) byDate.set(s.effective_from ?? "", s);
  return [...byDate.values()].sort((a, b) => (a.effective_from ?? "").localeCompare(b.effective_from ?? ""));
}

export function lastRateChange(client: RateStep[], candidate: RateStep[]): string | null {
  const cl = liveSteps(client);
  const ca = liveSteps(candidate);
  const parts: string[] = [];
  let date: string | null = null;
  if (cl.length >= 2 && cl[cl.length - 2].rate !== cl[cl.length - 1].rate) {
    parts.push(`klient ${num(cl[cl.length - 2].rate)} → ${num(cl[cl.length - 1].rate)}`);
    date = cl[cl.length - 1].effective_from;
  }
  if (ca.length >= 2 && ca[ca.length - 2].rate !== ca[ca.length - 1].rate) {
    parts.push(`kandydat ${num(ca[ca.length - 2].rate)} → ${num(ca[ca.length - 1].rate)}`);
    date = date ?? ca[ca.length - 1].effective_from;
  }
  if (parts.length === 0) return null;
  return `${date ? `od ${fmtDatePl(date)}: ` : ""}${parts.join(", ")}`;
}

export function ContractOverviewMoney(p: ContractOverviewMoneyProps) {
  const bench = useQuery({
    queryKey: ["contract-benchmark", p.contractId],
    queryFn: async () => (await contractsApi.benchmark(p.contractId)).data as Benchmark,
    enabled: p.showBenchmark,
    retry: false,
  }).data;
  const mixedCurrency = unit(p.clientCurrency) !== unit(p.candidateCurrency);
  // Marża jest w walucie kontraktu (obie strony w tej samej), nie zawsze w złotych.
  const marginUnit = unit(p.clientCurrency);
  const monthly = p.monthlyMargin ?? (p.margin != null ? p.margin * (p.hoursPerMonth ?? 168) : null);
  // Przy EUR równowartość w złotych tym samym kursem NBP, którym liczą statystyki.
  const nbp =
    marginUnit === "EUR" && p.eurPlnRate && Number.isFinite(p.eurPlnRate.rate) && p.eurPlnRate.rate > 0
      ? p.eurPlnRate
      : null;
  const pct = !mixedCurrency && p.rateClient && p.rateCandidate != null ? ((p.rateClient - p.rateCandidate) / p.rateClient) * 100 : null;
  const change = lastRateChange(p.clientSchedule, p.candidateSchedule);
  const benchLine = (() => {
    if (!bench?.contract_rate_monthly || !bench.internal_median_monthly) return null;
    const diff = Math.round(((bench.contract_rate_monthly - bench.internal_median_monthly) / bench.internal_median_monthly) * 100);
    const where = diff === 0 ? "równo z naszą medianą" : `${Math.abs(diff)} % ${diff > 0 ? "powyżej" : "poniżej"} naszej mediany`;
    return `Stawka klienta ${pln(bench.contract_rate_monthly)}/mies. — ${where}${bench.role_used ? ` dla roli ${bench.role_used}` : ""}${bench.internal_sample_size ? ` (${bench.internal_sample_size} umów)` : ""}.`;
  })();

  return (
    <section className="rounded-xl border border-border bg-card p-4 shadow-xs" aria-labelledby="overview-money-h">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 id="overview-money-h" className="text-[13.5px] font-semibold text-foreground">
          Pieniądze
        </h2>
        <button type="button" onClick={p.onOpenMoney} className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:underline">
          Stawki, premie i faktury <ArrowRight className="size-3.5" aria-hidden />
        </button>
      </div>
      <dl className="grid grid-cols-3 gap-3">
        <div>
          <dt className="text-[11.5px] text-muted-foreground">Klient płaci</dt>
          <dd className="text-[19px] font-semibold tabular-nums text-foreground">{num(p.rateClient)}</dd>
          <dd className="text-[11px] text-muted-foreground">{unit(p.clientCurrency)}/h</dd>
        </div>
        <div>
          <dt className="text-[11.5px] text-muted-foreground">Konsultant dostaje</dt>
          <dd className="text-[19px] font-semibold tabular-nums text-foreground">{num(p.rateCandidate)}</dd>
          <dd className="text-[11px] text-muted-foreground">{unit(p.candidateCurrency)}/h</dd>
        </div>
        <div>
          <dt className="text-[11.5px] text-muted-foreground">Marża</dt>
          <dd className="text-[19px] font-semibold tabular-nums text-success">{mixedCurrency ? "—" : num(p.margin)}</dd>
          <dd className="text-[11px] text-muted-foreground">
            {mixedCurrency ? "różne waluty" : `${marginUnit}/h${pct != null ? ` · ${pct.toLocaleString("pl-PL", { maximumFractionDigits: 1, minimumFractionDigits: 1 })} %` : ""}`}
          </dd>
        </div>
      </dl>
      <ul className="mt-3 space-y-1.5 border-t border-border/60 pt-3 text-[12.5px] leading-5 text-muted-foreground">
        {mixedCurrency ? (
          <li>
            Marży nie liczymy: klient płaci w {unit(p.clientCurrency)}, konsultant dostaje w {unit(p.candidateCurrency)}.
          </li>
        ) : monthly != null ? (
          <>
            <li>
              <span className="font-medium text-foreground">
                ≈ {formatWholeAmount(monthly)} {marginUnit}
              </span>{" "}
              marży miesięcznie ({p.hoursPerMonth ?? 168} h)
            </li>
            {nbp ? (
              <li>
                ≈ {formatWholeAmount(monthly * nbp.rate)} zł po kursie NBP {formatNbpRate(nbp.rate)} z{" "}
                {formatNbpDate(nbp.effective_date)}
              </li>
            ) : null}
          </>
        ) : null}
        <li>{change ? `Ostatnia zmiana stawek ${change}.` : "Stawki bez zmian od startu."}</li>
        {p.frameworkRate != null ? <li>Stawka z umowy ramowej: {num(p.frameworkRate)} zł/h.</li> : null}
        {benchLine ? <li>{benchLine}</li> : null}
      </ul>
    </section>
  );
}
