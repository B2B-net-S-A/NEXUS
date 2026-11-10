import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BonusDecisions, BonusRow } from "@/lib/api/hr-payroll";

import { BonusDecisionsTopbarButton } from "../BonusDecisionsTopbarButton";

// Dane fikcyjne. Menu renderuje się od razu, bez otwierania rozwijanej listy.
const state: { decisions: BonusDecisions; manualAllowed: boolean } = {
  decisions: { signed: [], league: [], check: [], vouchers: [] },
  manualAllowed: true,
};

vi.mock("@/lib/api/hr-payroll", async (original) => ({
  ...(await original<typeof import("@/lib/api/hr-payroll")>()),
  useBonusDecisions: () => ({ isSuccess: true, data: state.decisions }),
  useBonusMode: () => ({
    data: { automatic: Boolean(state.decisions.automatic), manual_allowed: state.manualAllowed },
  }),
  useApproveBonus: () => ({ mutate: vi.fn(), isPending: false }),
  useConfirmVoucher: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/api/hr", () => ({
  useHrConfig: () => ({ data: { me: { payroll: true }, open_modules: { payroll: true } } }),
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (pick: (s: unknown) => unknown) => pick({ user: { role: "admin", roles: ["admin"] } }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const row = (over: Partial<BonusRow>): BonusRow =>
  ({
    id: 1,
    recipient_user_id: 5,
    recipient_name: "Jan Bąk",
    amount: "1000.00",
    currency: "PLN",
    category: "recruiter",
    category_label: "Rekruter",
    period_year: 2026,
    period_month: 11,
    status: "proposed",
    source: "contract_placement",
    description: "Premia rekrutera — placement: Anna Nowak (Firma)",
    edited: false,
    can_approve: true,
    flags: [],
    ...over,
  }) as BonusRow;

const held = row({
  id: 2,
  description: "Premia DL — placement: Piotr Kos (Firma)",
  flags: [{ code: "no_order", label: "Brak zamówienia", detail: "" }],
});

beforeEach(() => {
  state.manualAllowed = true;
  state.decisions = { signed: [row({})], league: [], check: [held], vouchers: [] };
});

describe("Ikona „Premie do decyzji”", () => {
  it("bez automatu: zatwierdzanie i grupa do sprawdzenia jak dotąd", () => {
    render(<BonusDecisionsTopbarButton />);
    expect(screen.getByRole("button", { name: "Premie do decyzji: 2 pozycje" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zatwierdź" })).toBeInTheDocument();
    expect(screen.getByText(/Do sprawdzenia · 1/)).toBeInTheDocument();
    expect(screen.queryByText(/Czeka na termin/)).not.toBeInTheDocument();
  });

  it("przy automacie admin widzi tylko zatrzymane i liczbę premii przed terminem", () => {
    state.decisions = { signed: [], league: [], check: [held], vouchers: [], automatic: true, scheduled: 19 };
    render(<BonusDecisionsTopbarButton />);
    expect(screen.getByRole("button", { name: "Premie do decyzji: 1 pozycja" })).toBeInTheDocument();
    expect(screen.getByText(/Automat zatrzymał · 1/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zatwierdź" })).not.toBeInTheDocument();
    expect(screen.getByText(/Czeka na termin: 19 premii/)).toBeInTheDocument();
  });

  it("przy automacie ikony nie ma dla Płac bez prawa ręcznej zmiany", () => {
    state.manualAllowed = false;
    state.decisions = { signed: [], league: [], check: [held], vouchers: [], automatic: true, scheduled: 3 };
    const { container } = render(<BonusDecisionsTopbarButton />);
    expect(container).toBeEmptyDOMElement();
  });

  it("przy automacie bez zatrzymanych premii ikony nie ma", () => {
    state.decisions = { signed: [], league: [], check: [], vouchers: [], automatic: true, scheduled: 19 };
    const { container } = render(<BonusDecisionsTopbarButton />);
    expect(container).toBeEmptyDOMElement();
  });
});
