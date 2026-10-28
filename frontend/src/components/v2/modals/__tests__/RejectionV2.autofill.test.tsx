/**
 * Odrzucenie osoby od systemu z powodem (silnik „Nowi na 20”, makieta A3,
 * 23.10.2026): okno pyta „skąd wiesz” i o powód, bez obu nie da się
 * potwierdzić, a wybór idzie jako 10. argument `onConfirm`. Od 27.10.2026
 * o powód pyta raz — powód z szablonu wynika z powodu dla systemu.
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
import {
  autofillBucketHint,
  autofillMoveFields,
  needsAutofillReason,
  templateReasonFor,
} from "@/lib/autofill-feedback";

const reasons = [
  { id: "1", name: "Brak doświadczenia", label: "Brak doświadczenia", applies_to: ["rejected" as const] },
  {
    id: "2",
    name: "Nie spełnia wymagań technicznych",
    label: "Nie spełnia wymagań technicznych",
    applies_to: ["rejected" as const],
  },
  { id: "3", name: "Nie pasuje kulturowo", label: "Nie pasuje kulturowo", applies_to: ["rejected" as const] },
  { id: "6", name: "work_mode_mismatch", label: "Nie akceptuje trybu pracy", applies_to: ["rejected" as const] },
  { id: "9", name: "Inne (rejected)", label: "Inne", applies_to: ["rejected" as const] },
];

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
  it("pyta o powód raz: bez listy z szablonu, bez „skąd wiesz” nie da się potwierdzić", () => {
    const onConfirm = renderWith({ rateKnown: false, several: false });
    expect(screen.queryByText("Nie pasuje kulturowo")).toBeNull();
    expect(screen.getAllByText("Powód")).toHaveLength(1);
    const confirm = screen.getByRole("button", { name: "Potwierdź" });
    fireEvent.click(screen.getByText("Brak kluczowej umiejętności"));
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByText("Z rozmowy z osobą"));
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    const args = onConfirm.mock.calls[0];
    expect(args[0]).toBe("2");
    expect(args[1]).toBe("");
    expect(args[9]).toEqual({ reason: "missing_skill", learnedFrom: "call", rateHourly: null });
  });

  it("„Nie chce do tego klienta” domyślnie na cały klient; odznaczone idzie jako jedna rekrutacja", () => {
    const onConfirm = renderWith({ rateKnown: false, several: false });
    fireEvent.click(screen.getByText("Nie chce do tego klienta"));
    fireEvent.click(screen.getByText("Z rozmowy z osobą"));
    const box = screen.getByRole("checkbox", { name: /Dotyczy wszystkich rekrutacji tego klienta/ });
    expect(box).toBeChecked();
    expect(screen.getByText(/„Sprawa osoby”/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][0]).toBe("9");
    expect(onConfirm.mock.calls[0][9]).toEqual({
      reason: "client_refused",
      learnedFrom: "call",
      rateHourly: null,
      wholeClient: true,
    });
    expect(autofillMoveFields(onConfirm.mock.calls[0][9])).toMatchObject({ autofill_whole_client: true });
  });

  it("„Pracuje u tego klienta” można zawęzić do tej rekrutacji; przy innych powodach pola nie ma", () => {
    const onConfirm = renderWith({ rateKnown: false, several: false });
    fireEvent.click(screen.getByText("Brak kluczowej umiejętności"));
    expect(screen.queryByTestId("autofill-whole-client")).toBeNull();
    fireEvent.click(screen.getByText("Pracuje u tego klienta (też przez inną firmę)"));
    fireEvent.click(screen.getByRole("checkbox", { name: /Dotyczy wszystkich rekrutacji tego klienta/ }));
    fireEvent.click(screen.getByText("Z CV i profilu, bez kontaktu"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    const choice = onConfirm.mock.calls[0][9];
    expect(choice).toEqual({
      reason: "client_employed",
      learnedFrom: "profile",
      rateHourly: null,
      wholeClient: false,
    });
    expect(autofillMoveFields(choice).autofill_whole_client).toBeUndefined();
  });

  it("„Lokalizacja lub tryb pracy” liczy się jako tryb pracy i pyta o dni w biurze", () => {
    const onConfirm = renderWith({ rateKnown: false, several: false });
    fireEvent.click(screen.getByText("Lokalizacja lub tryb pracy"));
    fireEvent.click(screen.getByText("Z CV i profilu, bez kontaktu"));
    expect(screen.getByText(/Ile dni w biurze/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    const args = onConfirm.mock.calls[0];
    expect(args[0]).toBe("6");
    expect(args[8]).toEqual({ maxOnsiteDays: 0, saveToProfile: true });
  });

  it("powód bez odpowiednika idzie jako „Inne” z nazwą w opisie", () => {
    const onConfirm = renderWith({ rateKnown: false, several: false });
    fireEvent.click(screen.getByText("Język"));
    fireEvent.click(screen.getByText("Z rozmowy z osobą"));
    fireEvent.change(screen.getByPlaceholderText(/lepszą ofertę/), { target: { value: "Słaby angielski" } });
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    const args = onConfirm.mock.calls[0];
    expect(args[0]).toBe("9");
    expect(args[1]).toBe("Język. Słaby angielski");
  });

  it("„Za droga” z rozmowy niesie stawkę i mówi, do którego kosza trafi", () => {
    const onConfirm = renderWith({ rateKnown: false, several: false });
    fireEvent.click(screen.getByText("Z rozmowy z osobą"));
    fireEvent.click(screen.getByText("Za droga"));
    expect(screen.getByText(/„Brak danych”, nie błąd wyszukiwania/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Ile chce w złotych na godzinę"), {
      target: { value: "175,5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    const args = onConfirm.mock.calls[0];
    // Ta lista nie ma „Za wysokie oczekiwania finansowe” — „Inne” z nazwą.
    expect(args[0]).toBe("9");
    expect(args[1]).toBe("Za droga");
    expect(args[9]).toEqual({
      reason: "too_expensive",
      learnedFrom: "call",
      rateHourly: 175.5,
    });
  });

  it("„Inne” wymaga opisu i nie dokleja nazwy", () => {
    const onConfirm = renderWith({ rateKnown: true, several: true });
    fireEvent.click(screen.getByText("Z CV i profilu, bez kontaktu"));
    fireEvent.click(screen.getByText("Inne — opisz"));
    expect(screen.queryByLabelText("Ile chce w złotych na godzinę")).toBeNull();
    const confirm = screen.getByRole("button", { name: "Potwierdź" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/lepszą ofertę/), { target: { value: "Zna klienta" } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(onConfirm.mock.calls[0][1]).toBe("Zna klienta");
  });

  it("szablon bez powodów: nazwa powodu zamiast wpisywania ręcznie", () => {
    const onConfirm = vi.fn();
    renderUi(
      <RejectionV2
        open
        onOpenChange={() => {}}
        terminalType="rejected"
        reasons={[]}
        previousStageCategory="internal"
        onConfirm={onConfirm}
        autofill={{ rateKnown: false, several: false }}
      />,
    );
    expect(screen.queryByPlaceholderText(/brak wymaganych kompetencji/)).toBeNull();
    fireEvent.click(screen.getByText("Nie odbiera (3 próby)"));
    fireEvent.click(screen.getByText("Z rozmowy z osobą"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    const args = onConfirm.mock.calls[0];
    expect(args[0]).toBe("");
    expect(args[4]).toBe("Nie odbiera (3 próby)");
  });

  it("zwykła osoba — lista z szablonu, bez pytania o powód dla systemu", () => {
    const onConfirm = renderWith(null);
    expect(screen.queryByTestId("autofill-feedback")).toBeNull();
    fireEvent.click(screen.getByText("Nie pasuje kulturowo"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    const args = onConfirm.mock.calls[0];
    expect(args[0]).toBe("3");
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

  it("powód z szablonu dla powodu dla systemu", () => {
    expect(templateReasonFor("too_junior", reasons)?.id).toBe("1");
    expect(templateReasonFor("other_level_or_role", reasons)?.id).toBe("2");
    expect(templateReasonFor("no_answer", reasons)?.id).toBe("9");
    expect(templateReasonFor("missing_skill", [])).toBeUndefined();
    expect(templateReasonFor(null, reasons)).toBeUndefined();
  });
});
