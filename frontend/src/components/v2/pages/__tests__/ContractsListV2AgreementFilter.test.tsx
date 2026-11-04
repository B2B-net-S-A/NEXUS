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

function lastListParams(): Record<string, unknown> {
  const calls = getMock.mock.calls.filter((c) => c[0] === "/api/contracts");
  return (calls[calls.length - 1]?.[1] as { params: Record<string, unknown> })
    .params;
}

/**
 * „Umowa nierozwiązana” (decyzja Artura 28.10.2026): zbiór liczy serwer
 * (`agreement_not_terminated`), filtr żyje w adresie i idzie na wszystkie
 * statusy, bo domyślne „Aktywne + Kończące się” ucięłyby zakończone.
 */
describe("ContractsListV2 — filtr „Umowa nierozwiązana”", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    window.history.replaceState({}, "", "/contracts");
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
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  afterEach(() => {
    useAuthStore.setState({ user: null, hydrated: true });
    window.history.replaceState({}, "", "/contracts");
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("włącza filtr w zapytaniu, adresie i eksporcie, a wyłączenie wraca do domyślnych statusów", async () => {
    renderList();
    await waitFor(() =>
      expect(lastListParams()).toMatchObject({ status: ["active", "ending"] }),
    );
    expect(lastListParams().agreement_not_terminated).toBeUndefined();

    const toggle = screen.getByRole("button", { name: /umowa nierozwiązana/i });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);

    await waitFor(() =>
      expect(lastListParams()).toMatchObject({ agreement_not_terminated: true }),
    );
    expect(lastListParams().status).toBeUndefined();
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(window.location.search).toBe("?status=all&agreement=not_terminated");

    fireEvent.click(screen.getByRole("button", { name: /eksport/i }));
    fireEvent.click(screen.getByText(/excel \(\.xlsx\)/i));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "agreement_not_terminated=true",
    );

    fireEvent.click(toggle);
    await waitFor(() =>
      expect(lastListParams().agreement_not_terminated).toBeUndefined(),
    );
    expect(lastListParams()).toMatchObject({ status: ["active", "ending"] });
    expect(window.location.search).toBe("?status=active&status=ending");
  });

  it("wejście z adresu z filtrem pyta serwer od razu", async () => {
    window.history.replaceState({}, "", "/contracts?agreement=not_terminated");
    renderList();
    await waitFor(() =>
      expect(lastListParams()).toMatchObject({ agreement_not_terminated: true }),
    );
    expect(lastListParams().status).toBeUndefined();
    expect(
      screen.getByRole("button", { name: /umowa nierozwiązana/i }),
    ).toHaveAttribute("aria-pressed", "true");
  });
});
