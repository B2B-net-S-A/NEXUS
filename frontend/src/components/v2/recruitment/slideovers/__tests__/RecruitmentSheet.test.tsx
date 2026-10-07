import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecruitmentSheet } from "../RecruitmentSheet";

describe("RecruitmentSheet — karta obok panelu", () => {
  it("sidePane żyje wewnątrz okna (fokus i kliknięcia działają)", () => {
    render(
      <RecruitmentSheet
        open
        onOpenChange={vi.fn()}
        title="Panel"
        description="Opis panelu"
        sidePane={<button type="button">Akcja w karcie</button>}
      >
        treść
      </RecruitmentSheet>,
    );
    const dialog = screen.getByRole("dialog", { name: "Panel" });
    expect(within(dialog).getByRole("button", { name: "Akcja w karcie" })).toBeInTheDocument();
  });

  it("bez sidePane nie ma pustej karty", () => {
    render(
      <RecruitmentSheet open onOpenChange={vi.fn()} title="Panel" description="Opis panelu">
        treść
      </RecruitmentSheet>,
    );
    expect(screen.queryByTestId("recruitment-sheet-side-pane")).not.toBeInTheDocument();
  });

  it("onEscapeKeyDown może zatrzymać zamknięcie panelu", () => {
    const onOpenChange = vi.fn();
    const onEscape = vi.fn((event: KeyboardEvent) => event.preventDefault());
    render(
      <RecruitmentSheet
        open
        onOpenChange={onOpenChange}
        title="Panel"
        description="Opis panelu"
        onEscapeKeyDown={onEscape}
      >
        treść
      </RecruitmentSheet>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onEscape).toHaveBeenCalledTimes(1);
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("Esc w polu słów kluczowych nie zamyka okna — szkic filtrów zostaje (U8)", () => {
    const onOpenChange = vi.fn();
    render(
      <RecruitmentSheet open onOpenChange={onOpenChange} title="Panel" description="Opis panelu">
        <input aria-label="Słowo" data-keyword-field="" />
      </RecruitmentSheet>,
    );
    const input = screen.getByLabelText("Słowo");
    input.focus();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onOpenChange).not.toHaveBeenCalled();
    // Poza polem słów Esc zamyka okno jak dotąd.
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
