import { afterEach, describe, expect, it } from "vitest";

import { shouldCloseOnEscape } from "@/lib/panel-escape";

function esc(): KeyboardEvent {
  return new KeyboardEvent("keydown", { key: "Escape" });
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("shouldCloseOnEscape", () => {
  it("zamyka panel, gdy nic nie jest otwarte", () => {
    expect(shouldCloseOnEscape(esc())).toBe(true);
  });

  it("nie zamyka panelu przy otwartym oknie Radix", () => {
    document.body.innerHTML = '<div role="dialog"></div>';
    expect(shouldCloseOnEscape(esc())).toBe(false);
  });

  // Przegląd PR #1932: „Dodaj przedłużenie” i „Nowy kontraktor / zamówienie”
  // to surowe okna bez obsługi Esc — Esc zamykał panel i gubił wpisane dane.
  it("nie zamyka panelu przy oknie oznaczonym tylko aria-modal", () => {
    document.body.innerHTML = '<div aria-modal="true"></div>';
    expect(shouldCloseOnEscape(esc())).toBe(false);
  });

  it("nie zamyka panelu, gdy fokus jest w polu tekstowym", () => {
    document.body.innerHTML = "<input />";
    (document.querySelector("input") as HTMLInputElement).focus();
    expect(shouldCloseOnEscape(esc())).toBe(false);
  });
});
