/**
 * Kafelek „Szczegóły administracyjne” kontraktu (06.11.2026): widzą go Płace
 * i osoby z oznaczaniem podpisu, zmiana wymaga powodu, „Tak” przy replacement
 * wymaga osoby, a zapis wysyła komplet pól.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  config: { me: { payroll: true }, open_modules: { payroll: true } } as {
    me: { payroll: boolean };
    open_modules: { payroll: boolean };
  },
  details: {
    contract_id: 687,
    candidate_id: 1001,
    client_id: 39,
    is_replacement: false,
    replaced_contract_id: null,
    replaced: null,
    is_client_referral: null,
  } as Record<string, unknown>,
  isError: false,
  mutate: vi.fn(),
  permissions: new Set<string>(),
}));

vi.mock("@/lib/api/hr", () => ({
  useHrConfig: () => ({ data: mocks.config }),
}));
vi.mock("@/lib/api/hr-payroll", () => ({
  useContractAdminDetails: (_id: number, enabled: boolean) =>
    enabled
      ? mocks.isError
        ? { isError: true, isSuccess: false }
        : { isError: false, isSuccess: true, data: mocks.details }
      : { isError: false, isSuccess: false },
  useSaveContractAdminDetails: () => ({ mutate: mocks.mutate, isPending: false }),
}));
vi.mock("@/lib/permissions", () => ({
  hasPermission: (_user: unknown, permission: string) =>
    mocks.permissions.has(permission),
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (select: (s: { user: null }) => unknown) => select({ user: null }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock("@/components/v2/b2b-generator/AgreementAdminDetailsCard", () => ({
  ReplacedPicker: ({
    onChange,
  }: {
    onChange: (v: Record<string, unknown>) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        onChange({ contract_id: 497, name: "Zofia Przykładowa", status: "ended" })
      }
    >
      Wybierz osobę
    </button>
  ),
}));

import { ContractAdminDetailsCard } from "../ContractAdminDetailsCard";

function renderCard() {
  return render(<ContractAdminDetailsCard contractId={687} clientName="Klient Testowy" />);
}

describe("ContractAdminDetailsCard", () => {
  beforeEach(() => {
    mocks.config = { me: { payroll: true }, open_modules: { payroll: true } };
    mocks.isError = false;
    mocks.mutate.mockReset();
    mocks.permissions = new Set();
    mocks.details = {
      contract_id: 687,
      candidate_id: 1001,
      client_id: 39,
      is_replacement: false,
      replaced_contract_id: null,
      replaced: null,
      is_client_referral: null,
    };
  });

  it("bez Płac i bez oznaczania podpisu kafelka nie ma", () => {
    mocks.config = { me: { payroll: false }, open_modules: { payroll: true } };
    const { container } = renderCard();
    expect(container).toBeEmptyDOMElement();
  });

  it("oznaczający podpis widzi kafelek bez Płac", () => {
    mocks.config = { me: { payroll: false }, open_modules: { payroll: true } };
    mocks.permissions = new Set(["b2b_signature_confirmation"]);
    renderCard();
    expect(screen.getByRole("region", { name: "Szczegóły administracyjne" })).toBeInTheDocument();
    expect(screen.getByText("nie zapisano")).toBeInTheDocument();
  });

  it("awaria zapytania to komunikat, nie pusty kafelek", () => {
    mocks.isError = true;
    renderCard();
    expect(screen.getByRole("alert")).toHaveTextContent(/Nie udało się wczytać/);
  });

  it("zapis wymaga powodu i osoby przy replacement", () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: "Zmień" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(
      within(within(dialog).getByRole("group", { name: "Replacement / gwarancja" })).getByRole(
        "button",
        { name: "Tak" },
      ),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    expect(mocks.mutate).not.toHaveBeenCalled();
    expect(within(dialog).getByText("Wskaż osobę, którą zastępuje.")).toBeInTheDocument();
    expect(within(dialog).getByText("Podaj powód zmiany.")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Wybierz osobę" }));
    fireEvent.click(
      within(
        within(dialog).getByRole("group", { name: "Kandydat wskazany przez klienta" }),
      ).getByRole("button", { name: "Tak" }),
    );
    fireEvent.change(within(dialog).getByLabelText("Powód zmiany"), {
      target: { value: "  potwierdzone przez Delivery  " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    expect(mocks.mutate).toHaveBeenCalledWith(
      {
        is_replacement: true,
        replaced_contract_id: 497,
        is_client_referral: true,
        reason: "potwierdzone przez Delivery",
      },
      expect.anything(),
    );
  });

  it("pokazuje, za kogo jest zastępstwo i brak premii za kandydata od klienta", () => {
    mocks.details = {
      ...mocks.details,
      is_replacement: true,
      replaced_contract_id: 497,
      replaced: { contract_id: 497, name: "Zofia Przykładowa", status: "ended" },
      is_client_referral: true,
    };
    renderCard();
    expect(screen.getByText(/za Zofia Przykładowa \(kontrakt #497\)/)).toBeInTheDocument();
    expect(screen.getByText(/bez premii z placementu/)).toBeInTheDocument();
  });
});
