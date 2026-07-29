import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { B2BGeneratedContractRow } from "@/lib/api";

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
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  b2bGeneratorApi: {
    generated: (...args: unknown[]) => mocks.generated(...args),
    confirmFullySigned: (...args: unknown[]) =>
      mocks.confirmFullySigned(...args),
    updateGenerated: (...args: unknown[]) => mocks.updateGenerated(...args),
    deleteGenerated: (...args: unknown[]) => mocks.deleteGenerated(...args),
    downloadGenerated: (...args: unknown[]) => mocks.downloadGenerated(...args),
  },
  extractErrorMsg: (error: unknown) =>
    error instanceof Error ? error.message : "Błąd",
  signingApi: {},
}));

import { GeneratedContractsTab } from "@/components/v2/pages/B2BContractGeneratorV2";

beforeAll(() => {
  // Radix Select potrzebuje tych API, których jsdom nie implementuje.
  for (const [name, value] of [
    ["hasPointerCapture", () => false],
    ["setPointerCapture", () => undefined],
    ["releasePointerCapture", () => undefined],
    ["scrollIntoView", () => undefined],
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
    client_name: "Nordea Bank",
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
    candidate_id: null,
    job_id: null,
    client_id: null,
    contract_id: null,
    candidate_name: null,
    job_title: null,
    canonical_client_name: null,
    signed_at: null,
    signed_by_name: null,
    can_confirm_signed: false,
    blocked_reason: null,
    can_delete: true,
    can_edit: true,
    can_download: false,
    ...overrides,
  };
}

function renderTab(rows: B2BGeneratedContractRow[]) {
  mocks.generated.mockResolvedValue(rows);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <GeneratedContractsTab />
    </QueryClientProvider>,
  );
}

/**
 * `delay: null` wyłącza sztuczną pauzę między klawiszami. Domyślne opóźnienie
 * przy pełnym przebiegu suite'a (85 plików równolegle) potrafi przekroczyć
 * 5-sekundowy timeout i zamienić te testy w migoczące.
 */
const setupUser = () => userEvent.setup({ delay: null });

/** Wybierz opcję w Radix Select otwartym przez trigger o danej etykiecie. */
async function pickOption(
  user: ReturnType<typeof userEvent.setup>,
  triggerName: RegExp | string,
  optionName: RegExp | string,
) {
  await user.click(screen.getByRole("combobox", { name: triggerName }));
  await user.click(await screen.findByRole("option", { name: optionName }));
}

/**
 * `<input type="date">` ustawiamy jednym `change`, a nie 10 znakami przez
 * `user.type` — każdy znak to osobny re-render, a jsdom i tak nie odtwarza
 * natywnego parsowania segmentów daty.
 */
function setDate(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("GeneratedContractsTab — status umowy", () => {
  it("nowa umowa jest domyślnie Aktywna", async () => {
    renderTab([generatedRow()]);
    expect(await screen.findByText("Aktywna")).toBeInTheDocument();
    expect(screen.queryByText("Zamknięta")).not.toBeInTheDocument();
  });

  it("pokazuje powód i datę zakończenia zamkniętej umowy", async () => {
    renderTab([
      generatedRow({
        contract_status: "closed",
        closure_reason: "termination",
        closure_date: "2026-08-31",
      }),
    ]);

    expect(await screen.findByText("Zamknięta")).toBeInTheDocument();
    expect(screen.getByText(/Wypowiedzenie · 2026-08-31/)).toBeInTheDocument();
  });

  it("dla powodu „Inne” pokazuje własny tekst, nie etykietę katalogową", async () => {
    renderTab([
      generatedRow({
        contract_status: "closed",
        closure_reason: "other",
        closure_reason_other: "Zmiana modelu współpracy",
        closure_date: "2026-09-01",
      }),
    ]);

    expect(
      await screen.findByText(/Zmiana modelu współpracy/),
    ).toBeInTheDocument();
  });

  it("„Zamknięta” odsłania powód i datę, i wysyła komplet pól", async () => {
    const user = setupUser();
    mocks.updateGenerated.mockResolvedValue(
      generatedRow({ contract_status: "closed" }),
    );
    renderTab([generatedRow()]);

    await user.click(
      await screen.findByRole("button", { name: /Zmień status/ }),
    );
    // Póki umowa jest Aktywna, pola zamknięcia nie istnieją.
    expect(screen.queryByLabelText("Data zakończenia umowy")).toBeNull();

    await pickOption(user, /Status umowy/, "Zamknięta");
    await pickOption(user, /Powód zamknięcia umowy/, "Wypowiedzenie");
    setDate("Data zakończenia umowy", "2026-08-31");
    await user.click(screen.getByRole("button", { name: /Zapisz status/ }));

    await waitFor(() =>
      expect(mocks.updateGenerated).toHaveBeenCalledWith(1, {
        contract_status: "closed",
        closure_reason: "termination",
        closure_reason_other: null,
        closure_date: "2026-08-31",
      }),
    );
  });

  it("wybór „Inne” dokłada pole na własny powód", async () => {
    const user = setupUser();
    mocks.updateGenerated.mockResolvedValue(
      generatedRow({ contract_status: "closed" }),
    );
    renderTab([generatedRow()]);

    await user.click(
      await screen.findByRole("button", { name: /Zmień status/ }),
    );
    await pickOption(user, /Status umowy/, "Zamknięta");
    expect(screen.queryByLabelText("Własny powód")).toBeNull();

    await pickOption(user, /Powód zamknięcia umowy/, "Inne");
    fireEvent.change(screen.getByLabelText("Własny powód"), {
      target: { value: "Zmiana modelu współpracy" },
    });
    setDate("Data zakończenia umowy", "2026-09-01");
    await user.click(screen.getByRole("button", { name: /Zapisz status/ }));

    await waitFor(() =>
      expect(mocks.updateGenerated).toHaveBeenCalledWith(1, {
        contract_status: "closed",
        closure_reason: "other",
        closure_reason_other: "Zmiana modelu współpracy",
        closure_date: "2026-09-01",
      }),
    );
  });

  it("nie zapisuje „Zamkniętej” bez daty zakończenia", async () => {
    const user = setupUser();
    renderTab([generatedRow()]);

    await user.click(
      await screen.findByRole("button", { name: /Zmień status/ }),
    );
    await pickOption(user, /Status umowy/, "Zamknięta");
    await pickOption(user, /Powód zamknięcia umowy/, "Wypowiedzenie");
    await user.click(screen.getByRole("button", { name: /Zapisz status/ }));

    expect(mocks.updateGenerated).not.toHaveBeenCalled();
    expect(mocks.showError).toHaveBeenCalledWith(
      "Podaj datę zakończenia umowy.",
    );
  });

  it("powrót na „Aktywna” czyści pola zamknięcia", async () => {
    const user = setupUser();
    mocks.updateGenerated.mockResolvedValue(generatedRow());
    renderTab([
      generatedRow({
        contract_status: "closed",
        closure_reason: "termination",
        closure_date: "2026-08-31",
      }),
    ]);

    await user.click(
      await screen.findByRole("button", { name: /Zmień status/ }),
    );
    await pickOption(user, /Status umowy/, "Aktywna");
    await user.click(screen.getByRole("button", { name: /Zapisz status/ }));

    await waitFor(() =>
      expect(mocks.updateGenerated).toHaveBeenCalledWith(1, {
        contract_status: "active",
      }),
    );
  });

  it("bez uprawnień nie pokazuje przycisku zmiany statusu", async () => {
    renderTab([generatedRow({ can_change_status: false })]);
    expect(await screen.findByText("Aktywna")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zmień status/ })).toBeNull();
  });
});

