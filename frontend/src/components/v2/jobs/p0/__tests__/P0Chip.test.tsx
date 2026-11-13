/**
 * Plakietka P0: przed terminem pełny czerwony z odliczaniem, po terminie
 * „P0 · minęło …” z przerywaną ramką na karcie. Ramka idzie za kolorem napisu
 * (`border-current`), bo `border-destructive` w trybie ciemnym to ciemna
 * czerwień tła przycisku i ramka znikała na karcie (13.11.2026).
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { P0Chip } from "@/components/v2/jobs/p0/P0Chip";

const hoursFromNow = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();

describe("P0Chip", () => {
  it("po terminie: napis i przerywana ramka w kolorze czerwonego tekstu", () => {
    render(<P0Chip until={hoursFromNow(-6.5)} reason="Klient czeka na CV" />);
    const chip = screen.getByTestId("p0-chip");

    expect(chip).toHaveAttribute("data-overdue", "true");
    expect(chip).toHaveTextContent("P0 · minęło 6 h");
    expect(chip).toHaveClass("text-destructive", "border-dashed", "border-current", "bg-card");
    expect(chip).not.toHaveClass("border-destructive");
  });

  it("przed terminem: pełny czerwony z jasnym napisem i odliczaniem", () => {
    render(<P0Chip until={hoursFromNow(5.5)} />);
    const chip = screen.getByTestId("p0-chip");

    expect(chip).not.toHaveAttribute("data-overdue");
    expect(chip).toHaveTextContent(/^P0 · 5 h/);
    expect(chip).toHaveClass("bg-destructive", "text-destructive-foreground");
    expect(chip).not.toHaveClass("border-dashed");
  });

  it.each([null, undefined, "nie-data"])("bez poprawnego terminu nic nie pokazuje (%s)", (until) => {
    const { container } = render(<P0Chip until={until} />);
    expect(container).toBeEmptyDOMElement();
  });
});
