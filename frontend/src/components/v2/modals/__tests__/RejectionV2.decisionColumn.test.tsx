/**
 * Jedna lista powodów w „Nowych” i „Screeningu” (19.11.2026): karta dodana
 * ręcznie dostaje tę samą rozbudowaną listę co osoba od systemu („lepsza jest
 * wersja rozbudowana”), ale bez „Skąd to wiesz?” i bez powodu dla systemu —
 * serwer odrzuca `autofill_*` przy osobie spoza systemu (422).
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
import { isDecisionColumn } from "@/lib/autofill-feedback";

const reasons = [
  { id: "1", name: "Brak doświadczenia", label: "Brak doświadczenia", applies_to: ["rejected" as const] },
  {
    id: "2",
    name: "Nie spełnia wymagań technicznych",
    label: "Nie spełnia wymagań technicznych",
    applies_to: ["rejected" as const],
  },
  { id: "3", name: "Nie pasuje kulturowo", label: "Nie pasuje kulturowo", applies_to: ["rejected" as const] },
  { id: "5", name: "not_looking_for_work", label: "Nie szuka pracy", applies_to: ["rejected" as const] },
  { id: "7", name: "no_contact", label: "Brak kontaktu", applies_to: ["rejected" as const] },
  { id: "9", name: "Inne (rejected)", label: "Inne", applies_to: ["rejected" as const] },
];

function renderUi(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(ui, {
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  });
}

function renderManual(decisionColumn: boolean) {
  const onConfirm = vi.fn();
  renderUi(
    <RejectionV2
      open
      onOpenChange={() => {}}
      terminalType="rejected"
      reasons={reasons}
      previousStageCategory="internal"
      previousStage="new"
      onConfirm={onConfirm}
      autofill={null}
      decisionColumn={decisionColumn}
    />,
  );
  return onConfirm;
}

describe("RejectionV2 — karta ręczna w „Nowych”/„Screeningu”", () => {
  it("pokazuje rozbudowaną listę bez „Skąd to wiesz?” i wysyła powód z szablonu bez powodu dla systemu", () => {
    const onConfirm = renderManual(true);
    expect(screen.getByText("Nie pasuje do wymagań")).toBeInTheDocument();
    expect(screen.getByText("Pieniądze i dane")).toBeInTheDocument();
    expect(screen.queryByText("Nie pasuje kulturowo")).toBeNull();
    expect(screen.queryByText("Skąd to wiesz?")).toBeNull();
    expect(screen.queryByText(/To osoba od systemu/)).toBeNull();
    const confirm = screen.getByRole("button", { name: "Potwierdź" });
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByText("Za mało doświadczenia"));
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    const args = onConfirm.mock.calls[0];
    expect(args[0]).toBe("1");
    expect(args[9]).toBeNull();
    expect(args[12]).toBeNull();
  });

  it("powód bez odpowiednika w szablonie idzie jako „Inne” z nazwą powodu w opisie", () => {
    const onConfirm = renderManual(true);
    fireEvent.click(screen.getByText("Brak polskiego"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][0]).toBe("9");
    expect(onConfirm.mock.calls[0][1]).toBe("Brak polskiego");
  });

  it("„Nie szuka pracy” pyta „do kiedy” i niesie datę jako `notLookingUntil`, nie w powodzie dla systemu", () => {
    const onConfirm = renderManual(true);
    fireEvent.click(screen.getByText("Nie szuka pracy"));
    expect(screen.getByTestId("autofill-not-looking-until")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    const args = onConfirm.mock.calls[0];
    expect(args[0]).toBe("5");
    expect(args[9]).toBeNull();
    expect(args[12]).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("„Inne — opisz” wymaga opisu", () => {
    renderManual(true);
    fireEvent.click(screen.getByText("Inne — opisz"));
    const confirm = screen.getByRole("button", { name: "Potwierdź" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Wyjeżdża za granicę" } });
    expect(confirm).toBeEnabled();
  });

  it("poza „Nowymi”/„Screeningiem” zostaje lista z szablonu", () => {
    renderManual(false);
    expect(screen.getByText("Nie pasuje kulturowo")).toBeInTheDocument();
    expect(screen.queryByText("Pieniądze i dane")).toBeNull();
  });

  it("kolumny decyzji to tylko „Nowi” i „Screening”", () => {
    expect(isDecisionColumn("new")).toBe(true);
    expect(isDecisionColumn("screening")).toBe(true);
    expect(isDecisionColumn("verified")).toBe(false);
    expect(isDecisionColumn(null)).toBe(false);
  });
});
