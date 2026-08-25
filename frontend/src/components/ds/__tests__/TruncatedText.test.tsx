import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { TruncatedText } from "@/components/ds/TruncatedText";

const LONG =
  "CARDIF - ASSURANCES RISQUES DIVERS SPÓŁKA AKCYJNA ODDZIAŁ W POLSCE";

describe("TruncatedText", () => {
  it("pokazuje pełną treść w tooltipie, żeby ucięcie nie gubiło informacji", () => {
    render(<TruncatedText>{LONG}</TruncatedText>);
    const el = screen.getByText(LONG);
    expect(el).toHaveAttribute("title", LONG);
  });

  it("jest blokowy i przycięty — inaczej `truncate` nic nie robi", () => {
    render(<TruncatedText>{LONG}</TruncatedText>);
    const el = screen.getByText(LONG);
    // `truncate` (overflow-hidden + ellipsis) NIE działa na elemencie inline,
    // a `max-w` jest tym, co powstrzymuje kolumnę przed rozjazdem.
    expect(el.className).toContain("block");
    expect(el.className).toContain("truncate");
    expect(el.className).toContain("max-w-");
  });

  it("pusta wartość renderuje „—” BEZ tooltipa", () => {
    render(<TruncatedText>{null}</TruncatedText>);
    const el = screen.getByText("—");
    // `title="—"` to dymek, który nic nie mówi.
    expect(el).not.toHaveAttribute("title");
  });

  it("sam biały znak liczy się jako brak wartości", () => {
    render(<TruncatedText>{"   "}</TruncatedText>);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("własna klasa zawęża/rozszerza domyślny limit, a nie dubluje go", () => {
    render(<TruncatedText className="max-w-[420px]">{LONG}</TruncatedText>);
    const el = screen.getByText(LONG);
    expect(el.className).toContain("max-w-[420px]");
    expect(el.className).not.toContain("max-w-[220px]");
  });

  it("zastępnik da się zmienić, gdy „—” nie pasuje do kolumny", () => {
    render(<TruncatedText fallback="brak">{null}</TruncatedText>);
    expect(screen.getByText("brak")).toBeInTheDocument();
  });
});
