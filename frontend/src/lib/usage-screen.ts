// Same litery i myślniki, więc identyfikator (liczba, UUID) nie przejdzie.
// `b2b-` to jedyny człon adresu z cyfrą, który ma znaczenie dla obszaru.
const SEGMENT = /^(?:b2b-)?[a-z][a-z-]*$/;

/**
 * Ekran dla licznika użycia obszarów: pierwsze dwa człony adresu, bez
 * identyfikatorów. `/candidates/123` to `candidates`, a
 * `/contracts/b2b-generator` to cały adres, bo tam zaczyna się inny obszar.
 */
export function usageScreen(pathname: string): string | null {
  const [first, second] = pathname.split("/").filter(Boolean);
  if (!first || !SEGMENT.test(first)) return null;
  return second && SEGMENT.test(second) ? `${first}/${second}` : first;
}
