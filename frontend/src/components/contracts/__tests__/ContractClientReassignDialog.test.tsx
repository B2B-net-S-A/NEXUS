import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { ReassignPlanView } from "../ContractClientReassignDialog";
import { planFromConflict, type ReassignPlan } from "@/lib/api/contractClientReassign";

const base: ReassignPlan = {
  contract_id: 5,
  contract_label: "Kontrakt #5",
  contract_status: "active",
  from_client: { id: 1, name: "BNP Paribas Cardif" },
  to_client: { id: 2, name: "CARDIF - ASSURANCES" },
  orders: [{ id: 10, title: "ZAM-1", status: "active", client_id: 1, start_date: null, end_date: null }],
  b2b_documents: [{ id: 3, contract_number: "12/2026", contract_status: "active", printed_client_name: "BNP" }],
  open_gaps: [],
  alerts: [],
  blockers: [],
  warnings: [],
  can_apply: true,
  fingerprint: "a".repeat(64),
};

describe("ReassignPlanView", () => {
  it("lists what moves and no blocker box when the plan is clean", () => {
    render(<ReassignPlanView plan={base} />);
    expect(screen.getByText("ZAM-1 (#10)")).toBeInTheDocument();
    expect(screen.getByText("12/2026")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders every blocker message", () => {
    render(
      <ReassignPlanView
        plan={{
          ...base,
          can_apply: false,
          blockers: [
            { code: "order_group_line", message: "Konsultant jest linią zamówienia MD." },
            { code: "pm_contact_other_client", message: "PM jest kontaktem innego klienta." },
          ],
        }}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Konsultant jest linią zamówienia MD.");
    expect(alert).toHaveTextContent("PM jest kontaktem innego klienta.");
  });
});

describe("planFromConflict", () => {
  it("reads the fresh plan only from a 409 with a plan", () => {
    const err = { response: { status: 409, data: { detail: { code: "fingerprint_mismatch", plan: base } } } };
    expect(planFromConflict(err)?.fingerprint).toBe(base.fingerprint);
    expect(planFromConflict({ response: { status: 403, data: { detail: "x" } } })).toBeNull();
    expect(planFromConflict(new Error("net"))).toBeNull();
  });
});
