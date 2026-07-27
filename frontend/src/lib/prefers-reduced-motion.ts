/**
 * Czy użytkownik prosi o ograniczenie ruchu (`prefers-reduced-motion: reduce`).
 *
 * Współdzielone, bo respektowanie tej preferencji musi być spójne w całej
 * aplikacji — konfetti i tło animowane odpowiadające różnie na to samo
 * ustawienie systemowe to błąd dostępności, nie kosmetyka.
 *
 * `matchMedia?.` (opcjonalne wywołanie) jest celowe: jsdom w testach ma `window`,
 * ale nie zawsze `matchMedia`.
 */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );
}
