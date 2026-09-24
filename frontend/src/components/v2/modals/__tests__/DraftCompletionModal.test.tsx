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

import { DraftCompletionModal, contractorFullName } from "@/components/v2/modals/DraftCompletionModal";

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
  mocks.update.mockResolvedValue({ data: { status: "active" } });
  mocks.activate.mockResolvedValue({ data: {} });
});

describe("DraftCompletionModal — opcjonalny tryb pracy", () => {
  it("PATCHuje wymagane pola raz i polega na automatycznej aktywacji backendu", async () => {
    const user = userEvent.setup({ delay: null });
    const { onActivated } = renderModal();

    expect(screen.getByText("Tryb pracy (opcjonalnie)")).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: /Aktywuj kontrakt/i });
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() => {
      expect(mocks.update).toHaveBeenCalledTimes(1);
      expect(mocks.activate).not.toHaveBeenCalled();
      expect(onActivated).toHaveBeenCalledTimes(1);
    });
    expect(mocks.update).toHaveBeenCalledWith(
      563,
      expect.objectContaining({
        work_mode: null,
        rate_candidate_currency: "PLN",
        rate_client_currency: "PLN",
      }),
    );
    expect(mocks.update.mock.calls[0]?.[1]).not.toHaveProperty("currency");
  });

  it("zachowuje jawne Aktywuj dla kompletnego legacy draftu", async () => {
    mocks.update.mockResolvedValueOnce({ data: { status: "draft" } });
    const user = userEvent.setup({ delay: null });
    renderModal();

    await user.click(screen.getByRole("button", { name: /Aktywuj kontrakt/i }));

    await waitFor(() => {
      expect(mocks.update).toHaveBeenCalledTimes(1);
      expect(mocks.activate).toHaveBeenCalledWith(563);
    });
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

// UAT B25: formularz aktywacji pokazywał „130" bez jednostki, a szczegóły
// kontraktu obok mówiły „Godzinowo, 130 PLN/h".
describe("DraftCompletionModal — tytuł okna (UAT B25)", () => {
  it("rozdziela imię i nazwisko spacją", () => {
    renderModal();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Uzupełnij kontrakt — Agnieszka Urbaniak",
    );
  });

  it("pusta część nazwy nie zostawia spacji ani „undefined”", () => {
    expect(contractorFullName({ candidate: { name: "Agnieszka", lastname: "" } } as never)).toBe("Agnieszka");
    expect(contractorFullName({ candidate: { name: null, lastname: " Urbaniak " } } as never)).toBe("Urbaniak");
  });
});

describe("DraftCompletionModal — jednostka stawek (UAT B25)", () => {
  it("pokazuje jednostkę kontraktu przy obu polach stawek i w podpowiedzi", () => {
    renderModal({ rate_unit: "hourly" });

    expect(screen.getByTestId("rate-candidate-unit")).toHaveTextContent("PLN/h");
    expect(screen.getByTestId("rate-client-unit")).toHaveTextContent("PLN/h");
    expect(screen.getByTestId("rate-unit-hint")).toHaveTextContent(
      "Jednostka stawek: Godzinowo (/h)",
    );
  });

  it("jednostka dzienna czyta się jako MD, miesięczna jako /mc", () => {
    renderModal({
      rate_unit: "daily",
      currency: "EUR",
      rate_client_currency: "EUR",
      rate_candidate_currency: "EUR",
    });
    expect(screen.getByTestId("rate-client-unit")).toHaveTextContent("EUR/MD");
    expect(screen.getByTestId("rate-unit-hint")).toHaveTextContent("Dziennie (/MD)");
  });

  it("nie zgaduje jednostki, gdy payload jej nie niesie", () => {
    renderModal({ rate_unit: undefined });

    expect(screen.queryByTestId("rate-client-unit")).not.toBeInTheDocument();
    expect(screen.getByTestId("rate-unit-hint")).toHaveTextContent(
      "Jednostka stawki nieznana",
    );
  });
});

describe("DraftCompletionModal — audyt 24.09 (S12)", () => {
  it("zerowa albo pusta stawka nie aktywuje kontraktu", async () => {
    const user = userEvent.setup({ delay: null });
    renderModal({ rate_client: null });

    const submit = screen.getByRole("button", { name: /Aktywuj kontrakt/i });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText(/Stawka przychodowa/), "0");
    expect(submit).toBeDisabled();
  });

  it("umowa B2B bez zakończenia nie ma pola daty i czyści zapisaną datę (audyt 24.09, M5)", async () => {
    // Okno mówi „Bezterminowo", więc zapis musi to zrobić: zapisana data
    // końca zostawała, a nocny cron kończył potem aktywowany kontrakt
    // (lustro formularza edycji na /contracts/[id], który wysyła null).
    const user = userEvent.setup({ delay: null });
    renderModal({ contract_type: "b2b", status: "draft", end_date: "2026-12-31" });

    expect(screen.getByTestId("draft-end-date-b2b-indefinite")).toBeInTheDocument();
    expect(screen.queryByLabelText("Data zakończenia")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Aktywuj kontrakt/i }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    expect(mocks.update.mock.calls[0]?.[1]).toHaveProperty("end_date", null);
  });

  it("umowa o pracę nadal ma datę zakończenia", () => {
    renderModal({ contract_type: "uop", status: "draft" });
    expect(screen.getByLabelText("Data zakończenia")).toBeInTheDocument();
  });
});
