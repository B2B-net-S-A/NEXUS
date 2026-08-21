import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { DlAlertsSection } from "@/components/v2/dashboard/DlAlertsSection";
import type { DlAlertRead } from "@/lib/api/dlAlerts";

const authState = vi.hoisted(() => ({ role: "delivery_lead" as string }));

vi.mock("@/store/auth", () => ({
  useAuthStore: Object.assign(
    (selector: (s: { user: { role: string } }) => unknown) =>
      selector({ user: authState }),
    { getState: () => ({ token: "t" }) },
  ),
  hasRole: (user: { role?: string } | null, ...roles: string[]) =>
    roles.includes(user?.role ?? ""),
}));

vi.mock("@/lib/api/dlAlerts", () => ({
  dlAlertsApi: { list: vi.fn(), markHandled: vi.fn() },
  dlAlertsExportUrl: (scope: string) => `/api/dl-alerts/export?scope=${scope}`,
}));

import { dlAlertsApi } from "@/lib/api/dlAlerts";

function alert(overrides: Partial<DlAlertRead> = {}): DlAlertRead {
  return {
    id: 1,
    alert_type: "cost_order_exhausted",
    alert_type_label: "Zamówienie kosztowe wyczerpane",
    status: "new",
    status_label: "Nowe",
    client_id: 12,
    client_name: "Polkomtel",
    order_group_id: 5,
    order_id: null,
    title: "Polkomtel — zamówienie 4500719650 wyczerpane",
    message:
      "⚠ Polkomtel — zamówienie 4500719650 zostało wyczerpane i przeniesione do zakończonych.",
    link: "/clients/12?tab=zamowienia",
    recipient_user_id: 3,
    recipient_name: "Anna Delivery",
    created_at: "2026-08-01T10:00:00Z",
    handled_at: null,
    handled_by_user_id: null,
    handled_by_name: null,
    reaction_seconds: null,
    reaction_label: "—",
    ...overrides,
  };
}

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <DlAlertsSection />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  authState.role = "delivery_lead";
  vi.mocked(dlAlertsApi.list).mockResolvedValue({
    data: { alerts: [alert()], total_new: 1, total_handled: 4 },
  } as never);
  vi.mocked(dlAlertsApi.markHandled).mockResolvedValue({
    data: alert({ status: "handled" }),
  } as never);
});

describe("DlAlertsSection", () => {
  it("pokazuje powiadomienia z licznikami obu zakładek", async () => {
    renderSection();
    expect(await screen.findByText(/zostało wyczerpane/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Nowe \(1\)/ })).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: /Historia \(4\)/ }),
    ).toBeInTheDocument();
  });

  it("oznaczenie jako obsłużone woła API, a nie kasuje wpisu lokalnie", async () => {
    renderSection();
    await userEvent.click(
      await screen.findByRole("button", { name: /Oznacz jako obsłużone/i }),
    );
    await waitFor(() =>
      expect(dlAlertsApi.markHandled).toHaveBeenCalledWith(1),
    );
  });

  it("zakładka Historia pyta serwer o wpisy obsłużone", async () => {
    renderSection();
    await screen.findByText(/zostało wyczerpane/);
    await userEvent.click(screen.getByRole("tab", { name: /Historia/ }));
    await waitFor(() =>
      expect(dlAlertsApi.list).toHaveBeenCalledWith("handled"),
    );
  });

  it("awaria pobrania NIE renderuje się jako pusty stan", async () => {
    vi.mocked(dlAlertsApi.list).mockRejectedValue(new Error("boom"));
    renderSection();
    expect(
      await screen.findByText(/Nie udało się wczytać powiadomień/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Brak nowych powiadomień/i),
    ).not.toBeInTheDocument();
  });

  it("eksport zbiorczy widzą tylko Administrator i Finanse", async () => {
    renderSection();
    await screen.findByText(/zostało wyczerpane/);
    expect(
      screen.queryByRole("button", { name: /Eksport zbiorczy/i }),
    ).not.toBeInTheDocument();
  });

  it("admin widzi eksport zbiorczy obok własnego", async () => {
    authState.role = "admin";
    renderSection();
    await screen.findByText(/zostało wyczerpane/);
    expect(
      screen.getByRole("button", { name: /Eksport zbiorczy/i }),
    ).toBeInTheDocument();
  });
});
