/**
 * Podgląd w oknie nieobecności mówi słowami formy: na B2B i zleceniu pula
 * schodzi „po zgłoszeniu”, przy umowie o pracę „po wniosku” (D4, D5).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { LeavePreview } from "@/lib/api/hr-leave";

import { PreviewPanel } from "../LeavePreviewPanel";

const PREVIEW: LeavePreview = {
  working_days: ["2026-11-03"],
  days_total: "1.0",
  paid_days: "1.0",
  unpaid_days: "0.0",
  years: [
    {
      year: 2026,
      requested: "1.0",
      paid: "1.0",
      unpaid: "0.0",
      has_pool: true,
      remaining_before: "24.0",
      remaining_after: "23.0",
    },
  ],
  blocking_reason: null,
  auto_approved: true,
  employment_type: "b2b",
  flow: "report",
  approver: "Ewa Przykładowa",
  department_absent: [],
  work: { total: 0, by_kind: [], items: [] },
  substitute_absent: false,
  return_on: null,
};

function show(form: "b2b" | "uop") {
  render(
    <PreviewPanel
      preview={{ ...PREVIEW, employment_type: form, flow: form === "uop" ? "request" : "report" }}
      loading={false}
      failed={false}
      waitingForPerson={false}
      onBehalf={false}
      range="03.11.2026"
      form={form}
    />,
  );
}

describe("PreviewPanel — pula według formy", () => {
  it("B2B: pula schodzi po zgłoszeniu", () => {
    show("b2b");
    expect(screen.getByText(/Płatne dni z umowy 2026/).textContent).toMatch(/po zgłoszeniu/);
    expect(screen.queryByText(/po wniosku/)).toBeNull();
  });

  it("UoP: pula schodzi po wniosku", () => {
    show("uop");
    expect(screen.getByText(/Pula 2026/).textContent).toMatch(/po wniosku/);
  });
});
