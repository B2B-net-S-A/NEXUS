import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ContractCandidateContactRow } from "@/components/contracts/ContractCandidateContactRow";

function setup(overrides: Partial<React.ComponentProps<typeof ContractCandidateContactRow>> = {}) {
  const onSaveEmail = vi.fn().mockResolvedValue(undefined);
  const onSavePhone = vi.fn().mockResolvedValue(undefined);
  const onError = vi.fn();
  render(
    <ContractCandidateContactRow
      email="jan@example.com"
      emailSource="contract"
      phone="+48 600 100 200"
      phoneSource="contract"
      editable
      onSaveEmail={onSaveEmail}
      onSavePhone={onSavePhone}
      onError={onError}
      {...overrides}
    />,
  );
  return { onSaveEmail, onSavePhone, onError };
}

describe("ContractCandidateContactRow", () => {
  it("renderuje e-mail i telefon jako jeden wiersz", () => {
    setup();
    expect(screen.getByText("E-mail")).toBeInTheDocument();
    expect(screen.getByText("Telefon")).toBeInTheDocument();
    expect(screen.getByText("jan@example.com")).toBeInTheDocument();
    expect(screen.getByText("+48 600 100 200")).toBeInTheDocument();
  });

  it("oznacza wartość pochodzącą z profilu kandydata", () => {
    // Bez tego wyczyszczenie pola wygląda na niezapisaną zmianę: „skasowałem,
    // a dalej coś jest".
    setup({ emailSource: "candidate_profile", phoneSource: "contract" });
    expect(screen.getAllByText("z profilu")).toHaveLength(1);
  });

  it("nie oznacza wartości wpisanej na umowie", () => {
    setup();
    expect(screen.queryByText("z profilu")).not.toBeInTheDocument();
  });

  it("brak wartości pokazuje „—”, a nie pustą komórkę", () => {
    // Puste miejsce obok wypełnionych pól czyta się jak utrata danych.
    setup({ email: null, emailSource: null, phone: null, phoneSource: null });
    expect(screen.getAllByText("—")).toHaveLength(2);
  });

  it("zapisuje zmianę e-maila w miejscu", async () => {
    const user = userEvent.setup();
    const { onSaveEmail } = setup();

    await user.click(screen.getByRole("button", { name: "Edytuj: E-mail" }));
    const input = screen.getByRole("textbox", { name: "E-mail" });
    await user.clear(input);
    await user.type(input, "nowy@example.com");
    await user.keyboard("{Enter}");

    await waitFor(() => expect(onSaveEmail).toHaveBeenCalledWith("nowy@example.com"));
  });

  it("wyczyszczenie pola wysyła pusty string — to sygnał „wróć do profilu”", async () => {
    const user = userEvent.setup();
    const { onSavePhone } = setup();

    await user.click(screen.getByRole("button", { name: "Edytuj: Telefon" }));
    await user.clear(screen.getByRole("textbox", { name: "Telefon" }));
    await user.keyboard("{Enter}");

    await waitFor(() => expect(onSavePhone).toHaveBeenCalledWith(""));
  });

  it("bez uprawnień pokazuje wartości, ale nie daje ołówka", () => {
    setup({ editable: false });
    expect(screen.getByText("jan@example.com")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edytuj: E-mail" }),
    ).not.toBeInTheDocument();
  });

  it("odmowa zapisu trafia do obsługi błędu, nie ginie", async () => {
    const user = userEvent.setup();
    const onSaveEmail = vi.fn().mockRejectedValue(new Error("E-mail jest za długi"));
    const onError = vi.fn();
    render(
      <ContractCandidateContactRow
        email="jan@example.com"
        emailSource="contract"
        phone={null}
        phoneSource={null}
        editable
        onSaveEmail={onSaveEmail}
        onSavePhone={vi.fn()}
        onError={onError}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Edytuj: E-mail" }));
    const input = screen.getByRole("textbox", { name: "E-mail" });
    await user.clear(input);
    await user.type(input, "x@example.com");
    await user.keyboard("{Enter}");

    await waitFor(() => expect(onError).toHaveBeenCalledWith("E-mail jest za długi"));
  });
});
