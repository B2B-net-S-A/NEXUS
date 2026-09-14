import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  stats: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("view=operations&tab=active"),
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

vi.mock("@/lib/api", () => ({
  contractorsApi: {
    list: (...args: unknown[]) => mocks.list(...args),
    stats: (...args: unknown[]) => mocks.stats(...args),
  },
}));

vi.mock("@/components/v2/modals/DraftCompletionModal", () => ({
  DraftCompletionModal: () => null,
}));

import { ContractorsListV2 } from "@/components/v2/pages/ContractorsListV2";

function item(
  id: number,
  lastname: string,
  orders: Array<{ status: string; start_date: string | null; end_date: string | null }>,
) {
  return {
    contract_id: id,
    candidate: { id: id + 100, name: "Jan", lastname, email: null },
    client_name: "Klient testowy",
    job_title: null,
    status: "active",
    start_date: "2026-08-01",
    end_date: null,
    rate_candidate: null,
    rate_client: null,
    rate_unit: "hourly",
    currency: "PLN",
    margin: null,
    contract_type: "b2b",
    work_mode: null,
    missing_fields: [],
    orders,
  };
}

function renderList() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ContractorsListV2 />
    </QueryClientProvider>,
  );
}

describe("ContractorsListV2 — dopisek, status i daty (UAT M08-B05/B06)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({
      data: {
        items: [
          item(1, "Pokryty", [
            { status: "active", start_date: "2026-01-01", end_date: "2099-12-31" },
          ]),
          item(2, "Bezzamowienia", [
            { status: "completed", start_date: "2020-01-01", end_date: "2020-06-30" },
          ]),
        ],
        total: 2,
        page: 1,
        page_size: 50,
      },
    });
    mocks.stats.mockResolvedValue({
      data: { draft: 0, drafts_incomplete: 0, active_contracts: 2, active: 2, ending: 0 },
    });
  });

  it("dopisek „Brak aktywnego zamówienia” tylko przy osobie bez zamówienia na dziś", async () => {
    renderList();
    const uncovered = (await screen.findByRole("link", { name: "Jan Bezzamowienia" }))
      .closest("tr") as HTMLElement;
    const covered = screen.getByRole("link", { name: "Jan Pokryty" }).closest("tr") as HTMLElement;

    expect(within(uncovered).getByText("Brak aktywnego zamówienia")).toBeInTheDocument();
    expect(within(covered).queryByText("Brak aktywnego zamówienia")).toBeNull();
  });

  it("status po polsku i data w formacie DD.MM.RRRR", async () => {
    renderList();
    await screen.findByRole("link", { name: "Jan Pokryty" });
    expect(screen.getAllByText("Aktywny")).toHaveLength(2);
    expect(screen.queryByText("active")).toBeNull();
    expect(screen.getAllByText("01.08.2026")).toHaveLength(2);
  });
});
