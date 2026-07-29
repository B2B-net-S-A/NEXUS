import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  B2BConfirmFullySignedResult,
  B2BGeneratedContractRow,
} from "@/lib/api";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  generated: vi.fn(),
  confirmFullySigned: vi.fn(),
  updateGenerated: vi.fn(),
  deleteGenerated: vi.fn(),
  downloadGenerated: vi.fn(),
  showActionToast: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showActionToast: mocks.showActionToast,
    showSuccess: mocks.showSuccess,
    showError: mocks.showError,
  }),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...args: unknown[]) => mocks.apiGet(...args),
  },
  b2bGeneratorApi: {
    generated: (...args: unknown[]) => mocks.generated(...args),
    confirmFullySigned: (...args: unknown[]) =>
      mocks.confirmFullySigned(...args),
    updateGenerated: (...args: unknown[]) => mocks.updateGenerated(...args),
    deleteGenerated: (...args: unknown[]) => mocks.deleteGenerated(...args),
    downloadGenerated: (...args: unknown[]) =>
      mocks.downloadGenerated(...args),
  },
  extractErrorMsg: (error: unknown) =>
    error instanceof Error ? error.message : "Błąd",
  signingApi: {},
}));

import {
  GeneratedContractsTab,
  reuseOrGenerateContractId,
} from "@/components/v2/pages/B2BContractGeneratorV2";

beforeAll(() => {
  for (const [name, value] of [
    ["hasPointerCapture", () => false],
    ["setPointerCapture", () => undefined],
    ["releasePointerCapture", () => undefined],
  ] as const) {
    if (!(name in Element.prototype)) {
      Object.defineProperty(Element.prototype, name, {
        configurable: true,
        value,
      });
    }
  }
});

function generatedRow(
  overrides: Partial<B2BGeneratedContractRow> = {},
): B2BGeneratedContractRow {
  return {
    id: 1,
    contract_number: "1471/2026",
    partner_name: "Jan Kowalski",
    client_name: "Nazwa z dokumentu",
    language: "pl",
    signing_date: "2026-07-24",
    created_at: "2026-07-24T10:30:00Z",
    created_by_name: "Marta Rekruter",
    signature_status: "unsigned",
    signature_source: null,
    contract_status: "active",
    closure_reason: null,
    closure_reason_other: null,
    closure_date: null,
    can_change_status: true,
    candidate_id: 7,
    job_id: 20,
    client_id: 3,
    contract_id: null,
    candidate_name: "Jan Kowalski",
    job_title: "Cloud Engineer",
    canonical_client_name: "Nordea",
    signed_at: null,
    signed_by_name: null,
    can_confirm_signed: true,
    blocked_reason: null,
    can_delete: true,
    can_edit: true,
    can_download: false,
    ...overrides,
  };
}

function confirmationResult(
  outcome: B2BConfirmFullySignedResult["outcome"],
): B2BConfirmFullySignedResult {
  return {
    outcome,
    contract_id: 91,
    order_id: outcome === "already_processed" ? null : 44,
    candidate_id: 7,
    job_id: 20,
    client_id: 3,
    message: "",
    generated_contract: generatedRow({
      signature_status: "signed_both",
      signature_source: "manual_confirmation",
      contract_id: 91,
      can_confirm_signed: false,
      can_delete: false,
      can_edit: false,
    }),
  };
}

function renderTab(rows: B2BGeneratedContractRow[]) {
  mocks.generated.mockResolvedValue(rows);
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <GeneratedContractsTab />
    </QueryClientProvider>,
  );
}

