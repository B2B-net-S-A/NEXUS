"use client";

import Decimal from "decimal.js";

import type { OrderRateUnit } from "@/lib/api/dlPortal";

const RATE_UNITS: ReadonlyArray<{
  value: OrderRateUnit;
  label: string;
}> = [
  { value: "hourly", label: "Godzinowa" },
  { value: "daily", label: "MD" },
  { value: "monthly", label: "Miesięczna" },
];

const ORDER_CURRENCIES = ["PLN", "EUR", "USD", "GBP"] as const;

export function convertRateInput(
  value: string,
  from: OrderRateUnit,
  to: OrderRateUnit,
  billingHoursPerMonth = 160,
): string {
  if (!value.trim()) return value;
  let amount: Decimal;
  try {
    amount = new Decimal(value.trim().replace(/\s/g, "").replace(",", "."));
  } catch {
    return value;
  }
  if (!amount.isFinite()) return value;

  let converted: Decimal;
  if (
    (from === "hourly" && to === "daily") ||
    (from === "daily" && to === "hourly")
  ) {
    converted = from === "hourly" ? amount.times(8) : amount.dividedBy(8);
  } else if (
    (from === "daily" && to === "monthly") ||
    (from === "monthly" && to === "daily")
  ) {
    converted = from === "daily" ? amount.times(22) : amount.dividedBy(22);
  } else {
    const hours = new Decimal(billingHoursPerMonth || 160);
    converted =
      from === "hourly" ? amount.times(hours) : amount.dividedBy(hours);
  }

  // ClientOrder stores three decimal places (e.g. Alior 164.375 PLN/h).
  // Keep that precision here; the group-only PLN/MD converter intentionally
  // remains at two decimals in lib/rate-unit.ts.
  return converted
    .toDecimalPlaces(3, Decimal.ROUND_HALF_UP)
    .toFixed(3)
    .replace(/\.?0+$/, "");
}

export function extractionRateUnit(
  value: string | null | undefined,
): OrderRateUnit | null {
  switch (value?.trim().toLowerCase()) {
    case "hour":
    case "hourly":
    case "h":
      return "hourly";
    case "day":
    case "daily":
    case "md":
      return "daily";
    case "month":
    case "monthly":
    case "mc":
      return "monthly";
    default:
      return null;
  }
}

export function rateUnitNoticeLabel(unit: OrderRateUnit): string {
  if (unit === "daily") return "MD";
  if (unit === "hourly") return "godzinową";
  return "miesięczną";
}

export function normalizeOrderCurrency(
  ...values: Array<string | null | undefined>
): string {
  const inherited = values.find((value) => value?.trim());
  return inherited?.trim().toUpperCase() || "PLN";
}

interface OrderRateUnitToggleProps {
  value: OrderRateUnit;
  rateCandidate: string;
  rateClient: string;
  onValueChange: (value: OrderRateUnit) => void;
  onRateCandidateChange: (value: string) => void;
  onRateClientChange: (value: string) => void;
  billingHoursPerMonth?: number;
  disabled?: boolean;
}

/**
 * Jeden przełącznik opisuje obie stawki zamówienia. Zmiana jednostki przelicza
 * koszt i przychód w tym samym zdarzeniu; puste lub niepoprawne pole zostaje
 * nietknięte. Bezpośrednia zmiana godzina↔MD zawsze używa 1 MD = 8 h.
 */
export function OrderRateUnitToggle({
  value,
  rateCandidate,
  rateClient,
  onValueChange,
  onRateCandidateChange,
  onRateClientChange,
  billingHoursPerMonth = 160,
  disabled = false,
}: OrderRateUnitToggleProps) {
  function select(next: OrderRateUnit) {
    if (next === value || disabled) return;
    onRateCandidateChange(
      convertRateInput(rateCandidate, value, next, billingHoursPerMonth),
    );
    onRateClientChange(
      convertRateInput(rateClient, value, next, billingHoursPerMonth),
    );
    onValueChange(next);
  }

  return (
    <div>
      <span className="text-sm font-medium">Jednostka stawki</span>
      <div
        role="radiogroup"
        aria-label="Jednostka stawki"
        className="mt-1 inline-flex rounded-md border border-border bg-muted/30 p-0.5"
      >
        {RATE_UNITS.map((unit) => (
          <button
            key={unit.value}
            type="button"
            role="radio"
            aria-checked={value === unit.value}
            disabled={disabled}
            onClick={() => select(unit.value)}
            className={`rounded px-3 py-1.5 text-sm transition-colors disabled:opacity-50 ${
              value === unit.value
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-background hover:text-foreground"
            }`}
          >
            {unit.label}
          </button>
        ))}
      </div>
    </div>
  );
}

interface OrderCurrencySelectProps {
  value: string;
  onChange: (value: string) => void;
  label?: string;
  ariaLabel?: string;
  disabled?: boolean;
}

export function OrderCurrencySelect({
  value,
  onChange,
  label = "Waluta zamówienia (przychodowa)",
  ariaLabel = label,
  disabled = false,
}: OrderCurrencySelectProps) {
  const normalized = normalizeOrderCurrency(value);
  const inheritedFallback = ORDER_CURRENCIES.includes(
    normalized as (typeof ORDER_CURRENCIES)[number],
  )
    ? null
    : normalized;

  return (
    <label className="block">
      <span className="text-sm font-medium">{label}</span>
      <select
        aria-label={ariaLabel}
        value={normalized}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm disabled:opacity-50"
      >
        {inheritedFallback ? (
          <option value={inheritedFallback}>
            {inheritedFallback} (odziedziczona)
          </option>
        ) : null}
        {ORDER_CURRENCIES.map((currency) => (
          <option key={currency} value={currency}>
            {currency}
          </option>
        ))}
      </select>
    </label>
  );
}
