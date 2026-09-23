import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { warsawToday } from "@/lib/warsaw-date";

const mocks = vi.hoisted(() => ({ terminate: vi.fn() }));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  contractsApi: {
    terminate: (...args: unknown[]) => mocks.terminate(...args),
  },
  CONTRACT_TERMINATION_REASONS: [
    { value: "project_ended", label: "Projekt zakończony" },
    { value: "client_budget_cut", label: "Klient — brak budżetu" },
  ],
}));

vi.mock("@/components/ds/AppModal", () => ({
  AppModal: ({
    open,
    title,
    footer,
    children,
  }: {
    open: boolean;
    title: string;
    footer?: React.ReactNode;
    children: React.ReactNode;
  }) =>
    open ? (
      <section aria-label={title}>
        <h1>{title}</h1>
        {children}
        {footer}
      </section>
    ) : null,
}));

import { ContractTerminationDialog } from "@/components/contracts/ContractTerminationDialog";

function renderDialog(defaultDate?: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <ContractTerminationDialog
        contractId={7}
        defaultDate={defaultDate}
        onClose={() => {}}
        onSuccess={() => {}}
      />
    </QueryClientProvider>,
  );
  return screen.getByLabelText(/Data zakończenia projektu/) as HTMLInputElement;
}

/**
 * Zgłoszenie: data zakończenia była wpisywana dwa razy — raz w formularzu
 * edycji kontraktu, raz tutaj. Kartę kontraktu (`app/contracts/[id]/page.tsx`)
 * da się sprawdzić wyłącznie testem czytającym źródło (sesja + kilkanaście
 * zapytań), więc zachowanie samego pola pilnujemy tu.
 */
describe("ContractTerminationDialog — data zakończenia projektu", () => {
  it("startuje z datą podaną przez formularz edycji", () => {
    expect(renderDialog("2026-11-30").value).toBe("2026-11-30");
  });

  it("pozostawia pole edytowalne — datę można skorygować przed potwierdzeniem", async () => {
    const input = renderDialog("2026-11-30");
    expect(input).not.toBeDisabled();
    expect(input).not.toHaveAttribute("readonly");

    await userEvent.clear(input);
    await userEvent.type(input, "2026-12-15");

    expect(input.value).toBe("2026-12-15");
  });

  it("bez daty z formularza podstawia dzisiaj", () => {
    // „Dziś” w czasie polskim, jak komponent — UTC myliło się 22–24 UTC.
    expect(renderDialog(undefined).value).toBe(warsawToday());
  });
});
