import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ClientContractRegister } from "@/components/contracts/ClientContractRegister";
import { useAuthStore } from "@/store/auth";
import {
  buildClientContractRegisterUrl,
  rememberContractsListScroll,
} from "@/lib/contracts-list-navigation";

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
const NativeURL = URL;

function renderRegister(navigationSearch?: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ClientContractRegister
        clientId={CLIENT_ID}
        clientName="Nordea Bank"
        navigationSearch={navigationSearch}
      />
    </QueryClientProvider>,
  );
}

function listCalls() {
  return getMock.mock.calls.filter((c) => c[0] === "/api/contracts");
}

describe("ClientContractRegister — filtry (Okres) + eksport", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    window.history.replaceState({}, "", "/contracts");
    window.sessionStorage.clear();
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
    getMock.mockImplementation((url: string) => {
      if (url === "/api/contracts/register/subcategories") {
        return Promise.resolve({ data: { subcategories: ["Backend", "Frontend"] } });
      }
      return Promise.resolve({
        data: { items: [], total: 0, page: 1, page_size: 50 },
      });
    });

    fetchMock.mockReset();
    fetchMock.mockResolvedValue({ ok: true, blob: async () => new Blob(["x"]) });
    vi.stubGlobal("fetch", fetchMock);
    class TestURL extends NativeURL {
      static createObjectURL = vi.fn(() => "blob:stub");
      static revokeObjectURL = vi.fn();
    }
    vi.stubGlobal("URL", TestURL);
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

  it("odtwarza filtry, stronę, link powrotny i scroll rejestru klienta", async () => {
    const state = {
      search: "Kowalski",
      statusFilter: ["draft"] as const,
      periodFrom: "2026-01-01",
      periodTo: "2026-12-31",
      subcategoryFilter: ["Backend"],
      page: 3,
    };
    const returnTarget = buildClientContractRegisterUrl(
      CLIENT_ID,
      "Nordea Bank",
      { ...state, statusFilter: [...state.statusFilter] },
    );
    const navigationSearch = returnTarget.split("?")[1] ?? "";
    window.history.replaceState({}, "", returnTarget);
    const main = document.createElement("main");
    main.id = "main";
    main.scrollTop = 680;
    document.body.appendChild(main);
    rememberContractsListScroll(returnTarget);
    main.scrollTop = 0;

    getMock.mockImplementation((url: string) => {
      if (url === "/api/contracts/register/subcategories") {
        return Promise.resolve({ data: { subcategories: ["Backend"] } });
      }
      return Promise.resolve({
        data: {
          items: [
            {
              id: 563,
              candidate_id: 77,
              candidate_name: "Jan Kowalski",
              project_code: "NOR-563",
              project_name: "Cloud",
              start_date: "2026-01-01",
              end_date: null,
              engagement_model: "time_based",
              prolongation_status: "unknown",
              status: "draft",
            },
          ],
          total: 101,
          page: 3,
          page_size: 50,
        },
      });
    });

    renderRegister(navigationSearch);

    const link = await screen.findByRole("link", { name: "Jan Kowalski" });
    await waitFor(() => {
      const restored = getMock.mock.calls.find((call) => {
        const params = call[1]?.params;
        return (
          call[0] === "/api/contracts" &&
          params?.page === 3 &&
          params?.q === "Kowalski" &&
          params?.status?.[0] === "draft" &&
          params?.subcategory?.[0] === "Backend"
        );
      });
      expect(restored).toBeTruthy();
      expect(main.scrollTop).toBe(680);
    });
    expect(link.getAttribute("href")).toContain("from=client-register");
    expect(link.getAttribute("href")).toContain(
      `returnTo=${encodeURIComponent(returnTarget)}`,
    );
    main.remove();
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

  it("pobiera podkategorie klienta i przepuszcza wybór do listy oraz eksportu", async () => {
    renderRegister();
    await waitFor(() => expect(listCalls().length).toBeGreaterThan(0));

    // Opcje podkategorii pobrane z osobnego endpointu, scope po kliencie.
    const subcatCall = getMock.mock.calls.find(
      (c) => c[0] === "/api/contracts/register/subcategories",
    );
    expect(subcatCall).toBeTruthy();
    expect(
      (subcatCall![1] as { params: Record<string, unknown> }).params,
    ).toMatchObject({ client_id: CLIENT_ID });

    // Filtr renderuje się dopiero gdy klient ma jakieś podkategorie.
    const trigger = await screen.findByRole("button", {
      name: /wszystkie podkategorie/i,
    });
    fireEvent.click(trigger);
    // Wybór wartości z listy (cmdk CommandItem renderuje etykietę).
    const option = await screen.findByText("Backend");
    fireEvent.click(option);

    // Wybór trafia do zapytania listy jako repeat-param `subcategory`.
    await waitFor(() => {
      const withSub = listCalls().find((c) => {
        const p = (c[1] as { params?: Record<string, unknown> })?.params;
        return (
          Array.isArray(p?.subcategory) &&
          (p!.subcategory as string[]).includes("Backend")
        );
      });
      expect(withSub).toBeTruthy();
    });

    // I do URL eksportu.
    fireEvent.click(
      screen.getByRole("button", { name: /eksportuj do excela/i }),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("subcategory=Backend");
  });

  it("czyści filtr podkategorii przy zmianie klienta (nie przenosi go na nowego)", async () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
    });
    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <ClientContractRegister clientId={42} clientName="Klient A" />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(listCalls().length).toBeGreaterThan(0));

    // Wybierz podkategorię u klienta 42.
    fireEvent.click(
      await screen.findByRole("button", { name: /wszystkie podkategorie/i }),
    );
    fireEvent.click(await screen.findByText("Backend"));
    await waitFor(() => {
      const withSub = listCalls().find((c) => {
        const p = (c[1] as { params?: Record<string, unknown> })?.params;
        return (
          p?.client_id === 42 &&
          Array.isArray(p?.subcategory) &&
          (p!.subcategory as string[]).includes("Backend")
        );
      });
      expect(withSub).toBeTruthy();
    });

    getMock.mockClear(); // patrzymy tylko na wywołania PO zmianie klienta

    // Zmiana klienta — ten sam instancja komponentu (brak remountu).
    rerender(
      <QueryClientProvider client={qc}>
        <ClientContractRegister clientId={99} clientName="Klient B" />
      </QueryClientProvider>,
    );

    // Lista nowego klienta NIE niesie starego filtra podkategorii (reset w renderze).
    await waitFor(() => {
      const forB = listCalls().find(
        (c) =>
          (c[1] as { params?: Record<string, unknown> })?.params?.client_id === 99,
      );
      expect(forB).toBeTruthy();
    });
    const bCalls = listCalls().filter(
      (c) =>
        (c[1] as { params?: Record<string, unknown> })?.params?.client_id === 99,
    );
    for (const c of bCalls) {
      expect(
        (c[1] as { params: Record<string, unknown> }).params.subcategory,
      ).toBeUndefined();
    }
  });
});
