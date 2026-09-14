// Doładowywanie starszych powiadomień w dzwonku (B51).
//
// Dzwonek pobierał sztywno 20 pozycji i kończył listę przyciskiem „Zamknij" —
// przy liczniku ponad tysiąca nieprzeczytanych starsze były niedostępne.
// Zamiast stronicowania po `offset` rośnie `limit` (20 → 50 → 200): lista jest
// sortowana „nieprzeczytane najpierw", a kliknięcie pozycji oznacza ją jako
// przeczytaną i przetasowuje kolejność — doklejanie kolejnych stron dawałoby
// duplikaty i luki. Jedno zapytanie z większym limitem jest zawsze spójne.
export const NOTIFICATIONS_PAGE_SIZES: readonly number[] = [20, 50, 200] as const;

export const NOTIFICATIONS_INITIAL_LIMIT = NOTIFICATIONS_PAGE_SIZES[0];

/** Następny próg albo `null`, gdy osiągnięto sufit backendu (200). */
export function nextNotificationsLimit(limit: number): number | null {
  const next = NOTIFICATIONS_PAGE_SIZES.find((size) => size > limit);
  return next ?? null;
}

/**
 * „Pokaż więcej" ma sens tylko wtedy, gdy lista jest pełna (backend mógł mieć
 * więcej) i jest jeszcze wyższy próg. Lista krótsza niż limit = to już wszystko.
 */
export function canShowMoreNotifications(loaded: number, limit: number): boolean {
  return loaded >= limit && nextNotificationsLimit(limit) !== null;
}
