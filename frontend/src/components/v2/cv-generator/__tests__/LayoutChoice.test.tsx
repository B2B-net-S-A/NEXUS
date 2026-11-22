import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LayoutChoice, cvLayoutFact } from "../LayoutChoice";

describe("LayoutChoice — układ CV (22.11.2026)", () => {
  it("generator: domyślny układ klienta w podpowiedzi i zmiana wyboru", async () => {
    const onChange = vi.fn();
    render(
      <LayoutChoice place="generator" value="new" onChange={onChange} clientName="Bank Przykładowy" clientDefault="new" />,
    );
    expect(screen.getByRole("button", { name: "Nowe CV" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Bank Przykładowy: domyślnie Nowe CV/)).toBeInTheDocument();
    expect(screen.getByText(/zmienisz też po wygenerowaniu/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Klasyczne (Word)" }));
    expect(onChange).toHaveBeenCalledWith("classic");
  });

  it("karta: mówi, że ten sam tekst idzie w obu układach", () => {
    render(<LayoutChoice place="card" value="classic" onChange={vi.fn()} />);
    expect(screen.getByText(/Ten sam tekst w obu układach/)).toBeInTheDocument();
  });

  it("po wysyłce: przełącznik zablokowany z wyjaśnieniem", () => {
    render(<LayoutChoice place="card" value="new" onChange={vi.fn()} lockedAfterSend />);
    expect(screen.getByRole("button", { name: "Nowe CV" })).toBeDisabled();
    expect(screen.getByText(/po wysyłce do klienta/)).toBeInTheDocument();
  });

  it("fakty karty", () => {
    expect(cvLayoutFact("new")).toBe("Nowe CV · PDF");
    expect(cvLayoutFact("classic")).toBe("Klasyczne · Word");
  });
});
