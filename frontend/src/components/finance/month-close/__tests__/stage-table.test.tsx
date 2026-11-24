import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MonthCloseClient, MonthCloseOverview, MonthCloseStages } from "@/lib/api/client-settlements";

import { StageTable } from "../StageTable";

const STAGES: MonthCloseStages = {
  people: 4,
  report: { in: 4, missing: 0, md_auto: 4, md_manual: 0 },
  check: { clean: 4, auto_clean: 4, resolved: 0, warn: 0, fail: 0, returned: 0, unread: 0, no_md: 0, missing: 0 },
  accept: { done: 2, auto: 0, ready: 2 },
  contractor_invoice: { match: 0, differs: 0, nip: 0, can_issue: 0, none: 4, waiting: 2 },
  client_invoice: { issued: 0, ready: 2, waiting_client: 0, waiting: 2, issued_early: 0 },
  missing_order: 0,
};

const CLIENT: MonthCloseClient = {
  client_id: 7,
  name: "Klient A",
  people: 4,
  clean: 2,
  accepted: 2,
  decide: 0,
  unread: 0,
  missing: 0,
  contractor_in_ksef: 0,
  client_invoice_issued: 0,
  client_invoice_ready: 2,
  revenue_ready: null,
  top_reason: null,
  client_report: null,
  auto_accept: { count: 2, workday: 3, from: "2026-11-05" },
  stages: STAGES,
};

function renderTable() {
  const data = {
    month: "2026-10",
    can_see_amounts: false,
    totals: {},
    stages: STAGES,
    clients: [CLIENT],
    reasons: [],
  } as unknown as MonthCloseOverview;
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <StageTable
        data={data}
        month="2026-10"
        team={null}
        teamError={null}
        reminders={new Map()}
        clientHref={(id) => `/finance?view=settlements&stClient=${id}`}
        reminderNote={() => undefined}
      />
    </QueryClientProvider>,
  );
}

describe("tabela kroków miesiąca", () => {
  it("„Wystaw” przy kliencie otwiera fakturowanie tylko tego klienta", () => {
    renderTable();
    const link = screen.getByRole("link", { name: "Wystaw" });
    expect(link.getAttribute("href")).toContain("siClient=7");
    expect(link.getAttribute("href")).toContain("siPeriod=2026-10");
  });

  it("pokazuje, ile przyjmie automat i od kiedy", () => {
    renderTable();
    expect(screen.getByText("2 przyjmie automat od 05.11")).toBeTruthy();
    expect(screen.getByText("2 do przyjęcia")).toBeTruthy();
  });

  it("bez biura i bez błędu biura nie ma wiersza biura", () => {
    renderTable();
    expect(screen.queryByText("Biuro — B2B.Net")).toBeNull();
  });
});
