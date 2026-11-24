import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ClientsList,
  deliveryLeadLabel,
  formatWholePln,
  rowAttention,
} from "@/components/clients/ClientsList";
import { consultantAttention } from "@/components/clients/ClientAttention";
import type { ClientListItem, ClientListParams, ClientListResponse } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  currentSearch: "",
  list: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
  capabilities: new Set<string>(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn(() => Promise.resolve({ data: [] })) },
  clientListApi: {
    list: (...args: unknown[]) => mocks.list(...args),
  },
}));

vi.mock("@/components/clients/ClientAttention", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/clients/ClientAttention")>()),
  useClientAttention: () => ({ byClient: new Map(), failed: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/clients",
  useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
  useSearchParams: () => new URLSearchParams(mocks.currentSearch),
}));

vi.mock("@/hooks/useCapability", () => ({
  useCapability: (capability: string) => mocks.capabilities.has(capability),
}));

vi.mock("@/components/AppShell", () => ({
  AddClientModal: ({ category }: { category?: string }) => (
    <div data-testid="add-client-modal-category">{category}</div>
  ),
}));

function item(overrides: Partial<ClientListItem> = {}): ClientListItem {
  return {
    client_id: 7,
    display_name: "Bank Przykładowy",
    legal_name: null,
    industry: "Bankowość",
    state: "working",
    active_consultants: 32,
    planned_consultants: 3,
    open_jobs: 40,
    monthly_margin: 197588,
    monthly_margin_unpriced: 1,
    delivery_leads: [
      { name: "Opiekun Zapasowy", is_head: false },
      { name: "Delivery Lead Przykładowy", is_head: true },
    ],
    framework_effective_date: "2025-08-19",
    framework_expiry_date: "2028-08-19",
    has_framework_period: true,
    framework_count: 1,
    consultant_attention: {
      total: 2,
      order_ending: 2,
      order_ending_first: "2026-11-30",
      no_current_order: 0,
      notice: 0,
    },
    manually_placed: false,
    ...overrides,
  };
}

function response(overrides: Partial<ClientListResponse> = {}): ClientListResponse {
  return {
    items: [item()],
    total: 1,
    page: 1,
    page_size: 50,
    state_counts: { working: 29, idle: 6, archive: 112 },
    amounts_visible: true,
    manually_placed_count: 7,
    as_of: "2026-11-19",
    ...overrides,
  };
}

function renderList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ClientsList />
    </QueryClientProvider>,
  );
}

function requested(callIndex = 0): ClientListParams {
  return mocks.list.mock.calls[callIndex][0] as ClientListParams;
}

function narrowHeaders(): string[] {
  // jsdom nie liczy CSS: kolumny szerokiej tabeli (≥ 1700 px) są w DOM.
  return screen
    .getAllByRole("columnheader")
    .filter((header) => !header.className.includes("@min-[1700px]:table-cell"))
    .map((header) => header.textContent?.trim() ?? "");
}

describe("znaczniki i formaty listy „Klienci”", () => {
  it("odmienia zamówienia bez kontynuacji i podaje najbliższy koniec", () => {
    const labels = (count: number) =>
      consultantAttention({
        client_id: 1,
        consultant_attention: {
          order_ending: count,
          order_ending_first: "2026-11-30",
          no_current_order: 0,
          notice: 0,
        },
      }).map((entry) => [entry.label, entry.note]);
    expect(labels(1)).toEqual([["1 zamówienie bez kontynuacji", "najbliższe 30.11"]]);
    expect(labels(2)).toEqual([["2 zamówienia bez kontynuacji", "najbliższe 30.11"]]);
    expect(labels(39)).toEqual([["39 zamówień bez kontynuacji", "najbliższe 30.11"]]);
    expect(labels(0)).toEqual([]);
  });

  it("mówi tymi samymi słowami co zakładka Konsultanci i prowadzi do niej", () => {
    const entries = consultantAttention({
      client_id: 26,
      consultant_attention: {
        order_ending: 0,
        order_ending_first: null,
        no_current_order: 2,
        notice: 6,
      },
    });
    expect(entries.map((entry) => [entry.label, entry.note])).toEqual([
      ["Brak bieżącego zamówienia", "2 osoby"],
      ["6 umów wypowiedzianych", undefined],
    ]);
    expect(new Set(entries.map((entry) => entry.href))).toEqual(
      new Set(["/clients/26?tab=konsultanci"]),
    );
  });

  it("stawia umowę przed konsultantami, a bez współpracy nie liczy konsultantów", () => {
    const expired = item({ framework_expiry_date: "2026-03-29" });
    expect(rowAttention(expired, []).map((entry) => entry.label)).toEqual([
      "Umowa wygasła",
      "2 zamówienia bez kontynuacji",
    ]);
    expect(rowAttention({ ...expired, state: "idle" }, []).map((entry) => entry.label)).toEqual([
      "Umowa wygasła",
    ]);
    expect(rowAttention(item({ has_framework_period: false }), []).map((e) => e.label)).toEqual([
      "2 zamówienia bez kontynuacji",
    ]);
  });

  it("pokazuje głównego DL-a pierwszego i marżę w pełnych złotych", () => {
    expect(deliveryLeadLabel(item().delivery_leads)).toBe("Delivery Lead Przykładowy +1");
    expect(deliveryLeadLabel([])).toBeNull();
    expect(formatWholePln(197588)).toMatch(/^197\s588 zł$/);
    expect(formatWholePln(-6930)).toMatch(/^-6930 zł$/);
  });
});

