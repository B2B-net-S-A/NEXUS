import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";
import { useAuthStore } from "@/store/auth";

const getMock = vi.fn();
vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
  aiWriterApi: {},
  phase5Api: {},
  pipelineTemplatesApi: {},
  requestHistoryApi: {},
}));

function renderList() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ContractsListV2 />
    </QueryClientProvider>,
  );
}

function listCalls() {
  return getMock.mock.calls.filter((c) => c[0] === "/api/contracts");
}

/**
 * Eksport dzieli frazę z listą („eksportuj to, co widzę"). Po wprowadzeniu
 * debounce'u musi czytać wartość ZDEBOUNCOWANĄ, nie surową z inputa — inaczej
 * w oknie 300 ms wysyłałby inne `q` niż to, co user właśnie widzi na ekranie.
 */
describe("ContractsListV2 — eksport dzieli frazę z listą", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    useAuthStore.setState({
      user: {
        id: 1,
        email: "admin@example.com",
        name: "Admin",
        role: "admin",
        roles: ["admin"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        capabilities: ["view_finance"],
        analytics_capabilities: ["view_finance"],
      },
      hydrated: true,
    });
    getMock.mockReset();
    getMock.mockImplementation((url: string) => {
      if (url === "/api/contracts") {
        return Promise.resolve({
          data: { items: [], total: 0, page: 1, page_size: 20 },
        });
      }
      return Promise.resolve({ data: { items: [], count: 0 } });
    });

    fetchMock.mockReset();
    fetchMock.mockResolvedValue({ ok: true, blob: async () => new Blob(["x"]) });
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
    useAuthStore.setState({ user: null, hydrated: true });
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("w oknie debounce'u eksportuje to, co widać, a nie to, co dopisano w inpucie", async () => {
    renderList();
    await waitFor(() => expect(listCalls()).toHaveLength(1));
    // Lista pokazuje wynik bez filtra.
    expect(listCalls()[0][1]).toMatchObject({
      params: expect.objectContaining({ q: undefined }),
    });

    // Wszystko poniżej leci synchronicznie, w jednym makrotasku — debounce
    // (300 ms) jeszcze NIE wystrzelił, więc na ekranie wciąż jest lista bez
    // filtra, mimo że w inpucie jest już „acme".
    const input = screen.getByPlaceholderText(/szukaj po kandydacie/i);
    fireEvent.change(input, { target: { value: "acme" } });
    expect(input).toHaveValue("acme");
    expect(listCalls()).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: /eksport/i }));
    fireEvent.click(screen.getByText(/excel \(\.xlsx\)/i));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("format=xlsx");
    // Przed naprawą poleciałoby `q=acme` — plik nie zgadzałby się z ekranem.
    expect(url).not.toContain("q=acme");
  });
});
