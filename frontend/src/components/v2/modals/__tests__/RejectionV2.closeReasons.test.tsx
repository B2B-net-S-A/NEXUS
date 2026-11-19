/**
 * Jeden słownik powodów w oknie odrzucenia (decyzja 19.11.2026): lista zależy
 * od „Kto kończy?” i etapu, zmiana strony zdejmuje powód spoza nowej listy,
 * powód bez wiersza w szablonie idzie jako „Inne” z etykietą w opisie,
 * a karta ręczna nie pyta „Skąd to wiesz?”.
 */
import type * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  default: { post: vi.fn() },
}));

import { RejectionV2 } from "@/components/v2/modals/RejectionV2";

// Szablon po 0745 bez `no_polish` — jak szablon, z którego admin go skasował.
const reasons = [
  { id: "1", name: "Brak doświadczenia", label: "Brak doświadczenia", applies_to: ["rejected" as const] },
  { id: "2", name: "client_chose_other", label: "Klient wybrał kogoś innego", applies_to: ["rejected" as const] },
  { id: "3", name: "not_looking_for_work", label: "Nie szuka pracy", applies_to: ["rejected" as const] },
  { id: "9", name: "Inne (rejected)", label: "Inne", applies_to: ["rejected" as const] },
];

function renderWindow(props: Partial<React.ComponentProps<typeof RejectionV2>> = {}) {
  const onConfirm = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <RejectionV2
      open
      onOpenChange={() => {}}
      terminalType="rejected"
      reasons={reasons}
      previousStageCategory="internal"
      previousStage="verified"
      onConfirm={onConfirm}
      {...props}
    />,
    {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    },
  );
  return onConfirm;
}

const confirm = () => screen.getByRole("button", { name: "Potwierdź" });

describe("RejectionV2 — jeden słownik powodów (19.11.2026)", () => {
  it("„Odrzucamy my” w „Zweryfikowanym”: bez „Dane w bazie” i bez grupy „Klient”", () => {
    renderWindow();
    expect(screen.getByText("Nie pasuje do wymagań")).toBeInTheDocument();
    expect(screen.getByText("Nie szuka pracy")).toBeInTheDocument();
    expect(screen.queryByText("Dane w bazie")).toBeNull();
    expect(screen.queryByText("CV nieaktualne")).toBeNull();
    expect(screen.queryByText("Klient")).toBeNull();
    expect(screen.queryByText("Wybrał innego kandydata")).toBeNull();
    expect(screen.getByText("Inne — opisz")).toBeInTheDocument();
  });

  it("„Odrzuca klient”: grupa „Klient”, bez „Nie szuka pracy”", () => {
    renderWindow();
    fireEvent.click(screen.getByText("Odrzuca klient"));
    expect(screen.getByText("Klient")).toBeInTheDocument();
    expect(screen.getByText("Wybrał innego kandydata")).toBeInTheDocument();
    expect(screen.getByText("Nie podał powodu")).toBeInTheDocument();
    expect(screen.queryByText("Nie szuka pracy")).toBeNull();
    expect(screen.queryByText("Nie odbiera / brak kontaktu")).toBeNull();
  });

  it("zmiana z „Odrzuca klient” na „Odrzucamy my” zdejmuje „Wybrał innego kandydata”", () => {
    const onConfirm = renderWindow({ initialEndedBy: "client" });
    fireEvent.click(screen.getByText("Wybrał innego kandydata"));
    expect(confirm()).toBeEnabled();
    fireEvent.click(screen.getByText("Odrzucamy my"));
    expect(screen.queryByText("Wybrał innego kandydata")).toBeNull();
    expect(confirm()).toBeDisabled();
    fireEvent.click(screen.getByText("Odrzuca klient"));
    expect(screen.getByRole("radio", { name: "Wybrał innego kandydata" })).not.toBeChecked();
    expect(confirm()).toBeDisabled();
    fireEvent.click(confirm());
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("zmiana z „Odrzuca klient” na „Odrzucamy my” zostawia „Za mało doświadczenia”", () => {
    const onConfirm = renderWindow({ initialEndedBy: "client" });
    fireEvent.click(screen.getByText("Za mało doświadczenia"));
    fireEvent.click(screen.getByText("Odrzucamy my"));
    expect(screen.getByRole("radio", { name: "Za mało doświadczenia" })).toBeChecked();
    fireEvent.click(confirm());
    expect(onConfirm.mock.calls[0][0]).toBe("1");
    expect(onConfirm.mock.calls[0][5]).toBe("recruiter");
  });

  it("powód bez wiersza w szablonie wysyła id „Inne” i etykietę na początku opisu", () => {
    const onConfirm = renderWindow();
    fireEvent.click(screen.getByText("Brak polskiego"));
    // Opis nie jest obowiązkowy — etykieta powodu i tak trafia do historii.
    expect(screen.getByText("Notatka (opcjonalnie)")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Klient wymaga C1" } });
    fireEvent.click(confirm());
    const args = onConfirm.mock.calls[0];
    expect(args[0]).toBe("9");
    expect(args[1]).toBe("Brak polskiego. Klient wymaga C1");
  });

  it("powód z wierszem w szablonie nie dokleja etykiety do opisu", () => {
    const onConfirm = renderWindow();
    fireEvent.click(screen.getByText("Za mało doświadczenia"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "2 lata zamiast 5" } });
    fireEvent.click(confirm());
    expect(onConfirm.mock.calls[0][0]).toBe("1");
    expect(onConfirm.mock.calls[0][1]).toBe("2 lata zamiast 5");
  });

  it.each([
    ["„Nowi”", true],
    ["„Zweryfikowany”", false],
  ])("karta ręczna (%s): bez „Skąd to wiesz?”, bez powodu dla systemu", (_column, decisionColumn) => {
    const onConfirm = renderWindow({ autofill: null, decisionColumn });
    expect(screen.queryByText("Skąd to wiesz?")).toBeNull();
    expect(screen.queryByText("Z rozmowy z osobą")).toBeNull();
    expect(screen.queryByText(/To osoba od systemu/)).toBeNull();
    fireEvent.click(screen.getByText("Za mało doświadczenia"));
    fireEvent.click(confirm());
    const args = onConfirm.mock.calls[0];
    expect(args[0]).toBe("1");
    expect(args[9]).toBeNull();
  });
});
