/**
 * Kryterium akceptacji ticketu: bez powodu i bez daty operacji nie da się
 * zatwierdzić. Test pilnuje przycisku, bo to on jest bramką — `required` na
 * polach chroni tylko ścieżkę submitu formularza, a przycisk da się kliknąć.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { Mock } from "vitest";
import type { ComponentProps } from "react";
import { render, screen, fireEvent } from "@testing-library/react";

import { ContractsBulkEndDialog } from "../ContractsBulkEndDialog";

type DialogProps = ComponentProps<typeof ContractsBulkEndDialog>;

function renderDialog(overrides: Partial<DialogProps> = {}) {
  const onConfirm = vi.fn<DialogProps["onConfirm"]>() as Mock;
  render(
    <ContractsBulkEndDialog
      open
      count={3}
      onOpenChange={vi.fn()}
      onConfirm={onConfirm as unknown as DialogProps["onConfirm"]}
      {...overrides}
    />,
  );
  return { onConfirm };
}

const reasonSelect = () =>
  screen.getByRole("combobox") as HTMLSelectElement;
const endDateInput = () =>
  document.querySelector('input[type="date"]') as HTMLInputElement;
const confirmButton = () =>
  screen.getByRole("button", { name: "Zakończ" }) as HTMLButtonElement;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ContractsBulkEndDialog", () => {
  it("mówi, ilu kontraktów dotyczy dyspozycja", () => {
    renderDialog();
    expect(screen.getByText(/3 zaznaczonych kontraktach/)).toBeInTheDocument();
  });

  it("startuje z pustym powodem — żaden nie jest podstawiony domyślnie", () => {
    renderDialog();
    // Domyślny „Koniec projektu" oznaczyłby N umów powodem, którego nikt nie
    // wybrał; okno pojedynczego zakończenia może sobie na niego pozwolić.
    expect(reasonSelect().value).toBe("");
    expect(endDateInput().value).toBe("");
  });

  it("trzyma „Zakończ” nieaktywny, dopóki brakuje któregokolwiek pola", () => {
    renderDialog();
    expect(confirmButton()).toBeDisabled();

    fireEvent.change(reasonSelect(), { target: { value: "project_ended" } });
    expect(confirmButton()).toBeDisabled();

    fireEvent.change(endDateInput(), { target: { value: "2026-10-31" } });
    expect(confirmButton()).toBeEnabled();

    // Wyczyszczenie daty znowu blokuje — bramka patrzy na stan, nie na to,
    // czy pole kiedykolwiek było wypełnione.
    fireEvent.change(endDateInput(), { target: { value: "" } });
    expect(confirmButton()).toBeDisabled();
  });

  it("oddaje wybrany powód i datę", () => {
    const { onConfirm } = renderDialog();
    fireEvent.change(reasonSelect(), { target: { value: "client_budget_cut" } });
    fireEvent.change(endDateInput(), { target: { value: "2026-11-30" } });
    fireEvent.click(confirmButton());
    expect(onConfirm).toHaveBeenCalledWith("client_budget_cut", "2026-11-30");
  });

  it("oferuje powody z kanonicznej listy „Zakończ współpracę”", () => {
    renderDialog();
    expect(
      screen.getByRole("option", { name: "Koniec projektu" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Porozumienie stron" }),
    ).toBeInTheDocument();
  });

  it("pokazuje odmowę serwera zamiast chować ją w konsoli", () => {
    renderDialog({ error: "Illegal contract status transition" });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Illegal contract status transition",
    );
  });

  it("blokuje przycisk na czas zapisu", () => {
    renderDialog({ busy: true });
    expect(
      screen.getByRole("button", { name: "Zapisywanie…" }),
    ).toBeDisabled();
  });
});
