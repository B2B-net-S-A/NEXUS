import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LineConsumptionTable } from "@/components/client-profile/orders/LineConsumptionTable";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: {
    listConsumptions: vi.fn(),
    putConsumption: vi.fn(),
    deleteConsumption: vi.fn(),
  },
}));

import { orderGroupsApi } from "@/lib/api/orderGroups";

const LINE = {
  id: 44,
  group_id: 910,
  contract_id: 100,
  candidate_id: 5,
  consultant_name: "Anna Przykładowa",
  status: "active",
  is_active: true,
  start_date: "2025-10-01",
  end_date: null,
  md_total: 190,
  md_remaining: 36,
} as unknown as OrderLineRead;

const GROUP = {
  id: 910,
  client_id: 115,
  order_number: "4500030197",
  start_date: "2025-10-01",
  end_date: null,
  lines: [LINE],
} as unknown as OrderGroupRead;

const DATA = {
  order_number: "4500030197",
  md_budget: 25,
  md_used: 44,
  md_remaining: -19,
  removed_months: [],
  foreign_import_warnings: [],
  rows: [
    {
      period_month: "2026-07",
      md_reported: 23,
      status: "accepted",
      note: null,
      source: "import",
      source_kind: "import",
      import_id: 1,
      created_by_name: "Import z Finansów",
      updated_at: "2026-08-05T08:00:00Z",
      balance_after: 2,
      import_rows: [
        { import_id: 1, row_number: 30, order_number_hint: "4500030197", md_reported: 23, foreign: false },
      ],
      corrections: [],
    },
    {
      period_month: "2026-08",
      md_reported: 3.7,
      status: null,
      note: "Przeliczona stawka",
      source: "manual",
      source_kind: "manual_correction",
      import_id: null,
      created_by_name: "Anna Korycka",
      updated_at: "2026-09-24T12:23:00Z",
      balance_after: -19,
      import_rows: [],
      corrections: [
        {
          created_at: "2026-09-24T12:23:00Z",
          period_month: "2026-08",
          author_name: "Anna Korycka",
          from_md: 4,
          from_source: "import",
          to_md: 3.7,
          removed: false,
        },
      ],
    },
  ],
};

function renderTable(props: { canEdit?: boolean; enabled?: boolean } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  render(
    <QueryClientProvider client={queryClient}>
      <LineConsumptionTable
        clientId={115}
        group={GROUP}
        line={LINE}
        canEdit={props.canEdit ?? true}
        enabled={props.enabled}
        compact
      />
    </QueryClientProvider>,
  );
  return { invalidateSpy };
}

describe("LineConsumptionTable — zwarty widok do panelu bocznego", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(orderGroupsApi.listConsumptions).mockResolvedValue({ data: DATA } as never);
    vi.mocked(orderGroupsApi.putConsumption).mockResolvedValue({ data: LINE } as never);
  });

  it("trzy kolumny + akcje; reszta w rozwijanych szczegółach wiersza", async () => {
    const user = userEvent.setup();
    renderTable();

    const july = (await screen.findByText("lip 2026")).closest("tr")!;
    expect(july).toHaveTextContent("23");
    expect(july).toHaveTextContent("Zaakceptowany");
    const table = screen.getByRole("table");
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((th) => th.textContent);
    expect(headers).toEqual(["Miesiąc", "MD", "Saldo", "Akcje"]);
    // Kolumny spoza zwartego widoku nie stoją w tabeli, dopóki wiersz jest zwinięty.
    expect(screen.queryByText("Import z Finansów")).toBeNull();

    const toggle = within(july).getByRole("button", { name: "lip 2026" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const details = july.nextElementSibling as HTMLElement;
    expect(details).toHaveTextContent("Nr z importu");
    expect(details).toHaveTextContent("4500030197");
    expect(details).toHaveTextContent("Import z Finansów");

    const august = screen.getByText("sie 2026").closest("tr")!;
    expect(within(august).getByText("-19")).toHaveClass("text-destructive");
    expect(august.nextElementSibling).toHaveTextContent(/↳ korekta: .*import 4 MD → ręcznie 3,7 MD/);
    expect(screen.getByText("Razem").closest("tr")).toHaveTextContent("26,7");
    expect(screen.getByText("Wykorzystane").nextSibling).toHaveTextContent("44 MD");
  });

  it("bez uprawnień: sam podgląd — bez edycji, usuwania i formularza", async () => {
    renderTable({ canEdit: false });
    await screen.findByText("lip 2026");

    expect(screen.queryByRole("button", { name: /Edytuj wpis/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Usuń wpis/ })).toBeNull();
    expect(screen.queryByText("Nowy wpis miesięczny")).toBeNull();
    expect(screen.queryByLabelText("Miesiąc *")).toBeNull();
    expect(
      within(screen.getByRole("table"))
        .getAllByRole("columnheader")
        .map((th) => th.textContent),
    ).toEqual(["Miesiąc", "MD", "Saldo"]);
  });

  it("z uprawnieniami: formularz nowego wpisu zapisuje PUT-em i odświeża listy", async () => {
    const user = userEvent.setup();
    const { invalidateSpy } = renderTable();
    await screen.findByText("lip 2026");

    expect(screen.getByText("Nowy wpis miesięczny")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edytuj wpis za lip 2026" })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Miesiąc *"), "2026-09");
    await user.type(screen.getByLabelText("MD *"), "10");
    await user.click(screen.getByRole("button", { name: "Dodaj wpis" }));

    await waitFor(() =>
      expect(orderGroupsApi.putConsumption).toHaveBeenCalledWith(115, 910, 44, "2026-09", {
        md_reported: 10,
        status: null,
        note: null,
      }),
    );
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["order-group-events", 115] }),
    );
  });

  it("enabled=false nie pobiera danych", () => {
    renderTable({ enabled: false });
    expect(orderGroupsApi.listConsumptions).not.toHaveBeenCalled();
    expect(screen.getByText("Wczytywanie rozliczeń…")).toBeInTheDocument();
  });
});
