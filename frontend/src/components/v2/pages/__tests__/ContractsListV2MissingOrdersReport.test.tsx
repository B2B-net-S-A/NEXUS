import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";
import { defaultPermissionsForRoles, type Permission } from "@/lib/permissions";
import { useAuthStore, type UserRole } from "@/store/auth";
import {
  permissionSnapshot,
  sectionSnapshot,
} from "@/test/fixtures/permission-snapshot";

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

/**
 * Profil jak z `/api/auth/me`: capability `view_finance` backend wyprowadza
 * z uprawnienia „Moduł Finanse”, więc oba idą w parze.
 */
function setUser(role: string, granted?: Permission[]) {
  const permissions =
    granted ?? [...defaultPermissionsForRoles([role as UserRole])];
  const capabilities = permissions.includes("finance_module")
    ? ["view_finance", "manage_finance"]
    : [];
  useAuthStore.setState({
    user: {
      id: 1,
      email: `${role}@example.com`,
      name: role,
      role,
      roles: [role],
      profile_completed: true,
      profile_completed_at: null,
      force_password_change: false,
      force_password_change_at: null,
      capabilities,
      analytics_capabilities: capabilities,
      effective_action_access: permissionSnapshot(...permissions),
      effective_section_access: sectionSnapshot(permissions),
    },
    hydrated: true,
  } as never);
}

/**
 * Ticket 10: raport kontraktów bez podpiętego zamówienia — uprawnienie
 * „Moduł Finanse” (domyślnie admin i Finanse), jak trasa raportu.
 */
describe("ContractsListV2 — raport kontraktów bez zamówienia", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
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

  it.each(["admin", "finance"])("%s pobiera raport z menu Eksport", async (role) => {
    setUser(role);
    fetchMock.mockResolvedValue({ ok: true, blob: async () => new Blob(["x"]) });
    renderList();

    fireEvent.click(await screen.findByRole("button", { name: /eksport/i }));
    fireEvent.click(screen.getByText(/kontrakty bez zamówienia/i));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/api/contracts/missing-orders-report",
    );
  });

  it("rekruter z nadanym „Modułem Finanse” pobiera raport", async () => {
    setUser("recruiter", ["finance_module"]);
    fetchMock.mockResolvedValue({ ok: true, blob: async () => new Blob(["x"]) });
    renderList();

    fireEvent.click(await screen.findByRole("button", { name: /eksport/i }));
    fireEvent.click(screen.getByText(/kontrakty bez zamówienia/i));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/api/contracts/missing-orders-report",
    );
  });

  it("Delivery Lead (bez „Modułu Finanse”) nie ma eksportu ani raportu", async () => {
    setUser("delivery_lead");
    renderList();

    expect(await screen.findByText(/brak kontraktów spełniających kryteria/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /eksport/i })).toBeNull();
    expect(screen.queryByText(/kontrakty bez zamówienia/i)).toBeNull();
  });

  it("Finanse z wyłączonym „Modułem Finanse” tracą eksport i raport", async () => {
    setUser("finance", ["contracts_orders_edit", "amounts_edit"]);
    renderList();

    expect(await screen.findByText(/brak kontraktów spełniających kryteria/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /eksport/i })).toBeNull();
    expect(screen.queryByText(/kontrakty bez zamówienia/i)).toBeNull();
  });

  it("profil sprzed wdrożenia uprawnień: eksport z capability, raport dopiero z uprawnienia", async () => {
    // Stara sesja ma capability `view_finance`, ale jeszcze bez migawki
    // uprawnień — eksport (trasa po capability) działa od razu, a raport
    // (trasa po uprawnieniu) pojawia się wraz z rolą, która ma je domyślnie.
    useAuthStore.setState({
      user: {
        id: 1,
        email: "dl@example.com",
        name: "Delivery Lead",
        role: "delivery_lead",
        roles: ["delivery_lead"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        capabilities: ["view_finance"],
        analytics_capabilities: ["view_finance"],
      },
      hydrated: true,
    } as never);
    renderList();

    fireEvent.click(await screen.findByRole("button", { name: /eksport/i }));
    expect(screen.getByText(/excel \(\.xlsx\)/i)).toBeInTheDocument();
    expect(screen.queryByText(/kontrakty bez zamówienia/i)).toBeNull();
  });

  it("nieudane pobranie mówi o tym po polsku", async () => {
    setUser("admin");
    fetchMock.mockResolvedValue({ ok: false, blob: async () => new Blob([]) });
    renderList();

    fireEvent.click(await screen.findByRole("button", { name: /eksport/i }));
    fireEvent.click(screen.getByText(/kontrakty bez zamówienia/i));

    expect(
      await screen.findByText(/nie udało się pobrać raportu kontraktów bez zamówienia/i),
    ).toBeInTheDocument();
  });
});
