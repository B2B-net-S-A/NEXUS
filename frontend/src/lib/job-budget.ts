/**
 * Budżet PLN/h rekrutacji — ta sama kwota, której używa wyszukiwanie.
 *
 * `effective_budget_hourly` liczy backend funkcją filtra (jawne pole oferty,
 * a gdy puste — stawka z Profilu Championa). Nagłówek, pasek AI Matching
 * i dok oferty czytały wcześniej trzy różne pola, więc ta sama rekrutacja
 * miała „budżet do 155 PLN/h” w nagłówku i „brak danych” w doku (UAT B62/B72).
 * `rate_budget_hourly` zostaje zapasem dla odpowiedzi sprzed tego pola.
 */
export interface JobBudgetSource {
  effective_budget_hourly?: number | string | null;
  rate_budget_hourly?: number | string | null;
}

export function jobBudgetHourly(job: JobBudgetSource | null | undefined): number | null {
  for (const raw of [job?.effective_budget_hourly, job?.rate_budget_hourly]) {
    const value = typeof raw === "string" ? Number(raw) : raw;
    if (typeof value === "number" && Number.isFinite(value) && value > 0) return value;
  }
  return null;
}

/** `155` → `155,00` — ten sam zapis co w nagłówku rekrutacji. */
export function formatBudgetHourly(value: number): string {
  return value.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
