import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RequestPriorityChip } from "@/components/v2/jobs/RequestPriorityChip";

describe("RequestPriorityChip", () => {
  it("P1: krótka etykieta w tonie alarmu, pełna nazwa w podpowiedzi i dla czytnika", () => {
    render(<RequestPriorityChip level="p1" />);
    const chip = screen.getByTitle("P1 Pilne");
    expect(chip).toHaveAttribute("data-priority", "p1");
    expect(chip.className).toContain("bg-destructive-muted");
    expect(chip.className).toContain("text-destructive-muted-foreground");
    // Widoczny skrót jest ukryty przed czytnikiem — ten dostaje pełną nazwę.
    expect(screen.getByText("P1")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("P1 Pilne")).toHaveClass("sr-only");
  });

  it("„Przyjmujemy kandydatów”: przygaszona plakietka z obwódką", () => {
    render(<RequestPriorityChip level="accepting" />);
    const chip = screen.getByTitle("Przyjmujemy kandydatów");
    expect(chip).toHaveAttribute("data-priority", "accepting");
    expect(chip.className).toContain("border-border");
    expect(chip.className).toContain("text-muted-foreground");
    expect(chip.className).not.toContain("bg-destructive-muted");
    expect(screen.getByText("Przyjmujemy")).toBeInTheDocument();
  });

  it("P2 to stan domyślny — bez plakietki, także w wersji pełnej", () => {
    const { container, rerender } = render(<RequestPriorityChip level="p2" />);
    expect(container).toBeEmptyDOMElement();
    rerender(<RequestPriorityChip level="p2" full />);
    expect(container).toBeEmptyDOMElement();
  });

  it("brak poziomu niczego nie renderuje", () => {
    const { container, rerender } = render(<RequestPriorityChip level={null} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<RequestPriorityChip level={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("`full` pokazuje pełną etykietę wprost", () => {
    const { rerender } = render(<RequestPriorityChip level="p1" full />);
    expect(screen.getByText("P1 Pilne")).not.toHaveClass("sr-only");
    expect(screen.queryByText("P1")).not.toBeInTheDocument();

    rerender(<RequestPriorityChip level="accepting" full />);
    expect(screen.getByText("Przyjmujemy kandydatów")).not.toHaveClass("sr-only");
  });

  it("przyjmuje rozmiar i dodatkowe klasy", () => {
    render(<RequestPriorityChip level="p1" size="md" className="ml-2" />);
    const chip = screen.getByTitle("P1 Pilne");
    expect(chip.className).toContain("h-5");
    expect(chip.className).toContain("ml-2");
    // Pełna nazwa dla czytnika jest pozycjonowana absolutnie — plakietka ją obejmuje.
    expect(chip.className).toContain("relative");
  });
});
