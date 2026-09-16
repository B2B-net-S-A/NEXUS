/**
 * „Struktura umów" Centrum e-Zdrowia: dodanie umowy wykonawczej bez
 * opuszczania profilu. Okno dostaje preselekcję ramowej, przy której
 * kliknięto, a po zapisie struktura, przegląd i profil są unieważniane —
 * select w formularzach zamówień oferuje tylko to, co tu już istnieje.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ContractStructureResponse,
  ExecutiveContractReviewResponse,
} from "@/lib/api/executiveContracts";
import { EZDROWIE_CLIENT_ID } from "@/lib/ezdrowie";

const mocks = vi.hoisted(() => ({
  structure: vi.fn(),
  review: vi.fn(),
  create: vi.fn(),
  assign: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: mocks.showSuccess,
    showError: mocks.showError,
    showToast: vi.fn(),
    showActionToast: vi.fn(),
  }),
}));

// Czyste funkcje i hooki zostają prawdziwe — podmieniamy metody obiektu API,
// które hooki wołają przez tę samą referencję.
vi.mock("@/lib/api/executiveContracts", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/api/executiveContracts")>();
  Object.assign(actual.executiveContractsApi, {
    structure: (...args: unknown[]) => mocks.structure(...args),
    review: (...args: unknown[]) => mocks.review(...args),
    create: (...args: unknown[]) => mocks.create(...args),
    assign: (...args: unknown[]) => mocks.assign(...args),
  });
  return { ...actual };
});

import { ContractStructureSection } from "@/components/client-profile/ContractStructureSection";
import { contractStructureQueryKey } from "@/lib/api/executiveContracts";

const STRUCTURE: ContractStructureResponse = {
  framework_contracts: [
    {
      id: 2,
      name: "CeZ/145/2025 – cz. II",
      project_part: "cz2",
      status: "active",
      executive_contracts: [
        {
          id: 10,
          number: "CeZ/145/2025/UW-1",
          status: "active",
          framework_contract_id: 2,
          project_part: "cz2",
          notes: null,
          consultants_count: 3,
          created_at: null,
        },
      ],
    },
    {
      id: 4,
      name: "CeZ/147/2025 – cz. IV",
      project_part: "cz4",
      status: "active",
      executive_contracts: [],
    },
  ],
};

const EMPTY_REVIEW: ExecutiveContractReviewResponse = { rows: [], total: 0 };

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  render(
    <QueryClientProvider client={queryClient}>
      <ContractStructureSection clientId={EZDROWIE_CLIENT_ID} />
    </QueryClientProvider>,
  );
  return { queryClient, invalidate };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.structure.mockResolvedValue(STRUCTURE);
  mocks.review.mockResolvedValue(EMPTY_REVIEW);
});

describe("ContractStructureSection", () => {
  it("dodaje umowę wykonawczą pod klikniętą ramową i odświeża trzy zapytania", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.create.mockResolvedValue({
      id: 13,
      number: "CeZ/147/2025/UW-1",
      status: "active",
      framework_contract_id: 4,
      project_part: "cz4",
      notes: null,
      consultants_count: 0,
      created_at: null,
    });
    const { invalidate } = renderSection();

    expect(await screen.findByText("3 konsultantów")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Dodaj umowę wykonawczą: Cz. IV — CeZ/147/2025" }),
    );

    const dialog = await screen.findByRole("dialog", { name: "Dodaj umowę wykonawczą" });
    expect(dialog).toBeInTheDocument();
    // Preselekcja ramowej, przy której kliknięto — ale select edytowalny.
    expect(screen.getByRole("combobox", { name: "Umowa ramowa" })).toHaveValue("4");
    expect(screen.getByText("Nowa umowa wykonawcza dostaje status Aktywna.")).toBeInTheDocument();

    const submit = screen.getByRole("button", { name: "Zapisz umowę wykonawczą" });
    expect(submit).toBeDisabled();
    await user.type(
      screen.getByRole("textbox", { name: "Numer umowy wykonawczej" }),
      "  CeZ/147/2025/UW-1  ",
    );
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() =>
      expect(mocks.create).toHaveBeenCalledWith(EZDROWIE_CLIENT_ID, {
        framework_contract_id: 4,
        number: "CeZ/147/2025/UW-1",
        notes: null,
      }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Dodaj umowę wykonawczą" })).toBeNull(),
    );
    expect(mocks.showSuccess).toHaveBeenCalledWith("Dodano umowę wykonawczą CeZ/147/2025/UW-1");
    const keys = invalidate.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(keys).toEqual(
      expect.arrayContaining([
        JSON.stringify(contractStructureQueryKey(EZDROWIE_CLIENT_ID)),
        JSON.stringify(["executive-contract-review", EZDROWIE_CLIENT_ID]),
        JSON.stringify(["client-profile", EZDROWIE_CLIENT_ID]),
      ]),
    );
    // Struktura została odpytana ponownie — chipy zobaczą nową umowę.
    await waitFor(() => expect(mocks.structure).toHaveBeenCalledTimes(2));
  });

  it("odmowa serwera zostaje w oknie, nie zamyka go i nie unieważnia cache’u", async () => {
    const user = userEvent.setup({ delay: null });
    // Kształt błędu axiosa — `apiErrorMessage` czyta `response.data.detail`,
    // a plain `Error` dostałby komunikat zastępczy.
    mocks.create.mockRejectedValue({
      response: { status: 409, data: { detail: "Numer umowy wykonawczej już istnieje" } },
    });
    const { invalidate } = renderSection();

    await user.click(
      await screen.findByRole("button", {
        name: "Dodaj umowę wykonawczą: Cz. II — CeZ/145/2025",
      }),
    );
    await user.type(
      await screen.findByRole("textbox", { name: "Numer umowy wykonawczej" }),
      "CeZ/145/2025/UW-1",
    );
    await user.click(screen.getByRole("button", { name: "Zapisz umowę wykonawczą" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Numer umowy wykonawczej już istnieje",
    );
    expect(screen.getByRole("dialog", { name: "Dodaj umowę wykonawczą" })).toBeInTheDocument();
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("awaria struktury renderuje się jako błąd z ponowieniem, nie jako pustka", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.structure.mockReset();
    mocks.structure
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(STRUCTURE);
    renderSection();

    const retry = await screen.findByRole("button", { name: /Spróbuj ponownie/ });
    expect(screen.queryByText(/struktura umów jest pusta/)).toBeNull();
    await user.click(retry);
    expect(await screen.findByText("Cz. II — CeZ/145/2025")).toBeInTheDocument();
  });
});
