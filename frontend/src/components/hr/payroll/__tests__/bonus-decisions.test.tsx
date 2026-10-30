import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BonusRow } from "@/lib/api/hr-payroll";

import { bonusCalculation } from "../BonusDialog";
import { DecisionPanel } from "../PayrollCloseParts";

vi.mock("@/lib/api/hr-payroll", async (original) => ({
  ...(await original<typeof import("@/lib/api/hr-payroll")>()),
  useApproveBonuses: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: async () => true, confirmDialog: null }),
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

const flagged = row({
  id: 2,
  recipient_name: "Ola Lis",
  description: "Premia rekrutera — placement: Piotr Kos (Firma)",
  flags: [{ code: "inactive", label: "Konto nieaktywne", detail: "Ta osoba nie ma konta." }],
});

function renderPanel(overrides: Partial<Parameters<typeof DecisionPanel>[0]> = {}) {
  const onEdit = vi.fn();
  render(
    <DecisionPanel
      rows={[row({}), flagged]}
      meId={9}
      open
      canCreate
      onCreate={vi.fn()}
      onApprove={vi.fn()}
      onEdit={onEdit}
      onCancel={vi.fn()}
      approving={false}
      {...overrides}
    />,
  );
  return { onEdit };
}

describe("Premie do decyzji: lista", () => {
  beforeEach(() => vi.clearAllMocks());

  it("najpierw do sprawdzenia, a oznaczony wiersz nie jest domyślnie zaznaczony", () => {
    renderPanel();
    expect(screen.getByText("Do sprawdzenia: 1")).toBeInTheDocument();
    expect(screen.getByText("Bez uwag: 1")).toBeInTheDocument();
    expect(screen.getByLabelText(/Zaznacz: .*Ola Lis/)).toHaveAttribute("data-state", "unchecked");
    expect(screen.getByLabelText(/Zaznacz: .*Jan Bąk/)).toHaveAttribute("data-state", "checked");
  });

  it("klik w wiersz otwiera okno, klik w pole wyboru nie", () => {
    const { onEdit } = renderPanel();
    fireEvent.click(screen.getByText("Jan Bąk"));
    expect(onEdit).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByLabelText(/Zaznacz: .*Jan Bąk/));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it("własnej premii nie da się otworzyć ani zaznaczyć", () => {
    const { onEdit } = renderPanel({ meId: 5 });
    fireEvent.click(screen.getByText("Jan Bąk"));
    expect(onEdit).not.toHaveBeenCalled();
    expect(screen.queryByLabelText(/Zaznacz: .*Jan Bąk/)).not.toBeInTheDocument();
  });

  it("zakładki: później i bez stawki z linkiem do kontraktu", () => {
    renderPanel({
      later: [row({ id: 3, recipient_name: "Ewa Kowal", period_month: 12 })],
      missingRates: [
        {
          contract_id: 44,
          candidate: "Anna Nowak",
          client: "Firma",
          start_date: "2026-11-09",
          recruiter_name: null,
          dl_name: "Ola Lis",
        },
      ],
    });
    fireEvent.click(screen.getByRole("tab", { name: "Później 1" }));
    expect(screen.getByText("Ewa Kowal")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Bez stawki 1" }));
    const link = screen.getByRole("link", { name: "Uzupełnij stawki" });
    expect(link).toHaveAttribute("href", "/contracts/44");
    expect(within(link.closest("li") as HTMLElement).getByText(/Rekruter brak/)).toBeInTheDocument();
  });
});

describe("Jak policzona premia", () => {
  it("rekruter z progu, system indywidualny i DL z godzinami osoby", () => {
    expect(bonusCalculation(row({ rule_snapshot: { margin_per_hour: "45.00", role: "recruiter", tier: 2 } }))).toBe(
      "Marża 45,00 zł/h, próg 2.",
    );
    expect(
      bonusCalculation(
        row({ rule_snapshot: { margin_per_hour: "43.00", individual_percent: "35", recruiter_starts: 3 } }),
      ),
    ).toBe("Marża 43,00 zł/h, 35% marży miesięcznej (starty w miesiącu: 3).");
    expect(
      bonusCalculation(row({ rule_snapshot: { margin_per_hour: "40.50", role: "dl", dl_percent: "10", dl_hours: 160 } })),
    ).toBe("10% × 40,50 zł/h × 160 h.");
    expect(bonusCalculation(row({ rule_snapshot: {} }))).toBeNull();
  });
});
