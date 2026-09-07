/**
 * "Brak ownera requestu" jako FILTR, nie tylko badge (makieta „01 Lista").
 *
 * `GET /api/jobs` nie ma parametru `tac_id`/`has_owner` — dodanie go jest
 * follow-upem backendowym (patrz raport PR). Do tego czasu filtr zawęża
 * WYŁĄCZNIE bieżącą, już wczytaną stronę wyników — stąd `count` w UI musi
 * być jawnie podpisany „na tej stronie" (inaczej sugerowałby globalną liczbę,
 * której to zapytanie nie zna: strona ma co najwyżej `page_size` wierszy,
 * reszta stron może mieć zupełnie inny udział braków ownera).
 */
export function jobsMissingRequestOwner<T extends { tac_id?: number | null }>(
  jobs: readonly T[],
): T[] {
  return jobs.filter((j) => j.tac_id == null);
}
