import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ClientsListV2 } from "@/components/v2/pages/ClientsListV2";
import type { ClientDirectoryResponse } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  currentSearch: "",
  list: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  clientsDirectoryApi: {
    list: (...args: unknown[]) => mocks.list(...args),
  },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/clients",
  useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
  useSearchParams: () => new URLSearchParams(mocks.currentSearch),
}));

vi.mock("@/hooks/useCapability", () => ({ useCapability: () => false }));

vi.mock("@/components/AppShell", () => ({
  AddClientModal: () => null,
}));

vi.mock("@/lib/session", () => ({
  getAuthenticatedRequestHeaders: () => ({ Authorization: "Bearer tok-123" }),
}));

const BASE_RESPONSE: ClientDirectoryResponse = {
  items: [
    {
      scope_id: 11,
      client_id: 7,
      msa_id: 101,
      display_name: "Nordea ABP",
      legal_name: "Nordea Bank Abp",
      scope_label: "Bankowość",
      industry: "Banking & Finance",
      active_consultants_count: 4,
      active_contracts_count: 5,
      effective_date: "2026-02-01",
      expiry_date: null,
      category: "active",
      category_base: "active",
      client_status: "active",
      category_override: null,
      contract_start_override: null,
      contract_end_override: null,
    },
  ],
  total_rows: 1,
  total_clients: 1,
  page: 1,
  page_size: 50,
  category_counts: { active: 1, relationship: 4, inactive: 3 },
  as_of: "2026-07-30",
};

function renderList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ClientsListV2 />
    </QueryClientProvider>,
  );
}

describe("ClientsListV2 — eksport katalogu klientów", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    mocks.currentSearch = "";
    mocks.list.mockReset();
    mocks.push.mockReset();
    mocks.replace.mockReset();
    mocks.list.mockResolvedValue({ data: BASE_RESPONSE });

    fetchMock.mockReset();
    fetchMock.mockResolvedValue({
      ok: true,
      blob: async () => new Blob(["x"]),
      headers: { get: () => null },
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:stub"),
      revokeObjectURL: vi.fn(),
    });
    // jsdom nie umie nawigacji — anchor pobierania i tak nic nie robi w teście.
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("Excel trafia w endpoint eksportu z aktualną kategorią i tokenem", async () => {
    renderList();
    await screen.findByText("Nordea ABP");

    fireEvent.click(screen.getByRole("button", { name: /eksport/i }));
    fireEvent.click(screen.getByText(/excel \(\.xlsx\)/i));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    const requestUrl = String(url);
    expect(requestUrl).toContain("/api/clients/directory/export");
    expect(requestUrl).toContain("category=active");
    expect(requestUrl).toContain("format=xlsx");
    // Bez frazy nie doklejamy pustego `q`.
    expect(requestUrl).not.toContain("q=");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer tok-123",
    });
  });

  it("CSV używa format=csv", async () => {
    renderList();
    await screen.findByText("Nordea ABP");

    fireEvent.click(screen.getByRole("button", { name: /eksport/i }));
    fireEvent.click(screen.getByText(/^CSV$/));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0][0])).toContain("format=csv");
  });

  it("eksportuje kategorię aktualnie wybranego kafelka", async () => {
    renderList();
    await screen.findByText("Nordea ABP");

    fireEvent.click(screen.getByRole("tab", { name: /^Klienci relacyjni/i }));

    fireEvent.click(screen.getByRole("button", { name: /eksport/i }));
    fireEvent.click(screen.getByText(/excel \(\.xlsx\)/i));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0][0])).toContain("category=relationship");
  });

  it("przy błędzie eksportu pokazuje komunikat i nie pobiera pliku", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500 });
    renderList();
    await screen.findByText("Nordea ABP");

    fireEvent.click(screen.getByRole("button", { name: /eksport/i }));
    fireEvent.click(screen.getByText(/excel \(\.xlsx\)/i));

    expect(await screen.findByText(/Eksport nie powiódł się/i)).toBeVisible();
  });

  it("ostrzega toastem, gdy backend oznaczy plik jako częściowy", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      blob: async () => new Blob(["x"]),
      headers: {
        get: (name: string) =>
          name.toLowerCase() === "x-export-truncated" ? "true" : null,
      },
    });
    renderList();
    await screen.findByText("Nordea ABP");

    fireEvent.click(screen.getByRole("button", { name: /eksport/i }));
    fireEvent.click(screen.getByText(/excel \(\.xlsx\)/i));

    expect(await screen.findByText(/częściowy widok/i)).toBeVisible();
  });
});
