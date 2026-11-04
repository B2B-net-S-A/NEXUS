import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ThemePicker } from "../ThemePicker";

describe("ThemePicker (szablon graficzny rekrutacji)", () => {
  it("pokazuje 3 szablony i zaznacza domyślny, gdy rekruter nic nie wybrał", () => {
    render(<ThemePicker value={null} defaultTheme="jasny" onChange={() => {}} />);
    expect(screen.getAllByRole("button", { pressed: false })).toHaveLength(2);
    const picked = screen.getByTestId("theme-jasny");
    expect(picked).toHaveAttribute("aria-pressed", "true");
    expect(picked).toHaveTextContent("domyślny");
    expect(screen.queryByText(/Przywróć domyślny/)).toBeNull();
  });

  it("wybór innego szablonu zapisuje jego identyfikator", () => {
    const onChange = vi.fn();
    render(<ThemePicker value={null} defaultTheme="terminal" onChange={onChange} />);
    fireEvent.click(screen.getByTestId("theme-jasny"));
    expect(onChange).toHaveBeenCalledWith("jasny");
  });

  it("kliknięcie domyślnego zapisuje null — rekrutacja dalej idzie za rolą", () => {
    const onChange = vi.fn();
    render(<ThemePicker value="jasny" defaultTheme="grafit" onChange={onChange} />);
    fireEvent.click(screen.getByTestId("theme-grafit"));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("„Przywróć domyślny” pokazuje nazwę szablonu i zapisuje null", () => {
    const onChange = vi.fn();
    render(<ThemePicker value="terminal" defaultTheme="grafit" onChange={onChange} />);
    expect(screen.getByTestId("theme-terminal")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Przywróć domyślny (Grafit B2B)" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("zapisana dawna scena (sprzed 28.10.2026) wygląda jak brak wyboru", () => {
    // Strona pokazuje wtedy domyślny szablon roli (`career_theme.resolve_theme`).
    render(<ThemePicker value="radar" defaultTheme="jasny" onChange={() => {}} />);
    expect(screen.getByTestId("theme-jasny")).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText(/Przywróć domyślny/)).toBeNull();
  });

  it("w trakcie zapisu przyciski są zablokowane", () => {
    render(<ThemePicker value="terminal" defaultTheme="grafit" onChange={() => {}} busy />);
    expect(screen.getByTestId("theme-jasny")).toBeDisabled();
  });
});
