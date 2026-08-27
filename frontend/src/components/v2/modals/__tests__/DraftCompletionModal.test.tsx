import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  update: vi.fn(),
  activate: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  contractsApi: {
    update: (...args: unknown[]) => mocks.update(...args),
    activate: (...args: unknown[]) => mocks.activate(...args),
  },
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: { role: string } }) => unknown) =>
    selector({ user: { role: "admin" } }),
  canManageCandidateFinance: () => true,
}));

// The regression is form validation/payload, not Radix portal positioning.
vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  DialogContent: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  DialogFooter: ({ children }: { children: React.ReactNode }) => <footer>{children}</footer>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <header>{children}</header>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h1>{children}</h1>,
  DialogBody: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

import { DraftCompletionModal } from "@/components/v2/modals/DraftCompletionModal";

function renderModal(contractorOverrides: Record<string, unknown> = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onActivated = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <DraftCompletionModal
        open
        onOpenChange={vi.fn()}
        onActivated={onActivated}
        contractor={
          {
            contract_id: 563,
            candidate: { name: "Agnieszka", lastname: "Urbaniak" },
            start_date: "2026-08-01",
            end_date: null,
            rate_candidate: 100,
            rate_client: 150,
            currency: "PLN",
            contract_type: "b2b",
            work_mode: null,
            missing_fields: [],
            ...contractorOverrides,
          } as never
        }
      />
    </QueryClientProvider>,
  );
  return { onActivated };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.update.mockResolvedValue({ data: {} });
  mocks.activate.mockResolvedValue({ data: {} });
});

describe("DraftCompletionModal — opcjonalny tryb pracy", () => {
  it("aktywuje kontrakt z pustym trybem i wysyła null zamiast sztucznego remote", async () => {
    const user = userEvent.setup({ delay: null });
    const { onActivated } = renderModal();

    expect(screen.getByText("Tryb pracy (opcjonalnie)")).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: /Aktywuj kontrakt/i });
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    expect(mocks.update).toHaveBeenCalledWith(
      563,
      expect.objectContaining({
        work_mode: null,
        rate_candidate_currency: "PLN",
        rate_client_currency: "PLN",
      }),
    );
    expect(mocks.update.mock.calls[0]?.[1]).not.toHaveProperty("currency");
    expect(mocks.activate).toHaveBeenCalledWith(563);
    await waitFor(() => expect(onActivated).toHaveBeenCalledTimes(1));
  });
});

describe("DraftCompletionModal — niezależne waluty stawek", () => {
  it("prefilluje obie waluty, PATCHuje tylko nowe pola i ukrywa nominalną marżę mieszaną", async () => {
    const user = userEvent.setup({ delay: null });
    renderModal({
      currency: "EUR",
      rate_client_currency: "EUR",
      rate_candidate_currency: "PLN",
    });

    expect(
      screen.getByRole("combobox", {
        name: "Waluta stawki przychodowej (klienta)",
      }),
    ).toHaveTextContent("EUR");
    expect(
      screen.getByRole("combobox", {
        name: "Waluta stawki kosztowej (kandydata)",
      }),
    ).toHaveTextContent("PLN");
    expect(screen.queryByText("Marża:")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Aktywuj kontrakt/i }));

    await waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    expect(mocks.update).toHaveBeenCalledWith(
      563,
      expect.objectContaining({
        rate_candidate_currency: "PLN",
        rate_client_currency: "EUR",
      }),
    );
    expect(mocks.update.mock.calls[0]?.[1]).not.toHaveProperty("currency");
  });

  it("pokazuje marżę wyłącznie dla porównywalnych walut i podpisuje ją właściwą walutą", () => {
    renderModal({
      currency: "EUR",
      rate_client_currency: "EUR",
      rate_candidate_currency: "EUR",
    });

    expect(screen.getByText("Marża:").parentElement).toHaveTextContent(
      "Marża: 50 EUR",
    );
  });
});
