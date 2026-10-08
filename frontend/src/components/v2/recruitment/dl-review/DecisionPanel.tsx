"use client";

/**
 * Prawa kolumna przeglądu Delivery Leada — decyzja (D9, 08.10.2026).
 *
 * D9 odwraca decyzję z 23.09.2026 („przegląd bez marży”): DL widzi stawkę
 * kandydata, budżet rekrutacji od–do, stawkę do klienta podpowiedzianą
 * z historii (ta para, potem ta osoba u tego klienta — ze źródłem) i marżę
 * na żywo na godzinę i na miesiąc (168 h, `lib/dl-review-margin.ts`). Gdy
 * DL ma dostęp do kwot klienta, obok stoi mediana marży u klienta
 * i ostrzeżenie, gdy wpisana stawka daje mniej. Punkty odniesienia: wcześniejsze
 * wysyłki tej osoby, inni wysłani w tej rekrutacji, konsultanci u klienta
 * w tej samej kategorii (same agregaty), ostatni kontrakt.
 *
 * Waluta stawki do klienta to wybór (domyślnie PLN), nie stała w kodzie.
 * Przy walucie innej niż PLN marży nie liczymy — mówimy to zdaniem.
 */

import type { ReactNode } from "react";
import { AlertTriangle, Loader2, Send, Undo2, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { RateUnit } from "@/lib/api";
import type { BoardTaskRow } from "@/lib/api/boardTasks";
import type { DlReviewContext, DlReviewRate, DlReviewSend } from "@/lib/api/dlReview";
import { computeMargin, formatHourly, formatPln } from "@/lib/dl-review-margin";
import { RATE_UNIT_LABEL, rateText, type ClientRateUnit } from "@/lib/person-facts";
import { cn, formatDate } from "@/lib/utils";

export const CLIENT_RATE_CURRENCIES = ["PLN", "EUR", "USD", "GBP", "CHF"] as const;

export type DecisionAction = "send" | "reject" | "return";

export interface DecisionPanelProps {
  task: BoardTaskRow;
  context: DlReviewContext | undefined;
  contextLoading?: boolean;
  rateRaw: string;
  onRateRawChange: (value: string) => void;
  rateUnit: ClientRateUnit;
  onRateUnitChange: (unit: ClientRateUnit) => void;
  currency: string;
  onCurrencyChange: (currency: string) => void;
  /** Skąd jest wpisana stawka (podpowiedź z historii) — `null` = wpisał DL. */
  rateSourceLabel: string | null;
  canSend: boolean;
  sendReady: boolean;
  canReturn: boolean;
  canReject: boolean;
  busy: DecisionAction | null;
  onAccept: () => void;
  onReturn: () => void;
  onReject: () => void;
  /** Fakty o osobie (stawka w tej rekrutacji, „Stawka od”, dostępność…) — nad budżetem. */
  facts?: ReactNode;
  /** Ostrzeżenia, formularz odrzucenia, uwaga dla rekrutera — nad przyciskami. */
  children?: ReactNode;
  footerNote?: ReactNode;
}

function rateLabel(rate: DlReviewRate | null | undefined): string | null {
  if (!rate) return null;
  return rateText(rate.amount, rate.unit, rate.currency);
}

function Fact({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-2 text-xs">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium text-foreground">
        {value ?? "—"}
        {hint ? <span className="block text-[11px] font-normal text-muted-foreground">{hint}</span> : null}
      </dd>
    </div>
  );
}

function SendList({ title, rows, showName }: { title: string; rows: DlReviewSend[]; showName: boolean }) {
  if (rows.length === 0) return null;
  return (
    <div className="space-y-1">
      <p className="text-[11px] font-semibold text-foreground">{title}</p>
      <ul className="space-y-1">
        {rows.slice(0, 6).map((row) => (
          <li key={`${row.candidate_id}-${row.job_id}`} className="text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
            <span className="text-foreground">{showName ? row.candidate_name : row.job_title ?? "Rekrutacja"}</span>
            {!showName && row.client_name ? ` · ${row.client_name}` : ""}
            {row.sent_at ? ` · ${formatDate(row.sent_at)}` : ""}
            {row.candidate_rate ? ` · kandydat ${rateLabel(row.candidate_rate)}` : ""}
            {row.client_rate ? ` → klient ${rateLabel(row.client_rate)}` : ""}
            {row.outcome ? ` · ${row.outcome}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}

function budgetText(budget: DlReviewContext["budget"] | undefined): string | null {
  if (!budget) return null;
  const { min_hourly: min, max_hourly: max } = budget;
  if (max == null) return null;
  return min != null ? `${formatHourly(min).replace("/h", "")}–${formatHourly(max)}` : `do ${formatHourly(max)}`;
}

export function acceptLabel(rateRaw: string, unit: ClientRateUnit, currency: string): string {
  const text = rateText(rateRaw.replace(",", "."), unit, currency);
  return text ? `Akceptuj — wysyłam za ${text}` : "Akceptuj — wpisz stawkę do klienta";
}

export function DecisionPanel({
  task,
  context,
  contextLoading = false,
  rateRaw,
  onRateRawChange,
  rateUnit,
  onRateUnitChange,
  currency,
  onCurrencyChange,
  rateSourceLabel,
  canSend,
  sendReady,
  canReturn,
  canReject,
  busy,
  onAccept,
  onReturn,
  onReject,
  facts,
  children,
  footerNote,
}: DecisionPanelProps) {
  const candidateRate: DlReviewRate | null =
    context?.candidate_rate ??
    (task.expected_rate_value != null
      ? {
          amount: Number(task.expected_rate_value),
          unit: (task.expected_rate_unit ?? "hourly") as RateUnit,
          currency: task.expected_rate_currency ?? "PLN",
          hourly_pln: null,
        }
      : null);
  const clientRates = context?.client_rates ?? null;
  const margin = computeMargin({
    clientAmount: rateRaw,
    clientUnit: rateUnit,
    clientCurrency: currency,
    candidateAmount: candidateRate?.amount,
    candidateUnit: candidateRate?.unit,
    candidateCurrency: candidateRate?.currency,
    clientMedianHourly: clientRates?.client_margin_median_hourly ?? null,
  });
  const budget = budgetText(context?.budget);

  return (
    <section aria-label="Decyzja" className="flex min-w-0 flex-col gap-4" data-testid="dl-review-decision">
      {facts}
      <dl className="space-y-1.5" data-testid="dl-review-facts">
        {facts ? null : (
          <Fact
            label="Stawka kandydata"
            value={rateLabel(candidateRate)}
            hint={
              context?.rate_from_hourly != null
                ? `Stawka od: ${formatHourly(context.rate_from_hourly)} (najniższa z 18 mies.)`
                : null
            }
          />
        )}
        <Fact label="Budżet rekrutacji" value={budget} />
        <Fact label="Start" value={context?.start ?? null} />
      </dl>

      <div className="space-y-2 rounded-lg border border-border p-3">
        <label className="block text-xs font-medium">
          Stawka do klienta *
          <div className="mt-1 flex flex-wrap gap-1">
            <input
              inputMode="decimal"
              aria-label="Stawka do klienta"
              className="h-9 w-28 rounded-md border border-input bg-background px-2 text-sm tabular-nums"
              value={rateRaw}
              onChange={(e) => onRateRawChange(e.target.value)}
              disabled={!canSend}
            />
            <select
              aria-label="Jednostka stawki do klienta"
              className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              value={rateUnit}
              onChange={(e) => onRateUnitChange(e.target.value as ClientRateUnit)}
              disabled={!canSend}
            >
              {(Object.keys(RATE_UNIT_LABEL) as ClientRateUnit[]).map((u) => (
                <option key={u} value={u}>
                  {RATE_UNIT_LABEL[u].replace("zł", currency === "PLN" ? "zł" : currency)}
                </option>
              ))}
            </select>
            <select
              aria-label="Waluta stawki do klienta"
              className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              value={currency}
              onChange={(e) => onCurrencyChange(e.target.value)}
              disabled={!canSend}
            >
              {CLIENT_RATE_CURRENCIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
        </label>
        {rateSourceLabel ? (
          <p className="text-[11px] text-muted-foreground" data-testid="dl-review-rate-source">
            Podpowiedź: {rateSourceLabel}
          </p>
        ) : null}
        {contextLoading ? (
          <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
            <Loader2 className="size-3 animate-spin" aria-hidden /> Szukam stawek z historii…
          </p>
        ) : null}

        <div className="rounded-md bg-muted/40 px-2.5 py-2 text-xs" data-testid="dl-review-margin" aria-live="polite">
          {margin.kind === "ok" ? (
            <>
              <p className={cn("font-semibold", margin.negative ? "text-destructive" : "text-foreground")}>
                Marża: {formatHourly(margin.hourly)} · {formatPln(margin.monthly)}/mies. ({margin.percent.toLocaleString("pl-PL")}%)
              </p>
              <p className="text-[11px] text-muted-foreground">
                Klient {formatHourly(margin.clientHourly)} − kandydat {formatHourly(margin.candidateHourly)}, miesiąc
                = 168 h.
              </p>
              {margin.belowMedian && clientRates?.client_margin_median_hourly != null ? (
                <p className="mt-1 flex items-start gap-1 text-[11px] font-medium text-warning-muted-foreground">
                  <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden />
                  Poniżej mediany marży u tego klienta ({formatHourly(clientRates.client_margin_median_hourly)}).
                </p>
              ) : null}
            </>
          ) : margin.kind === "not_comparable" ? (
            <p className="text-muted-foreground">
              {margin.reason === "currency"
                ? "Marży nie liczymy — stawki są w różnych walutach."
                : "Marży nie liczymy — nie znamy stawki kandydata w tej rekrutacji."}
            </p>
          ) : (
            <p className="text-muted-foreground">Wpisz stawkę do klienta — marża policzy się od razu.</p>
          )}
        </div>
      </div>

      {context ? (
        <details className="rounded-lg border border-border" open>
          <summary className="cursor-pointer px-3 py-2 text-xs font-semibold">Punkty odniesienia</summary>
          <div className="space-y-3 border-t border-border p-3" data-testid="dl-review-reference">
            {clientRates ? (
              <div className="space-y-0.5 text-[11px] text-muted-foreground">
                <p className="font-semibold text-foreground">
                  Konsultanci u klienta{clientRates.category_name ? ` — ${clientRates.category_name}` : ""}
                </p>
                {clientRates.category_count > 0 && clientRates.category_cost_min == null &&
                clientRates.category_revenue_min == null ? (
                  <p>
                    {clientRates.category_count} os. z tej kategorii — przy mniej niż 3 osobach nie pokazujemy stawek
                    (zdradzałyby stawkę konkretnej osoby).
                  </p>
                ) : clientRates.category_count > 0 ? (
                  <>
                    <p>
                      {clientRates.category_count} os. · koszt {formatHourly(clientRates.category_cost_min)}–
                      {formatHourly(clientRates.category_cost_max)} · do klienta{" "}
                      {formatHourly(clientRates.category_revenue_min)}–{formatHourly(clientRates.category_revenue_max)}
                    </p>
                    <p>Mediana marży w kategorii: {formatHourly(clientRates.category_margin_median_hourly)}</p>
                  </>
                ) : (
                  <p>Nikt z tej kategorii nie pracuje dziś u klienta.</p>
                )}
                {clientRates.consultants >= 3 ? (
                  <p>
                    Mediana marży u klienta ({clientRates.consultants} os.):{" "}
                    {formatHourly(clientRates.client_margin_median_hourly)}
                  </p>
                ) : clientRates.consultants > 0 ? (
                  <p>
                    U klienta pracuje {clientRates.consultants} os. — za mało, żeby pokazać medianę marży.
                  </p>
                ) : (
                  <p>Nikt nie pracuje dziś u tego klienta.</p>
                )}
              </div>
            ) : context.can_see_amounts ? null : (
              <p className="text-[11px] text-muted-foreground">
                Stawek konsultantów u tego klienta nie widzisz — nie masz dostępu do kwot klienta.
              </p>
            )}
            <SendList title="Ta osoba wysyłana wcześniej" rows={context.previous_sends} showName={false} />
            <SendList title="Inni wysłani w tej rekrutacji" rows={context.job_sends} showName />
            {context.last_contract ? (
              <p className="text-[11px] text-muted-foreground">
                <span className="font-semibold text-foreground">Ostatni kontrakt: </span>
                {context.last_contract.client_name ?? "klient"}
                {context.last_contract.start_date ? ` od ${formatDate(context.last_contract.start_date)}` : ""}
                {context.last_contract.end_date ? ` do ${formatDate(context.last_contract.end_date)}` : ""}
                {context.last_contract.redacted
                  ? " · kwota ukryta"
                  : context.last_contract.cost_hourly != null
                    ? ` · koszt ${formatHourly(context.last_contract.cost_hourly)}`
                    : ""}
              </p>
            ) : null}
            {!clientRates &&
            context.previous_sends.length === 0 &&
            context.job_sends.length === 0 &&
            !context.last_contract ? (
              <p className="text-[11px] text-muted-foreground">Brak historii do porównania.</p>
            ) : null}
          </div>
        </details>
      ) : null}

      {children}

      <div className="flex flex-wrap justify-end gap-2">
        {canReturn ? (
          <Button variant="outline" disabled={busy !== null} onClick={onReturn}>
            {busy === "return" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Undo2 className="size-4" />}
            Wróć do poprawy…
          </Button>
        ) : null}
        {canReject ? (
          <Button variant="outline" onClick={onReject} disabled={busy !== null}>
            <XCircle className="size-4" />
            Odrzuć…
          </Button>
        ) : null}
        <Button disabled={!sendReady || busy !== null} onClick={onAccept}>
          {busy === "send" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Send className="size-4" />}
          {acceptLabel(rateRaw, rateUnit, currency)}
        </Button>
      </div>
      {footerNote}
    </section>
  );
}
