import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ReverseTerminationPlanView } from "@/components/contracts/ContractTerminationRecovery";
import { contractActivityLabel } from "@/components/contracts/contract-timeline-labels";
import type { ContractTerminationReversalPlan } from "@/lib/api";
import { canRecoverContractTermination } from "@/store/auth";

const plan = (
  overrides: Partial<ContractTerminationReversalPlan> = {},
): ContractTerminationReversalPlan => ({
  contract_id: 408,
  source: "history",
  terminated_on: "2026-08-31",
  contract: {
    status_now: "active",
    status_target: "active",
    end_date_now: null,
    end_date_target: null,
    clears_termination: true,
  },
  orders: [
    {
      order_id: 679,
      order_group_id: 96,
      order_label: "CeZ/242/2025",
      kind: "group",
      consultant: "Jan Testowy",
      status_now: "completed",
      status_target: "active",
      end_date_now: "2026-08-31",
      end_date_target: null,
      end_date_source: "history",
      removes_decision_case: true,
    },
  ],
  skipped: [],
  blockers: [],
  md_imports: [],
  decision_cases_removed: 1,
  executed: false,
  ...overrides,
});

describe("Cofnij zakończenie — okno potwierdzenia", () => {
  it("pokazuje zamówienia i zmiany, które zostaną przywrócone", () => {
    render(<ReverseTerminationPlanView plan={plan()} />);
    expect(screen.getByText(/CeZ\/242\/2025 · Jan Testowy/)).toBeInTheDocument();
    expect(screen.getByText(/Zakończone → Aktywne/)).toBeInTheDocument();
    expect(screen.getByText(/31\.08\.2026 → bezterminowo/)).toBeInTheDocument();
    expect(screen.getByText(/z historii zmian/)).toBeInTheDocument();
    expect(
      screen.getByText(/Znika „Wymagana decyzja o pozostałej puli MD”/),
    ).toBeInTheDocument();
    expect(screen.getByText(/stawki zostają bez zmian/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("blokada wskazuje zamówienie i decyzję", () => {
    render(
      <ReverseTerminationPlanView
        plan={plan({
          blockers: [
            {
              code: "md_pool_decided",
              order_label: "CeZ/242/2025",
              decision: "transfer",
              message:
                "Na zamówieniu CeZ/242/2025 podjęto już decyzję o pozostałej puli MD: przekazanie puli MD innemu konsultantowi.",
            },
          ],
        })}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Cofnięcie jest zablokowane");
    expect(alert).toHaveTextContent("CeZ/242/2025");
    expect(alert).toHaveTextContent("przekazanie puli MD");
  });

  it("wymienia importy MD do przeliczenia", () => {
    render(
      <ReverseTerminationPlanView
        plan={plan({
          md_imports: [
            {
              import_id: 5,
              row_id: 77,
              period_month: "2026-09",
              filename: "raport-wrzesien.xlsx",
              md_reported: "19",
              order_id: 679,
              order_label: "CeZ/242/2025",
              skipped: null,
            },
          ],
        })}
      />,
    );
    expect(screen.getByText(/Importy MD do przeliczenia/)).toBeInTheDocument();
    expect(screen.getByText(/2026-09 · raport-wrzesien\.xlsx · 19 MD/)).toBeInTheDocument();
  });
});

describe("kto przywraca zakończony kontrakt", () => {
  it("Admin, Finanse i TCM z odczytem Delivery", () => {
    for (const role of ["admin", "finance", "talent_community_manager"] as const) {
      expect(
        canRecoverContractTermination({
          role,
          effective_section_access: { delivery: "read" },
        }),
      ).toBe(true);
    }
  });

  it("Delivery Lead i rekruter — nie; brak sekcji Delivery — nie", () => {
    expect(
      canRecoverContractTermination({
        role: "delivery_lead",
        effective_section_access: { delivery: "write" },
      }),
    ).toBe(false);
    expect(
      canRecoverContractTermination({
        role: "recruiter",
        effective_section_access: { delivery: "read" },
      }),
    ).toBe(false);
    expect(
      canRecoverContractTermination({
        role: "finance",
        effective_section_access: { delivery: "none" },
      }),
    ).toBe(false);
  });
});

describe("historia kontraktu", () => {
  it("nazywa obie akcje po polsku", () => {
    expect(contractActivityLabel("termination_reversed")).toBe(
      "Cofnięto zakończenie (pomyłka)",
    );
    expect(contractActivityLabel("return_after_break")).toBe(
      "Powrót po przerwie – utworzono nowy kontrakt",
    );
  });
});
