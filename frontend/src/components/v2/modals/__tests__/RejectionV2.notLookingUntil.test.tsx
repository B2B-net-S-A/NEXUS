/**
 * „Nie szuka pracy” z datą przy karcie dodanej ręcznie (19.11.2026). Wybór
 * „3 miesiące / 6 miesięcy / Rok” stał tylko przy osobie od systemu; teraz
 * okno pyta o datę przy każdej karcie, a data idzie jako 13. argument
 * `onConfirm` (`not_looking_until` w ruchu).
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
import { notLookingUntil } from "@/lib/autofill-feedback";

const NOT_LOOKING = "Nie szuka pracy lub niezainteresowany";

const reasons = [
  { id: "1", name: "Brak doświadczenia", label: "Brak doświadczenia", applies_to: ["rejected" as const] },
  { id: "10", name: "not_looking_for_work", label: NOT_LOOKING, applies_to: ["rejected" as const] },
  { id: "99", name: "Inne (rejected)", label: "Inne", applies_to: ["rejected" as const] },
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
      previousStage="screening"
      onConfirm={onConfirm}
      {...props}
    />,
    {
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    },
  );
  return onConfirm;
}

describe("RejectionV2 — „Nie szuka pracy” z datą przy karcie dodanej ręcznie", () => {
  it("pyta, do kiedy nie podsuwać; domyślnie 3 miesiące", () => {
    const onConfirm = renderWindow();
    expect(screen.queryByTestId("autofill-not-looking-until")).toBeNull();
    fireEvent.click(screen.getByText(NOT_LOOKING));
    expect(screen.getByTestId("autofill-not-looking-until")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    const args = onConfirm.mock.calls[0];
    expect(args[0]).toBe("10");
    expect(args[12]).toBe(notLookingUntil(3));
  });

  it("„6 miesięcy” wysyła datę za pół roku", () => {
    const onConfirm = renderWindow();
    fireEvent.click(screen.getByText(NOT_LOOKING));
    fireEvent.click(screen.getByRole("button", { name: "6 miesięcy" }));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][12]).toBe(notLookingUntil(6));
  });

  it("przy innym powodzie nie ma pola i data nie idzie", () => {
    const onConfirm = renderWindow();
    fireEvent.click(screen.getByText(NOT_LOOKING));
    fireEvent.click(screen.getByText("Brak doświadczenia"));
    expect(screen.queryByTestId("autofill-not-looking-until")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onConfirm.mock.calls[0][12]).toBeNull();
  });

  it("przy osobie od systemu data zostaje w wyborze dla systemu, nie w 13. argumencie", () => {
    const onConfirm = renderWindow({ autofill: { rateKnown: false, several: false } });
    fireEvent.click(screen.getByText("Nie szuka pracy"));
    fireEvent.click(screen.getByText("Z rozmowy z osobą"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    const args = onConfirm.mock.calls[0];
    expect(args[9]).toMatchObject({ reason: "not_looking", notLookingUntil: notLookingUntil(3) });
    expect(args[12]).toBeNull();
  });
});
