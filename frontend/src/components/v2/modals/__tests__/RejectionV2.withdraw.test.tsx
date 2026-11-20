/**
 * Rezygnacja w tym samym oknie (decyzja Artura 19.11.2026): „Kto kończy? →
 * Kandydat rezygnuje” zamienia odrzucenie w rezygnację, a przycisk
 * „Zrezygnował” otwiera okno z tą odpowiedzią wybraną.
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

const reasons = [
  { id: "1", name: "Brak doświadczenia", label: "Brak doświadczenia", applies_to: ["rejected" as const] },
  { id: "2", name: "Za wysokie oczekiwania finansowe", label: "Za droga", applies_to: ["rejected" as const] },
  { id: "9", name: "Inne (rejected)", label: "Inne", applies_to: ["rejected" as const] },
  { id: "21", name: "counter_offer", label: "Kontroferta", applies_to: ["withdrawn" as const] },
  { id: "22", name: "salary_mismatch", label: "Za droga", applies_to: ["withdrawn" as const] },
  { id: "29", name: "Inne (withdrawn)", label: "Inne", applies_to: ["withdrawn" as const] },
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
      previousStageCategory="external"
      previousStage="cv_sent"
      canWithdraw
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
const candidate = () => screen.getByRole("radio", { name: /Kandydat rezygnuje/ });

describe("RejectionV2 — „Kandydat rezygnuje” w tym samym oknie", () => {
  it("odrzucenie zamienia się w rezygnację: lista kandydata, bez maila, wiersz rezygnacji", () => {
    const onConfirm = renderWindow();
    expect(screen.getByText(/Wyślij e-mail/)).toBeInTheDocument();
    fireEvent.click(candidate());
    expect(screen.getByText("Zamknij proces — kandydat rezygnuje")).toBeInTheDocument();
    expect(screen.queryByText("Za mało doświadczenia")).toBeNull();
    expect(screen.queryByText(/Wyślij e-mail/)).toBeNull();
    fireEvent.click(screen.getByText("Kontroferta od obecnego pracodawcy"));
    fireEvent.click(confirm());
    const call = onConfirm.mock.calls[0];
    expect(call[0]).toBe("21");
    expect(call[2]).toBe(false);
    expect(call[5]).toBe("candidate");
    expect(call[9]).toBeNull();
  });

  it("ten sam powód po obu stronach idzie do wiersza strony, która kończy", () => {
    const onConfirm = renderWindow();
    fireEvent.click(screen.getByText("Za droga"));
    fireEvent.click(candidate());
    // „Za droga” jest na liście kandydata — wybór zostaje.
    fireEvent.click(confirm());
    expect(onConfirm.mock.calls[0][0]).toBe("22");
  });

  it("powód tylko nasz znika po przełączeniu na kandydata", () => {
    renderWindow();
    fireEvent.click(screen.getByText("Za mało doświadczenia"));
    fireEvent.click(candidate());
    expect(confirm()).toBeDisabled();
  });

  it("„Zrezygnował” otwiera okno z wybranym kandydatem; można wrócić do odrzucenia", () => {
    const onConfirm = renderWindow({ terminalType: "withdrawn" });
    expect(candidate()).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: /Odrzucamy my/ }));
    expect(screen.getByText("Zamknij proces — odrzucenie")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Za mało doświadczenia"));
    fireEvent.click(confirm());
    expect(onConfirm.mock.calls[0][0]).toBe("1");
    expect(onConfirm.mock.calls[0][5]).toBe("recruiter");
  });

  it("po akceptacji oferty pyta o reakcję tylko przy rezygnacji", () => {
    renderWindow({ previousStage: "acceptance" });
    expect(screen.queryByText("Reakcja kandydata na ofertę")).toBeNull();
    fireEvent.click(candidate());
    expect(screen.getByText("Reakcja kandydata na ofertę")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Kontroferta od obecnego pracodawcy"));
    expect(confirm()).toBeDisabled();
    fireEvent.click(screen.getByText("Wycofał się PO akceptacji oferty"));
    expect(confirm()).not.toBeDisabled();
  });

  it("bez `canWithdraw` odpowiedzi „Kandydat rezygnuje” nie ma", () => {
    renderWindow({ canWithdraw: false });
    expect(screen.queryByRole("radio", { name: /Kandydat rezygnuje/ })).toBeNull();
  });
});
