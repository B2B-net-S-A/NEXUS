/** The backend owns comparability; missing status never authorizes a comparison. */
export function matchingRateBand(status?: string | null): "in" | "over" | "unknown" {
  return status === "ok" ? "in" : status === "over_budget" ? "over" : "unknown";
}

export function formatMatchingRate(candidate: {
  expected_rate_hourly?: number | null;
  expected_rate_currency?: string | null;
  expected_rate_unit?: string | null;
}): string {
  const amount = candidate.expected_rate_hourly;
  if (amount == null || !Number.isFinite(amount)) return "brak danych";
  const currency = candidate.expected_rate_currency?.trim().toUpperCase() || "waluta nieznana";
  const unit = candidate.expected_rate_unit === "hour" ? "/h" : " · jednostka nieznana";
  return `${amount.toLocaleString("pl-PL", { maximumFractionDigits: 2 })} ${currency}${unit}`;
}
