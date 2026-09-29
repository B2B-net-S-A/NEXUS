/**
 * Escape zamyka boczny panel — chyba że klawisz należy do otwartego okna,
 * menu albo pola tekstowego (w polu Esc anuluje edycję, nie zamyka panelu).
 */
export function shouldCloseOnEscape(e: KeyboardEvent): boolean {
  if (e.key !== "Escape" || e.defaultPrevented) return false;
  if (typeof document === "undefined") return true;
  if (document.querySelector('[role="dialog"],[role="alertdialog"],[role="menu"]')) return false;
  const el = document.activeElement as HTMLElement | null;
  if (!el) return true;
  const tag = el.tagName.toLowerCase();
  return !(tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable);
}
