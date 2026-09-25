import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toast = vi.hoisted(() => ({ showError: vi.fn(), showSuccess: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
const nav = vi.hoisted(() => ({ params: new URLSearchParams(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
  useSearchParams: () => nav.params,
}));
const apiMock = vi.hoisted(() => ({ get: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import JobBoardsCard, { balanceLines } from "../JobBoardsCard";
import { JOB_BOARD_CONNECTION_KEY, type JobBoardConnectionRead } from "@/lib/api/jobPortals";

const ACTIVE: JobBoardConnectionRead = {
  oauth_configured: true,
  status: "active",
  connected_by_name: "[Admin A]",
  connected_at: "2026-09-24T10:00:00Z",
  last_error: null,
  boards: [
    {
      board: "rocketjobs",
      label: "RocketJobs",
      enabled: true,
      organization_unit_id: "ou-1",
      balance: {
        codes: [{ name: "Pakiet 10", remaining: 7, expires_at: null, plan_key: "p10" }],
        subscriptions: [],
      },
      balance_error: null,
    },
    {
      board: "justjoinit",
      label: "JustJoin.IT",
      enabled: false,
      organization_unit_id: null,
      balance: null,
      balance_error: "401 od dostawcy",
    },
  ],
};

function renderCard(connection: JobBoardConnectionRead) {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  qc.setQueryData(JOB_BOARD_CONNECTION_KEY, connection);
  return render(
    <QueryClientProvider client={qc}>
      <JobBoardsCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  nav.params = new URLSearchParams();
  vi.clearAllMocks();
});

describe("JobBoardsCard", () => {
  it("pokazuje kto połączył, saldo i błąd salda", () => {
    renderCard(ACTIVE);
    expect(screen.getByText("Połączone")).toBeInTheDocument();
    expect(screen.getByText("[Admin A]")).toBeInTheDocument();
    expect(screen.getByText("Pakiet 10: 7 ogłoszeń")).toBeInTheDocument();
    expect(screen.getByText("Jednostka organizacyjna: nie ustawiono")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("401 od dostawcy");
    expect(screen.getByText("Publikacja wyłączona")).toBeInTheDocument();
  });

  it("rozłączenie jest dwustopniowe, bez window.confirm", async () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    apiMock.delete.mockResolvedValueOnce({});
    renderCard(ACTIVE);
    fireEvent.click(screen.getByRole("button", { name: /Rozłącz/ }));
    expect(apiMock.delete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Tak, rozłącz" }));
    await waitFor(() => expect(apiMock.delete).toHaveBeenCalledWith("/api/job-boards/jjit/connection"));
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("niepołączone bez OAuth — przycisk wyłączony i ostrzeżenie", () => {
    renderCard({ ...ACTIVE, status: "not_connected", oauth_configured: false, boards: [] });
    expect(screen.getByText("Brak konfiguracji OAuth na serwerze")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Połącz konto/ })).toBeDisabled();
  });

  it("powrót z OAuth: toast i czysty adres", async () => {
    nav.params = new URLSearchParams("item=job-boards&status=error&message=Odmowa%20zgody");
    renderCard(ACTIVE);
    await waitFor(() => expect(toast.showError).toHaveBeenCalledWith("Odmowa zgody"));
    expect(nav.replace).toHaveBeenCalledWith("/settings?item=job-boards");
  });

  it("saldo abonamentu w jednym zdaniu", () => {
    expect(
      balanceLines({
        codes: [],
        subscriptions: [{ id: "s1", remaining: 1, end_date: null, plan_key: null, active: false }],
      }),
    ).toEqual(["Abonament: 1 ogłoszenie · nieaktywny"]);
  });
});
