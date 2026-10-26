import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppModal } from "@/components/ds/AppModal";

// Zgłoszenie 26.10.2026 (debrief): klik „Czy przyjmie ofertę?” na dole
// przewiniętego okna robił z okna białą planszę. Przyciski wyboru to `<label>`
// z ukrytym `<input class="sr-only">` (position: absolute). Bez `relative`
// na przewijanej treści pole liczyło pozycję od całego okna (`fixed`), nie
// przewijało się z treścią i leżało pod dolną krawędzią okna. Fokus na nim
// przewijał całe okno (`overflow-hidden` da się przewinąć skryptem) —
// nagłówek, treść i stopka wyjeżdżały poza widok, a kółkiem nie dało się
// wrócić. jsdom nie liczy układu, więc test pilnuje obu warunków poprawki.
describe("AppModal — ukryte pola wyboru w przewijanej treści", () => {
  function renderModal() {
    render(
      <AppModal open onOpenChange={() => {}} title="Debrief">
        <label>
          <input type="radio" name="offer" className="sr-only" />
          Raczej tak
        </label>
      </AppModal>,
    );
    return screen.getByRole("radio");
  }

  it("przewijana treść jest blokiem odniesienia dla pól sr-only", () => {
    const radio = renderModal();
    const scroller = radio.closest(".overflow-y-auto");
    expect(scroller).not.toBeNull();
    expect(scroller!.className.split(/\s+/)).toContain("relative");
  });

  it("samo okno nie daje się przewinąć fokusem (overflow-clip, nie overflow-hidden)", () => {
    renderModal();
    const classes = screen.getByRole("dialog").className.split(/\s+/);
    expect(classes).toContain("overflow-clip");
    expect(classes).not.toContain("overflow-hidden");
  });
});
