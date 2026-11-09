/**
 * Kartoteka osoby → Płace: „Zmień” i „Anuluj” przy premii w profilu, te same
 * reguły co na ekranie miesiąca (`assignedBonusActions`). Profil ma wiersze
 * z wielu miesięcy i nie zna ich stanu: zamknięty miesiąc odmawia z serwera.
 * Dane fikcyjne.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BonusRow, PersonPayroll } from "@/lib/api/hr-payroll";
import { useAuthStore, type User } from "@/store/auth";

const mocks = vi.hoisted(() => ({
  payroll: null as unknown,
  cancelMutate: vi.fn(),
  updateMutate: vi.fn(),
  showToast: vi.fn(),
}));

vi.mock("@/lib/api/hr-payroll", async (original) => ({
  ...(await original<typeof import("@/lib/api/hr-payroll")>()),
  useBonusMode: () => ({ data: undefined }),
  usePersonPayroll: () => ({
    data: mocks.payroll,
    isLoading: false,
    isError: false,
    isSuccess: true,
    error: null,
    refetch: vi.fn(),
  }),
  useDeleteRate: () => ({ mutate: vi.fn(), isPending: false }),
  useCancelBonus: () => ({ mutate: mocks.cancelMutate, isPending: false }),
  useUpdateBonus: () => ({ mutate: mocks.updateMutate, isPending: false }),
  useCreateBonus: () => ({ mutate: vi.fn(), isPending: false }),
  useApproveBonus: () => ({ mutate: vi.fn(), isPending: false }),
  usePlacementOptions: () => ({ data: [] }),
}));
vi.mock("@/lib/api/hr", async (original) => ({
  ...(await original<typeof import("@/lib/api/hr")>()),
  usePeople: () => ({ data: { items: [] } }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: mocks.showToast }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: async () => true, confirmDialog: null }),
}));

import { PayrollProfileSection } from "../PayrollProfileSection";

const PERSON = 7;
const FINANCE = 1;
const BOSS = 5;

const bonus = (over: Partial<BonusRow> = {}): BonusRow =>
  ({
    id: 21,
    recipient_user_id: PERSON,
    recipient_name: "Ola Lis",
    proposed_by: FINANCE,
    amount: "1000.00",
    currency: "PLN",
    category: "custom",
    category_label: "Inna",
    period_year: 2026,
    period_month: 11,
    status: "assigned",
    source: "manual",
    contract_id: null,
    description: "Projekt Testowy",
    edited: false,
    can_approve: false,
    cancel_reason: null,
    flags: [],
    ...over,
  }) as BonusRow;

function renderAs(meId: number, scope: PersonPayroll["scope"], row: BonusRow) {
  useAuthStore.setState({ user: { id: meId } as User });
  mocks.payroll = {
    user_id: PERSON,
    scope,
    can_edit_rates: false,
    can_add_bonus: false,
    bonuses: [row],
    current_rate: null,
    rates: [],
  } satisfies PersonPayroll;
  render(<PayrollProfileSection userId={PERSON} name="Ola Lis" />);
}

const editButton = () => screen.queryByRole("button", { name: "Zmień" });
const cancelButton = () => screen.queryByRole("button", { name: "Anuluj" });

describe("PayrollProfileSection — akcje przy premii", () => {
  beforeEach(() => {
    mocks.cancelMutate.mockReset();
    mocks.updateMutate.mockReset();
    mocks.showToast.mockReset();
  });

  it("Płace przy przyznanej premii: Zmień i Anuluj", () => {
    renderAs(FINANCE, "full", bonus());
    expect(editButton()).not.toBeNull();
    expect(cancelButton()).not.toBeNull();
  });

  it("koordynator przy swojej przyznanej: samo Anuluj (decyzja 22.10.2026)", () => {
    renderAs(BOSS, "team", bonus({ proposed_by: BOSS }));
    expect(editButton()).toBeNull();
    expect(cancelButton()).not.toBeNull();
  });

  it("koordynator przy swojej propozycji: Zmień i Anuluj", () => {
    renderAs(BOSS, "team", bonus({ proposed_by: BOSS, status: "proposed" }));
    expect(editButton()).not.toBeNull();
    expect(cancelButton()).not.toBeNull();
  });

  it("koordynator przy cudzej premii: bez akcji", () => {
    renderAs(BOSS, "team", bonus({ proposed_by: FINANCE }));
    expect(editButton()).toBeNull();
    expect(cancelButton()).toBeNull();
  });

  it("własna premia, także u osoby z Płac: bez akcji", () => {
    renderAs(PERSON, "full", bonus());
    expect(editButton()).toBeNull();
    expect(cancelButton()).toBeNull();
  });

  it("premia anulowana ręcznie: wiersz zostaje, bez akcji", () => {
    renderAs(FINANCE, "full", bonus({ status: "cancelled", cancel_reason: "manual" }));
    expect(screen.getByText("Projekt Testowy")).toBeInTheDocument();
    expect(editButton()).toBeNull();
    expect(cancelButton()).toBeNull();
  });

  it("Zmień: Płace przenoszą premię na inny miesiąc", () => {
    renderAs(FINANCE, "full", bonus());
    fireEvent.click(editButton()!);
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Miesiąc wypłaty"), {
      target: { value: "2026-10" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz zmiany" }));
    expect(mocks.updateMutate).toHaveBeenCalledTimes(1);
    expect(mocks.updateMutate.mock.calls[0][0]).toMatchObject({
      id: 21,
      patch: { period_year: 2026, period_month: 10 },
    });
  });

  it("„Usuń premię” w oknie edycji prowadzi do usunięcia z powodem", () => {
    renderAs(FINANCE, "full", bonus());
    fireEvent.click(editButton()!);
    fireEvent.click(screen.getByRole("button", { name: "Usuń premię" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Powód");
  });

  it("Anuluj: po potwierdzeniu anuluje tę premię", async () => {
    renderAs(FINANCE, "full", bonus());
    fireEvent.click(cancelButton()!);
    await vi.waitFor(() => expect(mocks.cancelMutate).toHaveBeenCalledTimes(1));
    expect(mocks.cancelMutate.mock.calls[0][0]).toEqual({ id: 21 });
  });

  it("zamknięty miesiąc: odmowa serwera wraca jako komunikat", async () => {
    const detail = "Październik 2026 jest zamknięty.";
    mocks.cancelMutate.mockImplementation((_vars, options) =>
      options.onError({ isAxiosError: true, response: { status: 409, data: { detail } } }),
    );
    renderAs(FINANCE, "full", bonus());
    fireEvent.click(cancelButton()!);
    await vi.waitFor(() => expect(mocks.showToast).toHaveBeenCalledWith(detail, "error"));
  });
});
