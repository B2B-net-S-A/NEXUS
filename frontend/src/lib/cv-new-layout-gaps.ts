/**
 * Braki stanowisk w „Nowym CV” liczone z dokumentu edytora (25.11.2026): stanowisko
 * bez okresu albo bez firmy nie trafia na oś kariery strony 1.
 */

/** „1 stanowisku”, „2 stanowiskach”, „5 stanowiskach” (miejscownik). */
export function plural(n: number): string {
  return `${n} ${n === 1 ? "stanowisku" : "stanowiskach"}`;
}

export interface RoleLike {
  period?: string | null;
  company?: string | null;
}

/** Ile stanowisk nie ma okresu z rokiem, a ile firmy; `null` = wszystko jest. */
export function roleGaps(
  roles: readonly RoleLike[],
  blind = false,
): { without_dates: number; without_company: number } | null {
  const withoutDates = roles.filter((role) => !/(?:19|20)\d{2}|obecnie|present|currently/i.test(role.period ?? "")).length;
  const withoutCompany = blind ? 0 : roles.filter((role) => !(role.company ?? "").trim()).length;
  return withoutDates || withoutCompany ? { without_dates: withoutDates, without_company: withoutCompany } : null;
}
