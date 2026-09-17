/**
 * URL, na który ląduje DL po zapisaniu nowej rekrutacji w `CreateJobModal`.
 *
 * Zawsze zakładka Championa — bramka handoffu i tak wymaga wypełnionego
 * profilu, więc pusty Pipeline (dawny domyślny landing) tylko kazał DL-owi
 * ręcznie przełączać zakładkę. `intake=1` domyślnie otwiera panel „Wklej
 * opis" (AI intake) w edytorze Championa TYLKO gdy rekrutacja ma opis do
 * podania AI — bez opisu panel byłby pusty do wypełnienia ręcznie i tylko
 * zasłaniałby formularz.
 */
export function createdJobUrl(
  jobId: number,
  opts: { hasDescription: boolean },
): string {
  const base = `/jobs/${jobId}?tab=champion`;
  return opts.hasDescription ? `${base}&intake=1` : base;
}
