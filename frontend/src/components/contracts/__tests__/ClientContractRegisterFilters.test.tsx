import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ClientContractRegister } from "@/components/contracts/ClientContractRegister";
import { useAuthStore } from "@/store/auth";

const getMock = vi.fn();
vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => getMock(...args) },
  contractsApi: { update: vi.fn() },
}));

// Dialog "Nowy/Edytuj kontrakt" nie jest przedmiotem testu; wyłączamy go, żeby
// nie ciągnął własnych zależności/zapytań.
vi.mock("@/components/contracts/ContractRegisterDialog", () => ({
  ContractRegisterDialog: () => null,
}));

vi.mock("@/lib/session", () => ({ getAccessToken: () => "tok" }));

const CLIENT_ID = 42;

function renderRegister() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ClientContractRegister clientId={CLIENT_ID} clientName="Nordea Bank" />
    </QueryClientProvider>,
  );
}

function listCalls() {
  return getMock.mock.calls.filter((c) => c[0] === "/api/contracts");
}

describe("ClientContractRegister — filtry (Okres) + eksport", () => {
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
        capabilities: [],
        analytics_capabilities: [],
      },
      hydrated: true,
    });
    getMock.mockReset();
    getMock.mockResolvedValue({
      data: { items: [], total: 0, page: 1, page_size: 50 },
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
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("scopuje listę do klienta i przepuszcza zakres Okres (overlap) do zapytania", async () => {
    renderRegister();
    await waitFor(() => expect(listCalls().length).toBeGreaterThan(0));
    // Pierwsze zapytanie: scope po kliencie, bez filtra okresu.
    expect(listCalls()[0][1]).toMatchObject({
      params: expect.objectContaining({
        client_id: CLIENT_ID,
        period_from: undefined,
        period_to: undefined,
      }),
    });

    fireEvent.change(screen.getByLabelText("Okres od"), {
      target: { value: "2026-06-01" },
    });
    fireEvent.change(screen.getByLabelText("Okres do"), {
      target: { value: "2026-06-30" },
    });

    // Zmiana zakresu re-fetchuje listę z period_from/period_to (server-side).
    // Dwie zmiany inputów → dwa re-fetch'e; szukamy tego z KOMPLETNYM zakresem
    // (period_from ustawia się przed period_to, więc jest też stan pośredni).
    await waitFor(() => {
      const withPeriod = listCalls().find((c) => {
        const p = (c[1] as { params?: Record<string, unknown> })?.params;
        return p?.period_from === "2026-06-01" && p?.period_to === "2026-06-30";
      });
      expect(withPeriod).toBeTruthy();
      expect(
        (withPeriod![1] as { params: Record<string, unknown> }).params,
      ).toMatchObject({ client_id: CLIENT_ID });
    });
  });

  it("eksport uderza w /register/export z client_id i aktualnymi filtrami", async () => {
    renderRegister();
    await waitFor(() => expect(listCalls().length).toBeGreaterThan(0));

    fireEvent.change(screen.getByLabelText("Okres od"), {
      target: { value: "2026-06-01" },
    });
    fireEvent.change(screen.getByLabelText("Okres do"), {
      target: { value: "2026-06-30" },
    });

    fireEvent.click(
      screen.getByRole("button", { name: /eksportuj do excela/i }),
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/contracts/register/export");
    expect(url).toContain(`client_id=${CLIENT_ID}`);
    expect(url).toContain("period_from=2026-06-01");
    expect(url).toContain("period_to=2026-06-30");
    // Bearer token dołączony z sesji.
    const init = fetchMock.mock.calls[0][1] as { headers?: Record<string, string> };
    expect(init.headers?.Authorization).toBe("Bearer tok");
  });
});