describe("ClientsList — lista „Klienci” ze stanem z faktów", () => {
  beforeEach(() => {
    mocks.currentSearch = "";
    mocks.list.mockReset();
    mocks.push.mockReset();
    mocks.replace.mockReset();
    mocks.capabilities = new Set();
    mocks.list.mockResolvedValue({ data: response() });
  });

  it("otwiera „Współpracujemy” z liczbami, marżą i definicją stanu", async () => {
    renderList();

    expect(await screen.findByText("Bank Przykładowy")).toBeInTheDocument();
    expect(requested()).toEqual({ state: "working", q: undefined, page: 1, page_size: 50 });
    expect(mocks.replace).toHaveBeenCalledWith("/clients?state=working&page=1", { scroll: false });
    expect(screen.getByRole("tab", { name: /^Współpracujemy, 29 klientów/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: /^Archiwum/ })).toHaveTextContent("112");
    expect(narrowHeaders()).toEqual([
      "Klient",
      "Nasi ludzie",
      "Rekrutacje",
      "Marża / mc",
      "Umowa ramowa",
      "Wymaga uwagi",
    ]);
    expect(screen.getByTestId("client-state-definition")).toHaveTextContent(
      "Pracuje u nich ktoś od nas, ktoś zaczyna albo trwa rekrutacja.",
    );
    const row = screen.getByText("Bank Przykładowy").closest("tr") as HTMLElement;
    expect(within(row).getByTestId("client-people-cell")).toHaveTextContent("32+3 zaczyna");
    expect(within(row).getByRole("link", { name: "40" })).toHaveAttribute(
      "href",
      "/clients/7?tab=projekty",
    );
    expect(within(row).getByTestId("client-margin-cell")).toHaveTextContent(/197\s588 zł/);
    expect(within(row).getByTestId("client-margin-cell")).toHaveTextContent("niepełna");
    expect(within(row).getByText("2 zamówienia bez kontynuacji")).toBeInTheDocument();
    expect(screen.getByText("29 współpracuje z nami teraz")).toBeInTheDocument();
    // Porządki portfela tylko dla administratora portfela.
    expect(screen.queryByRole("link", { name: /Otwórz porządki/ })).not.toBeInTheDocument();
  });

  it("dawny adres z zakładką portfela otwiera listę i nie wozi `category` dalej", async () => {
    mocks.currentSearch = "category=inactive&page=1";
    renderList();

    await screen.findByText("Bank Przykładowy");
    expect(requested().state).toBe("working");
    expect(mocks.replace).toHaveBeenCalledWith("/clients?page=1&state=working", { scroll: false });
  });

  it("w „Bez bieżącej pracy” chowa kolumny, które z definicji mają same zera", async () => {
    mocks.currentSearch = "state=idle&page=1";
    mocks.list.mockResolvedValue({
      data: response({
        items: [
          item({
            state: "idle",
            active_consultants: 0,
            planned_consultants: 0,
            open_jobs: 0,
            monthly_margin: 0,
            consultant_attention: {
              total: 0,
              order_ending: 0,
              order_ending_first: null,
              no_current_order: 0,
              notice: 0,
            },
          }),
        ],
      }),
    });
    renderList();

    await screen.findByText("Bank Przykładowy");
    expect(requested().state).toBe("idle");
    expect(narrowHeaders()).toEqual(["Klient", "Umowa ramowa", "Wymaga uwagi"]);
  });

  it("szuka we wszystkich stanach i podpisuje stan pod nazwą", async () => {
    mocks.currentSearch = "state=working&q=bank&page=1";
    mocks.list.mockResolvedValue({
      data: response({ items: [item({ state: "archive", active_consultants: 0 })], total: 1 }),
    });
    renderList();

    await screen.findByText("Bank Przykładowy");
    expect(requested()).toMatchObject({ state: "working", q: "bank" });
    expect(screen.getByText("1 wynik ze wszystkich klientów")).toBeInTheDocument();
    const row = screen.getByText("Bank Przykładowy").closest("tr") as HTMLElement;
    expect(within(row).getByText("Archiwum")).toBeInTheDocument();
    // Przy frazie żadna zakładka nie udaje, że jest wybrana.
    for (const tab of screen.getAllByRole("tab")) {
      expect(tab).toHaveAttribute("aria-selected", "false");
    }
  });

  it("bez prawa do kwot nie ma kolumny marży", async () => {
    mocks.list.mockResolvedValue({
      data: response({ amounts_visible: false, items: [item({ monthly_margin: null })] }),
    });
    renderList();

    await screen.findByText("Bank Przykładowy");
    expect(narrowHeaders()).not.toContain("Marża / mc");
  });

  it("administrator portfela ma pod listą wejście do „Porządków portfela”", async () => {
    mocks.capabilities = new Set(["client.portfolio.manage"]);
    renderList();

    await screen.findByText("Bank Przykładowy");
    expect(screen.getByRole("link", { name: /Otwórz porządki/ })).toHaveAttribute(
      "href",
      "/clients/portfolio",
    );
    expect(screen.getByText(/ustawione ręcznie \(7\)/)).toBeInTheDocument();
  });
});