describe("GeneratedContractsTab — status podpisu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.apiGet.mockImplementation((url: string) => {
      if (url === "/api/jobs/20") {
        return Promise.resolve({
          data: {
            title: "Cloud Engineer",
            client_id: 3,
            client_name: "Nordea",
          },
        });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });
  });

  it("pokazuje oba statusy jako tekst z ikoną oraz linki podpisanej umowy", async () => {
    renderTab([
      generatedRow(),
      generatedRow({
        id: 2,
        contract_number: "1472/2026",
        signature_status: "signed_both",
        signature_source: "manual_confirmation",
        contract_id: 91,
        signed_at: "2026-07-24T11:00:00Z",
        signed_by_name: "Tomasz TAC",
        can_confirm_signed: false,
        can_delete: false,
        can_edit: false,
      }),
    ]);

    const unsigned = await screen.findByText("Niepodpisana");
    const signed = screen.getByText("Podpisana obustronnie");
    expect(unsigned.closest("span")?.querySelector("svg")).not.toBeNull();
    expect(signed.closest("span")?.querySelector("svg")).not.toBeNull();
    expect(
      screen.getByRole("button", { name: "Oznacz jako podpisaną" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Kandydat/ })).toHaveAttribute(
      "href",
      "/candidates/7",
    );
    expect(screen.getByRole("link", { name: /Kontraktor/ })).toHaveAttribute(
      "href",
      "/contracts/91",
    );
  });

  it("blokuje potwierdzenie podczas pobierania rekrutacji i przy konflikcie klienta", async () => {
    let resolveJob:
      | ((value: {
          data: { title: string; client_id: number; client_name: string };
        }) => void)
      | undefined;
    mocks.apiGet.mockImplementation(
      (url: string) =>
        new Promise((resolve, reject) => {
          if (url === "/api/jobs/20") {
            resolveJob = resolve;
          } else {
            reject(new Error(`Unexpected GET ${url}`));
          }
        }),
    );
    renderTab([generatedRow()]);

    await userEvent.click(
      await screen.findByRole("button", { name: "Oznacz jako podpisaną" }),
    );
    const dialog = screen.getByRole("dialog");
    const confirm = within(dialog).getByRole("button", {
      name: "Potwierdź podpisanie",
    });
    expect(confirm).toBeDisabled();
    expect(within(dialog).getByText("Ładowanie…")).toBeInTheDocument();

    resolveJob?.({
      data: {
        title: "Cloud Engineer",
        client_id: 4,
        client_name: "Inny klient",
      },
    });

    expect(
      await within(dialog).findByText("Nie można potwierdzić klienta"),
    ).toBeInTheDocument();
    expect(confirm).toBeDisabled();
    expect(mocks.confirmFullySigned).not.toHaveBeenCalled();
  });

  it("po pierwszym generate aktualizuje ten sam draft przez zapamiętane contract_id", async () => {
    const memo = {
      key: null,
      contractId: null,
      pending: null,
    };
    const generate = vi.fn().mockResolvedValue({ contract_id: 91 });

    expect(
      await reuseOrGenerateContractId({
        key: "7:20",
        memo,
        generate,
      }),
    ).toBe(91);
    expect(
      await reuseOrGenerateContractId({
        key: "7:20",
        memo,
        generate,
      }),
    ).toBe(91);
    expect(generate).toHaveBeenNthCalledWith(1, null);
    expect(generate).toHaveBeenNthCalledWith(2, 91);
  });

  it("scala równoległe akcje dla tej samej rekrutacji do jednego /generate", async () => {
    let resolveGenerate:
      | ((value: { contract_id: number }) => void)
      | undefined;
    const generate = vi.fn(
      (_contractId: number | null) =>
        new Promise<{ contract_id: number }>((resolve) => {
          resolveGenerate = resolve;
        }),
    );
    const memo = {
      key: null,
      contractId: null,
      pending: null,
    };

    const first = reuseOrGenerateContractId({
      key: "7:20",
      memo,
      generate,
    });
    const second = reuseOrGenerateContractId({
      key: "7:20",
      memo,
      generate,
    });
    expect(generate).toHaveBeenCalledTimes(1);
    expect(generate).toHaveBeenCalledWith(null);

    resolveGenerate?.({ contract_id: 91 });
    await expect(Promise.all([first, second])).resolves.toEqual([91, 91]);
    expect(memo.contractId).toBe(91);
  });

  it("dla rekordu legacy wymaga wyboru kandydata i konkretnej rekrutacji", async () => {
    mocks.apiGet.mockImplementation((url: string) => {
      if (url === "/api/cv-generator/candidates") {
        return Promise.resolve({
          data: [
            {
              id: 7,
              name: "Jan",
              lastname: "Nowak",
              full_name: "Jan Nowak",
              email: "jan@example.com",
            },
          ],
        });
      }
      if (url === "/api/cv-generator/candidates/7/recruitments") {
        return Promise.resolve({
          data: [
            {
              stage_id: 12,
              job_id: 20,
              job_title: "Cloud Engineer",
              stage: "Screening",
            },
          ],
        });
      }
      if (url === "/api/jobs/20") {
        return Promise.resolve({
          data: {
            title: "Cloud Engineer",
            client_id: 3,
            client_name: "Nordea",
          },
        });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });
    mocks.confirmFullySigned.mockResolvedValue(confirmationResult("created"));
    renderTab([
      generatedRow({
        candidate_id: null,
        job_id: null,
        client_id: null,
        candidate_name: null,
        job_title: null,
        canonical_client_name: null,
        partner_name: "Historyczny Partner",
      }),
    ]);

    await userEvent.click(
      await screen.findByRole("button", { name: "Oznacz jako podpisaną" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText("To nie jest walidacja podpisu elektronicznego"),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/nie utworzy pliku.*QES/i)).toBeInTheDocument();

    const confirm = within(dialog).getByRole("button", {
      name: "Potwierdź podpisanie",
    });
    expect(confirm).toBeDisabled();

    const [candidateCombobox] = within(dialog).getAllByRole("combobox");
    await userEvent.click(candidateCombobox);
    await userEvent.click(await screen.findByText("Jan Nowak"));

    await waitFor(() =>
      expect(
        within(dialog).getAllByRole("combobox")[1],
      ).not.toBeDisabled(),
    );
    await userEvent.click(within(dialog).getAllByRole("combobox")[1]);
    await userEvent.click(
      await screen.findByText("Cloud Engineer · Screening"),
    );

    await waitFor(() => expect(confirm).toBeEnabled());
    await userEvent.click(confirm);
    await waitFor(() =>
      expect(mocks.confirmFullySigned).toHaveBeenCalledWith(1, {
        candidate_id: 7,
        job_id: 20,
      }),
    );
  });

  it.each([
    ["created", "Umowa podpisana — utworzono szkic kontraktora."],
    [
      "linked_existing",
      "Umowa podpisana — powiązano istniejącego kontraktora bez duplikatu.",
    ],
    [
      "already_processed",
      "Umowa była już przetworzona — nie utworzono duplikatu.",
    ],
  ] as const)(
    "obsługuje wynik %s i udostępnia przejście do kontraktora",
    async (outcome, expectedMessage) => {
      mocks.confirmFullySigned.mockResolvedValue(confirmationResult(outcome));
      renderTab([generatedRow()]);

      await userEvent.click(
        await screen.findByRole("button", { name: "Oznacz jako podpisaną" }),
      );
      expect(
        screen.getByText("To nie jest walidacja podpisu elektronicznego"),
      ).toBeInTheDocument();
      const confirmButton = screen.getByRole("button", {
        name: "Potwierdź podpisanie",
      });
      await waitFor(() => expect(confirmButton).toBeEnabled());
      await userEvent.click(confirmButton);

      await waitFor(() =>
        expect(mocks.showActionToast).toHaveBeenCalledWith(
          expectedMessage,
          expect.objectContaining({
            actionLabel: "Otwórz kontraktora",
          }),
        ),
      );
      const options = mocks.showActionToast.mock.calls[0]?.[1] as {
        onAction: () => void;
      };
      options.onAction();
      expect(mocks.push).toHaveBeenCalledWith("/contracts/91");
    },
  );

  it("pokazuje linki do konfliktujących kontraktów przy strukturalnym 409", async () => {
    mocks.confirmFullySigned.mockRejectedValue({
      response: {
        status: 409,
        data: {
          detail: {
            message: "Znaleziono kilka otwartych kontraktów.",
            contract_ids: [91, 92],
          },
        },
      },
    });
    renderTab([generatedRow()]);

    await userEvent.click(
      await screen.findByRole("button", { name: "Oznacz jako podpisaną" }),
    );
    const confirmButton = screen.getByRole("button", {
      name: "Potwierdź podpisanie",
    });
    await waitFor(() => expect(confirmButton).toBeEnabled());
    await userEvent.click(confirmButton);

    expect(
      await screen.findByText("Znaleziono kilka otwartych kontraktów."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Kontrakt #91/ })).toHaveAttribute(
      "href",
      "/contracts/91",
    );
    expect(screen.getByRole("link", { name: /Kontrakt #92/ })).toHaveAttribute(
      "href",
      "/contracts/92",
    );
    expect(mocks.showActionToast).toHaveBeenCalledWith(
      "Znaleziono kilka otwartych kontraktów.",
      expect.objectContaining({
        actionLabel: "Otwórz pierwszy kontrakt",
      }),
    );
  });
});
