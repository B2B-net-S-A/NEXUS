/**
 * Odrzucenie osoby od systemu z powodem (silnik „Nowi na 20”, makieta A3,
 * 23.10.2026): okno pyta „skąd wiesz” i „dlaczego odpada”, bez obu nie da się
 * potwierdzić, a wybór idzie jako ostatni argument `onConfirm`.
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
import { parseRateInput } from "@/components/v2/modals/AutofillFeedbackField";
import { autofillBucketHint, autofillMoveFields, needsAutofillReason } from "@/lib/autofill-feedback";

const reasons = [{ id: "7", label: "Nie pasuje", applies_to: ["rejected" as const] }];

function renderUi(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(ui, {
    wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  });
}

function renderWith(autofill: { rateKnown: boolean; several: boolean } | null) {
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
      autofill={autofill}
    />,
  );
  return onConfirm;
}

describe("RejectionV2 — osoba od systemu", () => {
  it("bez „skąd wiesz” i powodu nie da się potwierdzić", () => {
    renderWith({ rateKnown: false, several: false });
    fireEvent.click(screen.getByText("Nie pasuje"));
    const confirm = screen.getByRole("button", { name: "Potwierdź" });
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByText("Z rozmowy z osobą"));
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByText("Brak kluczowej umiejętności"));
    expect(confirm).toBeEnabled();
  });

  it("„Za droga” z rozmowy niesie stawkę i mówi, do którego kosza trafi", () => {
    const onConfirm = renderWith({ rateKnown: false, several: false });
    fireEvent.click(screen.getByText("Nie pasuje"));
    fireEvent.click(screen.getByText("Z rozmowy z osobą"));
    fireEvent.click(screen.getByText("Za droga"));
    expect(screen.getByText(/„Brak danych”, nie błąd wyszukiwania/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Ile chce w złotych na godzinę"), {
      target: { value: "175,5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    const args = onConfirm.mock.calls[0];
    expect(args[9]).toEqual({
      reason: "too_expensive",
      learnedFrom: "call",
      rateHourly: 175.5,
    });
  });

  it("„Inne” wymaga opisu, a bez osoby od systemu okno nie pyta", () => {
    renderWith({ rateKnown: true, several: true });
    fireEvent.click(screen.getByText("Nie pasuje"));
    fireEvent.click(screen.getByText("Z CV i profilu, bez kontaktu"));
    fireEvent.click(screen.getByText("Inne — opisz"));
    expect(screen.queryByLabelText("Ile chce w złotych na godzinę")).toBeNull();
    const confirm = screen.getByRole("button", { name: "Potwierdź" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/lepszą ofertę/), { target: { value: "Zna klienta" } });
    expect(confirm).toBeEnabled();
  });

  it("zwykła osoba — bez pytania o powód dla systemu", () => {
    const onConfirm = renderWith(null);
    expect(screen.queryByTestId("autofill-feedback")).toBeNull();
    fireEvent.click(screen.getByText("Nie pasuje"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    const args = onConfirm.mock.calls[0];
    expect(args[9]).toBeNull();
  });
});

describe("autofill-feedback", () => {
  it("pyta tylko o osoby od systemu w „Nowych” i „Screeningu”", () => {
    expect(needsAutofillReason({ entry_source: "system" }, "new")).toBe(true);
    expect(needsAutofillReason({ entry_source: "system" }, "screening")).toBe(true);
    expect(needsAutofillReason({ entry_source: "system" }, "verified")).toBe(false);
    expect(needsAutofillReason({ entry_source: "added_manual" }, "new")).toBe(false);
  });

  it("pola żądania i podpowiedzi koszy", () => {
    expect(autofillMoveFields(null)).toEqual({});
    expect(
      autofillMoveFields({ reason: "not_looking", learnedFrom: "call", rateHourly: null }),
    ).toEqual({ autofill_reason: "not_looking", autofill_learned_from: "call", autofill_rate_hourly: undefined });
    expect(autofillBucketHint("missing_skill", false)).toContain("Błąd wyszukiwania");
    expect(autofillBucketHint("too_expensive", true)).toContain("porówna ją z budżetem");
    expect(parseRateInput("abc")).toBeNull();
    expect(parseRateInput("")).toBeNull();
    expect(parseRateInput("160")).toBe(160);
  });
});
