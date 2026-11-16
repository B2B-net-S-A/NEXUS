import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: vi.fn(),
    patch: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { CostsTab } from "@/components/finance/ledger/CostsTab";
import type { CostQueue, CostRow } from "@/lib/api/finance-ledger";

const ROW: CostRow = {
  id: 11,
  source_type: "payroll_invoice",
  source_id: 501,
  from_ksef: true,
  stage: "received",
  stage_label: "Z KSeF do przyjęcia",
  flags: ["mpp"],
  category: "team",
  category_label: "Zespół",
  received_at: "2026-11-12T08:00:00+00:00",
  seller_name: "Jan Przykładowy IT",
  seller_nip: "1234563218",
  invoice_number: "7/11/2026",
  ksef_number: "1234563218-20261112-97AC00000000-AB",
  issue_date: "2026-11-10",
  currency: "PLN",
  net_amount: "26400.00",
  gross_amount: "32472.00",
  due_date: "2026-11-26",
  due_date_set: false,
  counterparty_id: null,
  counterparty_name: null,
  cost_account: null,
  concerning: {
    kind: "team",
    person: "Jan Przykładowy",
    label: "Rozliczenie 10.2026",
    status: "matched",
    status_label: "dopasowana do rozliczenia",
  },
  own: false,
  reject_reason: null,
  note: null,
};

const OWN: CostRow = {
  ...ROW,
  id: 12,
  invoice_number: "FV/9/11/2026",
  seller_name: "Księgowa Testowa",
  concerning: { ...ROW.concerning!, person: "Księgowa Testowa" },
  flags: [],
  own: true,
};

function queue(items: CostRow[]): CostQueue {
  return {
    stage: "received",
    items,
    total: items.length,
    counts: { received: items.length, new: 4, verified: 0, ready: 0, booked: 0, rejected: 2 },
    limit: 100,
    offset: 0,
  };
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CostsTab />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  showToast.mockReset();
  window.history.replaceState(null, "", "/finance?view=costs");
});

function answer(items: CostRow[]) {
  get.mockImplementation((url: string) =>
    url.endsWith("/module")
      ? Promise.resolve({ data: { enabled: true, open: true } })
      : Promise.resolve({ data: queue(items) }),
  );
}

describe("CostsTab", () => {
  it("pokazuje kogo dotyczy, flagi i liczniki zakładek", async () => {
    answer([ROW, OWN]);
    renderTab();
    expect(await screen.findByRole("link", { name: "7/11/2026" })).toHaveAttribute(
      "href",
      "/finance/costs/11",
    );
    expect(screen.getAllByText("Jan Przykładowy")[0]).toBeInTheDocument();
    expect(screen.getAllByText(/Rozliczenie 10.2026 · dopasowana do rozliczenia/)).toHaveLength(2);
    // „MPP” jest też w filtrze flag — plakietka to ta poza listą wyboru.
    expect(screen.getAllByText("MPP").filter((el) => el.tagName !== "OPTION")).toHaveLength(1);
    expect(screen.getByRole("tab", { name: /Do opisu\s*4/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Zaznacz FV/9/11/2026" })).toBeDisabled();
  });

  it("przyjmuje zaznaczone i mówi, ile zmieniono", async () => {
    answer([ROW, OWN]);
    post.mockResolvedValue({ data: { changed: 1, refused: [] } });
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("checkbox", { name: "Zaznacz wszystkie widoczne" }));
    await user.click(screen.getByRole("button", { name: "Przyjmij zaznaczone (1)" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/costs/actions", {
        ids: [11],
        action: "accept",
        reason: undefined,
      }),
    );
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Zmieniono: 1 faktura.", "success"));
  });

  it("odrzucenie pyta o powód", async () => {
    answer([ROW]);
    post.mockResolvedValue({ data: { changed: 1, refused: [] } });
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("checkbox", { name: "Zaznacz 7/11/2026" }));
    await user.click(screen.getByRole("button", { name: "Odrzuć zaznaczone (1)" }));
    await user.type(await screen.findByLabelText("Powód"), "Nie dotyczy firmy");
    await user.click(screen.getByRole("button", { name: "Odrzuć" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/costs/actions", {
        ids: [11],
        action: "reject",
        reason: "Nie dotyczy firmy",
      }),
    );
  });

  it("pusta poczekalnia tylko po udanym odczycie", async () => {
    answer([]);
    renderTab();
    expect(await screen.findByText("Nic nie czeka na przyjęcie z KSeF.")).toBeInTheDocument();
  });

  it("awaria nie wygląda jak pusta lista", async () => {
    get.mockImplementation((url: string) =>
      url.endsWith("/module")
        ? Promise.resolve({ data: { enabled: true, open: true } })
        : Promise.reject({ response: { status: 500 } }),
    );
    renderTab();
    expect(await screen.findByRole("button", { name: /Spróbuj ponownie/i })).toBeInTheDocument();
    expect(screen.queryByText("Nic nie czeka na przyjęcie z KSeF.")).not.toBeInTheDocument();
  });
});
