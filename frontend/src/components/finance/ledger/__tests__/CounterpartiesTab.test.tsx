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
    patch: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));

import { CounterpartiesTab } from "@/components/finance/ledger/CounterpartiesTab";
import type { CounterpartyList, ImportSummary } from "@/lib/api/finance-ledger";

const LIST: CounterpartyList = {
  items: [
    {
      id: 7,
      id_type: "nip",
      id_type_label: "NIP",
      id_value: "1234563218",
      name: "Jan Przykładowy IT",
      street: null,
      postal_code: null,
      city: "Kraków",
      country: "PL",
      email: null,
      symfonia_partner_id: "317",
      cost_account: "201-2-317",
      revenue_account: null,
      role: "contractor",
      role_label: "kontraktor",
      imported_at: null,
      updated_at: null,
    },
  ],
  total: 1,
  role_counts: { client: 0, team: 0, contractor: 1, supplier: 0 },
  without_account: 0,
};

const PREVIEW: ImportSummary = {
  saved: false,
  rows: 3,
  created: 1,
  changed: 1,
  unchanged: 0,
  error_count: 1,
  errors: [{ line: 4, message: "NIP ma niepoprawną sumę kontrolną." }],
  changes: [{ line: 2, name: "Jan Przykładowy IT", fields: ["cost_account"] }],
  columns: ["cost_account", "identifier", "name"],
  linked_entries: 0,
};

function renderTab(canWrite = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CounterpartiesTab canWrite={canWrite} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  showToast.mockReset();
  get.mockResolvedValue({ data: LIST });
});

describe("CounterpartiesTab", () => {
  it("pokazuje rolę i konta", async () => {
    renderTab();
    expect(await screen.findByText("Jan Przykładowy IT")).toBeInTheDocument();
    expect(screen.getByText("kontraktor")).toBeInTheDocument();
    expect(screen.getByText("201-2-317")).toBeInTheDocument();
  });

  it("najpierw podgląd pliku, dopiero „Zapisz” zapisuje", async () => {
    post
      .mockResolvedValueOnce({ data: PREVIEW })
      .mockResolvedValueOnce({ data: { ...PREVIEW, saved: true, linked_entries: 2 } });
    const user = userEvent.setup();
    renderTab();
    await screen.findByText("Jan Przykładowy IT");
    const file = new File(["Nazwa;NIP\n"], "partnerzy.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText("Plik kontrahentów z eBI24"), file);

    expect(await screen.findByText(/wiersz 4: NIP ma niepoprawną sumę kontrolną/)).toBeInTheDocument();
    expect(post.mock.calls[0][2]).toMatchObject({ params: { save: false } });

    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(post.mock.calls[1][2]).toMatchObject({ params: { save: true } });
    expect(await screen.findByText(/Powiązano z kolejką kosztów: 2 faktury/)).toBeInTheDocument();
  });

  it("podgląd jako inna osoba bez importu i edycji", async () => {
    renderTab(false);
    await screen.findByText("Jan Przykładowy IT");
    expect(screen.queryByRole("button", { name: "Edytuj konta" })).toBeNull();
  });
});
