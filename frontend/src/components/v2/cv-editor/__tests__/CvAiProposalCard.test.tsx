import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { CvAiResponse } from "@/lib/api/cvEditorAi";

import { CvAiProposalCard, type CvAiProposalCardProps } from "../CvAiProposalCard";

const RESPONSE: CvAiResponse = {
  status: "ok",
  action: "rephrase",
  proposed_text: "Rozwój usług w **Java 17** <img src=x onerror=alert(1)>",
  verified: false,
  sources: [],
  cautions: [],
  reason: null,
  problem: null,
  message: null,
};

function card(overrides: Partial<CvAiProposalCardProps> = {}) {
  const props: CvAiProposalCardProps = {
    title: "Propozycja: przeredaguj",
    state: "proposal",
    before: "Rozwój usług w **Java 17** i innych",
    response: RESPONSE,
    message: null,
    canRetry: false,
    busy: false,
    onAccept: vi.fn(),
    onAgain: vi.fn(),
    onRefine: vi.fn(),
    onReject: vi.fn(),
    ...overrides,
  };
  render(<CvAiProposalCard {...props} />);
  return props;
}

describe("karta propozycji AI", () => {
  it("pokazuje „było / będzie” jako tekst z pogrubieniem — nigdy jako HTML", () => {
    card();
    const dialog = screen.getByRole("dialog", { name: "Propozycja AI" });
    expect(dialog).toHaveTextContent("Było");
    expect(dialog).toHaveTextContent("Będzie");
    expect(dialog.querySelectorAll("strong")).toHaveLength(2);
    // Znaczniki z odpowiedzi modelu są zwykłym tekstem.
    expect(dialog.querySelector("img")).toBeNull();
    expect(dialog).toHaveTextContent("<img src=x onerror=alert(1)>");
    expect(screen.queryByText("Zgodne ze źródłem")).toBeNull();
  });

  it("w trakcie liczenia jest tylko „Anuluj”", () => {
    const props = card({ state: "loading", response: null });
    expect(screen.getByRole("status")).toHaveTextContent("AI przygotowuje propozycję");
    expect(screen.queryByRole("button", { name: "Przyjmij" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(props.onReject).toHaveBeenCalled();
  });

  it("bez propozycji: powód, „Jeszcze raz” tylko gdy ma sens, i „Zamknij”", () => {
    card({ state: "message", response: null, message: "Klauzula zgody jest stała.", canRetry: false });
    expect(screen.getByRole("status")).toHaveTextContent("Klauzula zgody jest stała.");
    expect(screen.queryByRole("button", { name: "Jeszcze raz" })).toBeNull();
    expect(screen.getByRole("button", { name: "Zamknij" })).toBeInTheDocument();
  });

  it("„Doprecyzuj” nie wysyła pustej wskazówki", () => {
    const props = card();
    fireEvent.click(screen.getByRole("button", { name: "Doprecyzuj" }));
    expect(screen.getByRole("button", { name: "Wyślij" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Co zmienić w tej propozycji?"), { target: { value: "  bez żargonu " } });
    fireEvent.click(screen.getByRole("button", { name: "Wyślij" }));
    expect(props.onRefine).toHaveBeenCalledWith("  bez żargonu ");
  });

  it("trwające przyjmowanie blokuje pozostałe decyzje", () => {
    card({ busy: true });
    for (const name of ["Przyjmij", "Doprecyzuj", "Jeszcze raz", "Odrzuć"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });
});
