import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ThemePicker } from "../ThemePicker";

describe("ThemePicker (szablon graficzny rekrutacji, 0478)", () => {
  it("pokazuje 12 szablonów i zaznacza domyślny, gdy rekruter nic nie wybrał", () => {
    render(<ThemePicker value={null} defaultTheme="sekwencja" onChange={() => {}} />);
    expect(screen.getAllByRole("button", { pressed: false })).toHaveLength(11);
    const picked = screen.getByTestId("theme-sekwencja");
    expect(picked).toHaveAttribute("aria-pressed", "true");
    expect(picked).toHaveTextContent("domyślny");
    expect(screen.queryByText(/Przywróć domyślny/)).toBeNull();
  });

  it("wybór innego szablonu zapisuje jego identyfikator", () => {
    const onChange = vi.fn();
    render(<ThemePicker value={null} defaultTheme="terminal" onChange={onChange} />);
    fireEvent.click(screen.getByTestId("theme-radar"));
    expect(onChange).toHaveBeenCalledWith("radar");
  });

  it("kliknięcie domyślnego zapisuje null — rekrutacja dalej idzie za rolą", () => {
    const onChange = vi.fn();
    render(<ThemePicker value="radar" defaultTheme="glitch" onChange={onChange} />);
    fireEvent.click(screen.getByTestId("theme-glitch"));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("„Przywróć domyślny” pokazuje nazwę szablonu i zapisuje null", () => {
    const onChange = vi.fn();
    render(<ThemePicker value="radar" defaultTheme="c4" onChange={onChange} />);
    expect(screen.getByTestId("theme-radar")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Przywróć domyślny (Architektura C4)" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("w trakcie zapisu przyciski są zablokowane", () => {
    render(<ThemePicker value="radar" defaultTheme="c4" onChange={() => {}} busy />);
    expect(screen.getByTestId("theme-plan")).toBeDisabled();
  });
});
