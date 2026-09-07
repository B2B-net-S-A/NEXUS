/**
 * Pilność deadline'u rekrutacji dla wiersza listy (makieta „01 Lista”):
 * `dl soon` (≤ 7 dni, warning), `dl over` (po terminie, destructive), zwykły
 * (neutral), brak terminu (muted). Osobny moduł — patrz `jobs-url-filters.ts`
 * dla uzasadnienia wzorca (test wiąże się z tą samą funkcją co komponent).
 */

export type DeadlineUrgency = "none" | "overdue" | "soon" | "normal";

export interface JobDeadlineInfo {
  urgency: DeadlineUrgency;
  /** Dni do terminu; ujemne po terminie. `null` gdy brak deadline'u. */
  daysLeft: number | null;
}

// `YYYY-MM-DD` z regexa, NIE `new Date(deadline)` wprost — `job.deadline` jest
// datą BEZ czasu (Pydantic `date`), a `new Date("2026-09-07")` w silniku JS
// parsuje się jako UTC północ. Odczytanie z niej `getFullYear/Month/Date`
// (metody LOKALNE) na maszynie w strefie za UTC cofa datę o dzień — dokładnie
// pułapka off-by-one, przed którą broni się już `isoLocal()` w `JobsListV2`
// (tam w drugą stronę: Date → lokalny ISO string).
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})/;

/**
 * `now` jest parametrem (nie `new Date()` w środku) — deterministyczny test
 * bez mockowania globalnego zegara.
 */
export function classifyJobDeadline(
  deadline: string | null | undefined,
  now: Date = new Date(),
): JobDeadlineInfo {
  if (!deadline) return { urgency: "none", daysLeft: null };
  const match = DATE_ONLY.exec(deadline);
  if (!match) return { urgency: "none", daysLeft: null };
  const [, year, month, day] = match;
  const targetLocal = new Date(Number(year), Number(month) - 1, Number(day));
  if (Number.isNaN(targetLocal.getTime())) {
    return { urgency: "none", daysLeft: null };
  }
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const daysLeft = Math.round(
    (targetLocal.getTime() - today.getTime()) / 86_400_000,
  );
  if (daysLeft < 0) return { urgency: "overdue", daysLeft };
  if (daysLeft <= 7) return { urgency: "soon", daysLeft };
  return { urgency: "normal", daysLeft };
}

/**
 * Format `YYYY-MM-DD` → `DD.MM.YYYY` (pl-PL) BEZ przejścia przez UTC.
 * `formatDate` z `lib/utils` robi `new Date("2026-09-07")` = północ UTC, więc
 * na maszynie w strefie za UTC pokazuje dzień wcześniej — ten sam off-by-one,
 * przed którym broni się `classifyJobDeadline`. Wartość nie-datowa (albo
 * z czasem) idzie do `Intl` po zwykłym `Date`, jak dotąd.
 */
export function formatDateOnly(value: string | null | undefined): string {
  if (!value) return "—";
  const match = DATE_ONLY.exec(value);
  const date = match
    ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    : new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("pl-PL").format(date);
}
