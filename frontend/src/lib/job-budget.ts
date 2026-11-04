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
  /** 0420: „od” z przedziału („60–80”) — tylko do wyświetlania. */
  effective_budget_hourly_min?: number | string | null;
  rate_budget_hourly_min?: number | string | null;
}

function positive(raw: number | string | null | undefined): number | null {
  const value = typeof raw === "string" ? Number(raw) : raw;
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

export function jobBudgetHourly(job: JobBudgetSource | null | undefined): number | null {
  for (const raw of [job?.effective_budget_hourly, job?.rate_budget_hourly]) {
    const value = positive(raw);
    if (value != null) return value;
  }
  return null;
}

/**
 * Dolna granica budżetu albo `null`. Budżetem — dla plakietki „ponad budżet”
 * i wszystkich reguł — zostaje górna granica (`jobBudgetHourly`); „od”
 * mniejsze niż budżet jest tylko informacją (backend: `job_budget_range`).
 */
export function jobBudgetMin(job: JobBudgetSource | null | undefined): number | null {
  const budget = jobBudgetHourly(job);
  if (budget == null) return null;
  const low = positive(job?.effective_budget_hourly_min) ?? positive(job?.rate_budget_hourly_min);
  return low != null && low < budget ? low : null;
}

/** „60,00–80,00 PLN/h” albo „do 80,00 PLN/h”; `null` bez budżetu. */
export function formatJobBudgetLabel(job: JobBudgetSource | null | undefined): string | null {
  const budget = jobBudgetHourly(job);
  if (budget == null) return null;
  const low = jobBudgetMin(job);
  return low != null
    ? `${formatBudgetHourly(low)}–${formatBudgetHourly(budget)} PLN/h`
    : `do ${formatBudgetHourly(budget)} PLN/h`;
}

/** `155` → `155,00` — ten sam zapis co w nagłówku rekrutacji. */
export function formatBudgetHourly(value: number): string {
  return value.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
