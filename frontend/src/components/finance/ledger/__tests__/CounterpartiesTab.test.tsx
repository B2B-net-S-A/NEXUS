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
const fetchDownload = vi.fn();
const saveBlob = vi.fn();
vi.mock("@/lib/authenticated-files", () => ({
  fetchAuthenticatedDownload: (...a: unknown[]) => fetchDownload(...a),
  downloadBlob: (...a: unknown[]) => saveBlob(...a),
}));

import { CounterpartiesTab } from "@/components/finance/ledger/CounterpartiesTab";
import type {
  CounterpartyList,
  ImportSummary,
  PendingCounterparties,
} from "@/lib/api/finance-ledger";

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

const PENDING: PendingCounterparties = {
  items: [
    {
      key: "nip:5260300517",
      name: "Nowy Dostawca Sp. z o.o.",
      id_type: "nip",
      id_type_label: "NIP",
      id_value: "5260300517",
      street: null,
      postal_code: null,
      city: null,
      country: "PL",
      sources: ["faktura kosztowa"],
      counterparty_id: null,
      receivable_prefix: "200-2",
      payable_prefix: "201-2",
      problems: [],
      warnings: ["brak adresu"],
      ready: true,
    },
    {
      key: "nip:1234567890",
      name: "Zły Numer SA",
      id_type: "nip",
      id_type_label: "NIP",
      id_value: "1234567890",
      street: "ul. Testowa 1",
      postal_code: "00-001",
      city: "Warszawa",
      country: "PL",
      sources: ["faktura sprzedaży"],
      counterparty_id: null,
      receivable_prefix: "200-2",
      payable_prefix: "201-2",
      problems: ["numer: NIP ma niepoprawną sumę kontrolną."],
      warnings: [],
      ready: false,
    },
  ],
  total: 2,
  ready: 1,
  without_address: 1,
  with_problems: 1,
  registered: 2317,
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
  fetchDownload.mockReset();
  saveBlob.mockReset();
  get.mockImplementation(async (url: string) => ({
    data: url.endsWith("/pending") ? PENDING : LIST,
  }));
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

  it("lista „Czeka na Symfonię” pokazuje gotowych, problemy i pobiera plik", async () => {
    fetchDownload.mockResolvedValue({ blob: new Blob(["x"]), filename: "kontrahenci-do-symfonii-2026-11-17.csv" });
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("tab", { name: /Czeka na Symfonię \(2\)/ }));

    expect(await screen.findByText("Nowy Dostawca Sp. z o.o.")).toBeInTheDocument();
    expect(screen.getByText("brak adresu")).toBeInTheDocument();
    expect(screen.getByText(/numer: NIP ma niepoprawną sumę kontrolną/)).toBeInTheDocument();
    expect(screen.getByText(/1 do poprawy — nie ma ich w pliku/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Pobierz plik dla księgowej" }));
    await waitFor(() => expect(saveBlob).toHaveBeenCalledTimes(1));
    expect(fetchDownload).toHaveBeenCalledWith("/api/finance/counterparties/pending/file");
    expect(saveBlob.mock.calls[0][1]).toBe("kontrahenci-do-symfonii-2026-11-17.csv");
  });

  it("przy pustej kartotece ostrzega, żeby najpierw wgrać plik z eBI24", async () => {
    get.mockImplementation(async (url: string) => ({
      data: url.endsWith("/pending") ? { ...PENDING, registered: 0 } : LIST,
    }));
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("tab", { name: /Czeka na Symfonię/ }));
    expect(await screen.findByText(/Kartoteka nie ma jeszcze żadnego ID Symfonii/)).toBeInTheDocument();
  });

  it("pusta lista „czeka na Symfonię” to komunikat, nie błąd", async () => {
    get.mockImplementation(async (url: string) => ({
      data: url.endsWith("/pending")
        ? { items: [], total: 0, ready: 0, without_address: 0, with_problems: 0, registered: 5 }
        : LIST,
    }));
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("tab", { name: /Czeka na Symfonię/ }));
    expect(await screen.findByText(/Nikt nie czeka na założenie w Symfonii/)).toBeInTheDocument();
  });

  it("awaria listy „czeka na Symfonię” nie wygląda jak pusta lista", async () => {
    get.mockImplementation(async (url: string) => {
      if (url.endsWith("/pending")) throw new Error("boom");
      return { data: LIST };
    });
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("tab", { name: /Czeka na Symfonię/ }));
    expect(await screen.findByRole("button", { name: /Spróbuj ponownie|Ponów/i })).toBeInTheDocument();
    expect(screen.queryByText(/Nikt nie czeka/)).toBeNull();
  });
});
