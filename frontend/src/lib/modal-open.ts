/**
 * Czy na ekranie jest otwarte okno modalne: Radix `Dialog`/`Sheet`
 * (`role="dialog"`, `data-state="open"`), potwierdzenie (`role="alertdialog"`)
 * albo własne okno z `aria-modal="true"`.
 *
 * Lista Radix `Popover` też ma `role="dialog"`, ale nie zasłania strony —
 * leży w `[data-radix-popper-content-wrapper]`, więc jej nie liczymy. Panel
 * osoby to zwykły `div`, nie okno: dymki leżą nad nim celowo.
 */
export function isModalOpen(): boolean {
  if (typeof document === "undefined") return false;
  for (const el of document.querySelectorAll<HTMLElement>('[role="dialog"], [role="alertdialog"]')) {
    if (el.getAttribute("aria-modal") === "true") return true;
    if (el.dataset.state === "closed") continue;
    if (el.getAttribute("role") === "alertdialog") return true;
    if (el.dataset.state === "open" && !el.closest("[data-radix-popper-content-wrapper]")) return true;
  }
  return false;
}