describe("GeneratedContractsTab — wyszukiwarka", () => {
  it("wysyła frazę na backend, a nie filtruje pobranej strony", async () => {
    const user = setupUser();
    renderTab([generatedRow()]);
    await screen.findByText("1471/2026");

    await user.type(
      screen.getByLabelText("Szukaj wygenerowanych umów"),
      "Kowalski",
    );

    await waitFor(
      () =>
        expect(mocks.generated).toHaveBeenCalledWith(100, {
          q: "Kowalski",
          contractStatus: undefined,
        }),
      { timeout: 2000 },
    );
  });

  it("filtr statusu trafia do zapytania", async () => {
    const user = setupUser();
    renderTab([generatedRow()]);
    await screen.findByText("1471/2026");

    await pickOption(user, /Filtr statusu umowy/, "Zamknięta");

    await waitFor(() =>
      expect(mocks.generated).toHaveBeenCalledWith(100, {
        q: "",
        contractStatus: "closed",
      }),
    );
  });

  it("pusty wynik wyszukiwania nie udaje braku umów w systemie", async () => {
    const user = setupUser();
    renderTab([generatedRow()]);
    await screen.findByText("1471/2026");

    mocks.generated.mockResolvedValue([]);
    await user.type(
      screen.getByLabelText("Szukaj wygenerowanych umów"),
      "nieistniejaca",
    );

    expect(
      await screen.findByText(
        "Brak umów pasujących do wyszukiwania.",
        {},
        { timeout: 2000 },
      ),
    ).toBeInTheDocument();
  });
});
