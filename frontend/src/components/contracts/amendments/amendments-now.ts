// Karta „Obowiązuje teraz” zakładki „Aneksy” (wariant A, 19.11.2026): stan
// bieżący liczony z kontraktu — stawka klienta i kandydata z dniem, od którego
// obowiązuje, koniec zamówienia i umowy, a gdy stawka klienta przyszła
// z zamówienia, a nie z aneksu — zdanie o tym. Czysta funkcja.
import { formatMoney } from "@/lib/money";

export interface AmendmentsRateStep {
  rate: number;
  effective_from: string | null;
  /** Krok z zamówienia klienta; `null` — ręczny albo z aneksu. */
  source_order_id?: number | null;
  superseded?: boolean;
}

/** Pola kontraktu, z których liczy się karta — podzbiór `GET /api/contracts/{id}`. */
export interface AmendmentsContract {
  contract_type?: string | null;
  end_date?: string | null;
  client_order_end_date?: string | null;
  latest_order_end_date?: string | null;
  rate_client?: number | null;
  rate_candidate?: number | null;
  currency?: string | null;
  rate_client_currency?: string | null;
  rate_candidate_currency?: string | null;
  rate_unit?: string | null;
  client_rate_schedule?: readonly AmendmentsRateStep[] | null;
  candidate_rate_schedule?: readonly AmendmentsRateStep[] | null;
}

export interface NowRate {
  who: "klient" | "kandydat";
  /** „163,00 zł/h”; `null` — kontrakt nie ma tej stawki. */
  amount: string | null;
  /** Od kiedy ta kwota obowiązuje — tylko gdy dni obu stawek się różnią. */
  since: string | null;
}

export interface AmendmentsNow {
  /** Wspólny dzień, od którego obowiązują obie stawki. */
  since: string | null;
  /** Puste bez wglądu w kwoty (serwer i tak je zeruje). */
  rates: NowRate[];
  order: { end: string; ended: boolean } | null;
  /** Drobny druk: okres umowy, skąd jest stawka klienta. */
  facts: string[];
}

const SAME = 0.0005;

/**
 * Od kiedy obowiązuje bieżąca kwota: ostatni krok harmonogramu z datą ≤ dziś,
 * cofnięty do początku ciągu kroków z tą samą kwotą. Kwota spoza harmonogramu
 * (krok nie zgadza się ze stawką kontraktu) — dzień nieznany.
 */
export function rateRun(
  steps: readonly AmendmentsRateStep[] | null | undefined,
  rate: number | null | undefined,
  today: string,
): { since: string | null; fromOrder: boolean } {
  if (rate == null) return { since: null, fromOrder: false };
  // Sortowanie jest stabilne: z kroków z jednego dnia wygrywa ostatni z odpowiedzi.
  const live = (steps ?? [])
    .filter((s) => !s.superseded && s.effective_from != null && s.effective_from <= today)
    .sort((a, b) => (a.effective_from ?? "").localeCompare(b.effective_from ?? ""));
  const last = live[live.length - 1];
  if (!last || Math.abs(last.rate - rate) > SAME) return { since: null, fromOrder: false };
  let first = live.length - 1;
  while (first > 0 && Math.abs(live[first - 1].rate - rate) <= SAME) first -= 1;
  return { since: live[first].effective_from, fromOrder: last.source_order_id != null };
}

function contractEndFact(c: AmendmentsContract): string {
  if (c.end_date) {
    const [y, m, d] = c.end_date.slice(0, 10).split("-");
    return `umowa do ${d}.${m}.${y}`;
  }
  return (c.contract_type ?? "b2b") === "b2b" ? "umowa B2B bezterminowa" : "umowa bez daty końca";
}

export function amendmentsNow(
  c: AmendmentsContract,
  { today, canSeeRates }: { today: string; canSeeRates: boolean },
): AmendmentsNow {
  const client = rateRun(c.client_rate_schedule, c.rate_client, today);
  const candidate = rateRun(c.candidate_rate_schedule, c.rate_candidate, today);
  const shared = canSeeRates && client.since != null && client.since === candidate.since ? client.since : null;
  const amount = (value: number | null | undefined, currency: string | null | undefined) =>
    value == null ? null : formatMoney(value, currency ?? c.currency, c.rate_unit);
  const rates: NowRate[] = canSeeRates
    ? [
        { who: "klient", amount: amount(c.rate_client, c.rate_client_currency), since: shared ? null : client.since },
        { who: "kandydat", amount: amount(c.rate_candidate, c.rate_candidate_currency), since: shared ? null : candidate.since },
      ]
    : [];
  const orderEnd = c.latest_order_end_date ?? c.client_order_end_date ?? null;
  return {
    since: shared,
    rates,
    order: orderEnd ? { end: orderEnd, ended: orderEnd < today } : null,
    facts: [
      contractEndFact(c),
      canSeeRates && client.fromOrder ? "stawka klienta z zamówienia, nie z aneksu" : "",
    ].filter(Boolean),
  };
}
