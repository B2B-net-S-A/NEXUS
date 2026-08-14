/**
 * Zakładki „Umowy bez projektu" i „Zakończone umowy".
 *
 * Sedno: wiersz jest w JEDNEJ zakładce naraz — o tym decyduje filtr statusu
 * wysyłany na serwer, nie filtrowanie pobranych wierszy w przeglądarce. Test
 * pilnuje tego kontraktu oraz tego, że awaria zapytania NIE renderuje się jako
 * pusta lista („brak umów" czyta się jak fakt o świecie, nie jak błąd sieci).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { B2BGeneratedContractRow } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  generated: vi.fn(),
  updateGenerated: vi.fn(),
  statusHistory: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

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
    showActionToast: vi.fn(),
    showSuccess: mocks.showSuccess,
    showError: mocks.showError,
  }),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  b2bGeneratorApi: {
    generated: (...args: unknown[]) => mocks.generated(...args),
    updateGenerated: (...args: unknown[]) => mocks.updateGenerated(...args),
    statusHistory: (...args: unknown[]) => mocks.statusHistory(...args),
    confirmFullySigned: vi.fn(),
    deleteGenerated: vi.fn(),
    downloadGenerated: vi.fn(),
  },
  extractErrorMsg: (error: unknown) =>
    error instanceof Error ? error.message : "Błąd",
  signingApi: {},
}));

import {
  ClosedContractsTab,
  NoProjectContractsTab,
} from "@/components/v2/pages/B2BContractGeneratorV2";

beforeAll(() => {
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

beforeEach(() => {
  vi.clearAllMocks();
});

function row(
  overrides: Partial<B2BGeneratedContractRow> = {},
): B2BGeneratedContractRow {
  return {
    id: 1,
    contract_number: "1471/2026",
    partner_name: "Jan Kowalski",
    partner_display_name: "JK Software Jan Kowalski",
    partner_secondary_line: null,
    partner_nip: "1234563218",
    start_date: "2026-01-15",
    client_name: "Nordea Bank",
    language: "pl",
    signing_date: null,
    created_at: "2026-01-10T10:30:00Z",
    created_by_name: "Marta Rekruter",
    signature_status: "signed_both",
    signature_source: null,
    contract_status: "suspended",
    closure_reason: "no_client_budget",
    closure_reason_other: null,
    closure_date: "2026-08-01",
    can_change_status: true,
    candidate_id: 5,
    job_id: null,
    client_id: 3,
    contract_id: 9,
    candidate_name: "Jan Kowalski",
    job_title: null,
    canonical_client_name: "Nordea Bank",
    signed_at: null,
    signed_by_name: null,
    can_confirm_signed: false,
    blocked_reason: null,
    can_delete: false,
    can_edit: false,
    can_download: true,
    ...overrides,
  };
}

function renderTab(
  Tab: React.ComponentType,
  rows: B2BGeneratedContractRow[] | Error,
) {
  if (rows instanceof Error) mocks.generated.mockRejectedValue(rows);
  else mocks.generated.mockResolvedValue(rows);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <Tab />
    </QueryClientProvider>,
  );
}

const setupUser = () => userEvent.setup({ delay: null });

describe("Umowy bez projektu", () => {
  it("pyta serwer wyłącznie o umowy zawieszone", async () => {
    renderTab(NoProjectContractsTab, [row()]);
    await screen.findByText("1471/2026");

    expect(mocks.generated).toHaveBeenCalledWith(100, {
      q: "",
      contractStatus: ["suspended"],
      closureReason: undefined,
      startFrom: undefined,
      startTo: undefined,
    });
  });

  it("ma komplet kolumn z ticketu, z datą ZAKOŃCZENIA PROJEKTU", async () => {
    renderTab(NoProjectContractsTab, [row()]);
    await screen.findByText("1471/2026");

    const headers = Array.from(document.querySelectorAll("th")).map((th) =>
      (th.textContent ?? "").trim(),
    );
    expect(headers).toEqual([
      "Numer umowy",
      "Partner",
      "NIP",
      "Data rozpoczęcia",
      "Data zakończenia projektu",
      "Klient",
      "Status umowy",
      "Powód zakończenia projektu",
      "Akcje",
    ]);
  });

  it("pokazuje status, datę i powód zakończenia projektu", async () => {
    renderTab(NoProjectContractsTab, [row()]);

    expect(await screen.findByText("Zawieszona")).toBeInTheDocument();
    expect(screen.getByText("2026-08-01")).toBeInTheDocument();
    expect(screen.getByText("Brak budżetu u klienta")).toBeInTheDocument();
  });

  it("przywrócenie wysyła projekt, a klient jest tylko do odczytu", async () => {
    const user = setupUser();
    mocks.apiGet.mockImplementation((url: string) => {
      if (url.includes("/recruitments")) {
        return Promise.resolve({
          data: [
            {
              stage_id: 11,
              job_id: 42,
              job_title: "Nowy projekt",
              stage: "hired",
            },
          ],
        });
      }
      return Promise.resolve({
        data: { id: 42, title: "Nowy projekt", client_name: "Klient docelowy" },
      });
    });
    mocks.updateGenerated.mockResolvedValue(row({ contract_status: "active" }));
    renderTab(NoProjectContractsTab, [row()]);

    await user.click(await screen.findByRole("button", { name: /Przywróć/ }));
    await user.click(
      await screen.findByRole("combobox", { name: /^Projekt$/ }),
    );
    await user.click(await screen.findByRole("option", { name: "Nowy projekt" }));

    // Klient dociąga się z projektu i nie da się go nadpisać ręcznie.
    const clientField = (await screen.findByLabelText(
      "Klient",
    )) as HTMLInputElement;
    await waitFor(() => expect(clientField.value).toBe("Klient docelowy"));
    expect(clientField).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /Przywróć umowę/ }));
    await waitFor(() =>
      expect(mocks.updateGenerated).toHaveBeenCalledWith(1, {
        contract_status: "active",
        job_id: 42,
      }),
    );
  });

  it("nie da się zapisać przywrócenia bez wybranego projektu", async () => {
    const user = setupUser();
    mocks.apiGet.mockResolvedValue({ data: [] });
    renderTab(NoProjectContractsTab, [row()]);

    await user.click(await screen.findByRole("button", { name: /Przywróć/ }));
    expect(
      await screen.findByRole("button", { name: /Przywróć umowę/ }),
    ).toBeDisabled();
  });

  it("padnięta lista projektów NIE udaje braku projektów", async () => {
    // Projekt jest polem obowiązkowym: „brak projektów" zostawiłby użytkownika
    // z zablokowanym przyciskiem i zerową wskazówką, co poszło nie tak.
    const user = setupUser();
    mocks.apiGet.mockRejectedValue(new Error("Network Error"));
    renderTab(NoProjectContractsTab, [row()]);

    await user.click(await screen.findByRole("button", { name: /Przywróć/ }));
    expect(
      await screen.findByText("Nie udało się wczytać listy projektów"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Kandydat nie jest w żadnej rekrutacji."),
    ).toBeNull();
  });

  it("awaria listy umów NIE renderuje się jako pusta zakładka", async () => {
    renderTab(NoProjectContractsTab, new Error("Network Error"));

    expect(
      await screen.findByText("Nie udało się wczytać listy"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Brak umów bez przypisanego projektu."),
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Ponów" })).toBeInTheDocument();
  });

  it("pustka po filtrze ma inny komunikat niż brak umów", async () => {
    const user = setupUser();
    renderTab(NoProjectContractsTab, []);
    expect(
      await screen.findByText("Brak umów bez przypisanego projektu."),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText(/Szukaj/), "Kowalski");
    expect(
      await screen.findByText("Brak umów pasujących do wyszukiwania."),
    ).toBeInTheDocument();
  });
});

describe("Zakończone umowy", () => {
  it("pyta serwer wyłącznie o umowy zakończone i nie daje akcji", async () => {
    renderTab(ClosedContractsTab, [
      row({
        contract_status: "closed",
        closure_reason: "project_completed",
        closure_date: "2026-09-30",
      }),
    ]);
    await screen.findByText("1471/2026");

    expect(mocks.generated).toHaveBeenCalledWith(
      100,
      expect.objectContaining({ contractStatus: ["closed"] }),
    );
    const headers = Array.from(document.querySelectorAll("th")).map((th) =>
      (th.textContent ?? "").trim(),
    );
    expect(headers).toEqual([
      "Numer umowy",
      "Partner",
      "NIP",
      "Data rozpoczęcia",
      "Data zakończenia umowy",
      "Klient",
      "Status umowy",
      "Powód zakończenia projektu",
    ]);
    expect(screen.queryByRole("button", { name: /Przywróć/ })).toBeNull();
  });

  it("powód sprzed migracji 0226 ma etykietę, nie surowy klucz", async () => {
    renderTab(ClosedContractsTab, [
      row({ contract_status: "closed", closure_reason: "termination" }),
    ]);
    expect(await screen.findByText("Wypowiedzenie")).toBeInTheDocument();
  });

  it("„Inny” pokazuje własny tekst zamiast etykiety katalogowej", async () => {
    renderTab(ClosedContractsTab, [
      row({
        contract_status: "closed",
        closure_reason: "other",
        closure_reason_other: "Zmiana modelu współpracy",
      }),
    ]);
    expect(
      await screen.findByText("Zmiana modelu współpracy"),
    ).toBeInTheDocument();
  });
});
