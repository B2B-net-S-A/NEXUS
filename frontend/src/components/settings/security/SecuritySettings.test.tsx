import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";

import type { SecurityFinding, SecurityOverview } from "./security-model";
import { SecurityOverviewPanel } from "./SecurityOverviewPanel";
import { SecuritySettings } from "./SecuritySettings";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), replaceUrl: vi.fn() }));

vi.mock("@/lib/api", () => {
  const client = { get: mocks.get, post: mocks.post, patch: mocks.patch };
  return { api: client, default: client };
});
vi.mock("next/navigation", () => ({
  usePathname: () => "/settings",
  useSearchParams: () => new URLSearchParams("area=sys&item=security"),
}));
vi.mock("@/lib/url-selection", () => ({ useUrlWriter: () => ({ replaceUrl: mocks.replaceUrl }) }));

const FINDING: SecurityFinding = {
  id: 11,
  source: "ci",
  scanner: "zizmor",
  severity: "high",
  title: "Wstrzyknięcie w run:",
  location: ".github/workflows/deploy.yml:42",
  evidence: "reguła template-injection",
  impact: "Kradzież tokenu z CI",
  steps: ["Przenieś wartość do env"],
  status: "open",
  stored_status: "open",
  exception_expired: false,
  owner_user_id: null,
  exception_reason: null,
  exception_until: null,
  closed_note: null,
  closed_at: null,
  first_seen_at: "2026-11-27T05:30:00Z",
  last_seen_at: "2026-11-27T05:30:00Z",
};

const OVERVIEW: SecurityOverview = {
  today: "2026-11-27",
  workflow_url: "https://github.com/example/repo/actions/workflows/security-weekly.yml",
  tiles: {
    ci: { new: 1, conclusion: "success", run_started_at: "2026-11-23T05:31:00Z", run_url: null, configured: true },
    waiting: { total: 1, by_severity: { high: 1 } },
    traffic: { blocked: 0, events: 0, configured: false },
    logins: { ok: 3, denied: 1 },
  },
  waiting: [FINDING],
  excepted: [],
  recently_closed: [],
  events: [
    { id: 1, source: "ci", kind: "ci_run", severity: "info", summary: "Tygodniowy skan zielony", count: 1, link: null, occurred_at: "2026-11-23T05:31:00Z" },
  ],
  sources: [
    { key: "crowdsec", name: "CrowdSec", where: "serwer NEXUSA", state: "unconfigured", state_label: "nieskonfigurowane", last_at: null, last_on: null, detail: null, link: null },
  ],
  routines_overdue: 1,
  owners: [{ id: 5, name: "Konto Testowe" }],
};

function wrap(ui: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}

describe("SecuritySettings", () => {
  beforeEach(() => vi.clearAllMocks());

  it("pokazuje kafelki, listę, źródło nieskonfigurowane i licznik rutyn po terminie", async () => {
    mocks.get.mockResolvedValue({ data: OVERVIEW });
    wrap(<SecuritySettings />);
    expect(await screen.findByText("Wstrzyknięcie w run:")).toBeInTheDocument();
    expect(screen.getByTestId("security-tile-ci")).toHaveTextContent("1 nowe");
    expect(screen.getByTestId("security-tile-traffic")).toHaveTextContent("CrowdSec jeszcze nie przysłał zdarzeń");
    expect(screen.getByText("nieskonfigurowane")).toBeInTheDocument();
    expect(screen.getByText("Rutyny (1 po terminie)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Uruchom pełny skan" })).toHaveAttribute("href", OVERVIEW.workflow_url);
  });

  it("awaria API nie wygląda jak pusta lista", async () => {
    mocks.get.mockRejectedValue(new AxiosError("boom", "500", undefined, undefined, {
      status: 500, statusText: "x", headers: {}, config: { headers: new AxiosHeaders() }, data: {},
    }));
    wrap(<SecuritySettings />);
    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText(/Nic nie czeka/)).not.toBeInTheDocument();
  });

  it("odmowa 403 mówi, że ekran jest dla administratora", async () => {
    mocks.get.mockRejectedValue(new AxiosError("no", "403", undefined, undefined, {
      status: 403, statusText: "x", headers: {}, config: { headers: new AxiosHeaders() }, data: {},
    }));
    wrap(<SecuritySettings />);
    expect(await screen.findByText(/widzi tylko administrator/)).toBeInTheDocument();
  });
});

describe("panel znaleziska", () => {
  beforeEach(() => vi.clearAllMocks());

  it("wyjątek bez powodu i daty nie idzie do API, z nimi — idzie", async () => {
    wrap(<SecurityOverviewPanel data={OVERVIEW} />);
    fireEvent.click(screen.getByRole("button", { name: "Otwórz" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Kradzież tokenu z CI")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Wyjątek do…" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz wyjątek" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/powód/);
    expect(mocks.post).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText("Powód (obowiązkowy)"), {
      target: { value: "Poprawka w oknie serwisowym 05.12" },
    });
    fireEvent.change(within(dialog).getByLabelText("Do kiedy (najwyżej rok)"), { target: { value: "2026-12-06" } });
    mocks.post.mockResolvedValue({ data: { ...FINDING, status: "excepted" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz wyjątek" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/security/findings/11/exception", {
        reason: "Poprawka w oknie serwisowym 05.12",
        until: "2026-12-06",
      }),
    );
  });

  it("„Zamknij jako naprawione” pyta o potwierdzenie przed zapisem", async () => {
    wrap(<SecurityOverviewPanel data={OVERVIEW} />);
    fireEvent.click(screen.getByRole("button", { name: "Otwórz" }));
    const dialog = await screen.findByRole("dialog");
    mocks.post.mockResolvedValue({ data: { ...FINDING, status: "fixed" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Zamknij jako naprawione" }));
    expect(mocks.post).not.toHaveBeenCalled();
    const confirm = await screen.findByRole("dialog", { name: "Zamknąć jako naprawione?" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Zamknij jako naprawione" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/security/findings/11/close", {}));
  });
});
