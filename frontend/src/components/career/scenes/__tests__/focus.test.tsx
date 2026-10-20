/**
 * Fokus nie może spaść na <body> po aktywacji przycisku sceny — inaczej
 * kolejny Tab zaczyna od początku strony (WCAG 2.4.3). Przyciski, które
 * zmieniają stan, zostają w DOM albo oddają fokus następnemu krokowi.
 */
import { fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderScene } from "./sceneTestUtils";

function activate(button: HTMLElement) {
  button.focus();
  fireEvent.click(button);
}

describe("fokus w scenach", () => {
  it("Glitch: znaleziony błąd zostaje przyciskiem z fokusem", () => {
    const s = renderScene("glitch");
    const bug = s.full().getByRole("button", { name: /^Błąd 2 z 3/ });
    activate(bug);
    expect(document.activeElement).toBe(bug);
    expect(bug).toHaveAttribute("aria-pressed", "true");
    expect(bug).toHaveAccessibleName(/znaleziony/);
    expect(bug).toHaveTextContent("kandydat.spec.ts");
  });

  it("Konstelacja: „zacznij od nowa” nie znika spod fokusu", () => {
    const s = renderScene("konstelacja");
    fireEvent.click(s.full().getByRole("button", { name: /^Kafka/ }));
    const clear = s.full().getByRole("button", { name: "zacznij od nowa" });
    activate(clear);
    expect(document.activeElement).toBe(clear);
    expect(clear).toHaveAttribute("aria-disabled", "true");
    expect(s.score().getByText("0/5")).toBeInTheDocument();
  });

  it("C4: „przełącz na C2” oddaje fokus przyciskowi widoku C2", () => {
    const s = renderScene("c4");
    fireEvent.click(s.full().getByRole("button", { name: "C1 · kontekst" }));
    activate(s.full().getByRole("button", { name: /przełącz na C2/ }));
    expect(document.activeElement).toBe(s.full().getByRole("button", { name: "C2 · kontenery" }));
  });

  it("Papier: zakreślony błąd zostaje przyciskiem z fokusem", () => {
    const s = renderScene("papier");
    const bug = s.full().getByRole("button", { name: /^Błąd 4 z 4/ });
    activate(bug);
    expect(document.activeElement).toBe(bug);
    expect(bug).toHaveAttribute("aria-pressed", "true");
    expect(bug).toHaveTextContent("Nieprawidłowy login lub hasło");
  });
});
