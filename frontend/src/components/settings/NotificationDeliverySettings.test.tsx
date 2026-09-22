import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NotificationDeliveryOverview, NotificationDeliveryUpdate } from "@/lib/api/notificationDelivery";

const mocks = vi.hoisted(() => ({
  user: null as Record<string, unknown> | null,
  get: vi.fn(),
  update: vi.fn(),
}));

vi.mock("@/lib/api/notificationDelivery", () => ({
  notificationDeliveryApi: { get: mocks.get, update: mocks.update },
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) => selector({ user: mocks.user, hydrated: true }),
  hasRole: (user: { roles?: string[] } | null, ...roles: string[]) =>
    !!user && roles.some((role) => user.roles?.includes(role)),
}));

import NotificationDeliverySettings from "./NotificationDeliverySettings";

function overview(): NotificationDeliveryOverview {
  const families = [
    ["chat_unread", "Nieprzeczytana wiadomość"],
    ["mentions", "Wzmianka"],
    ["pipeline_stage", "Zmiana etapu"],
    ["job_deadline", "Termin rekrutacji"],
    ["delivery_alert", "Alert Delivery"],
    ["password_reset", "Reset hasła"],
    ["email_verification", "Weryfikacja adresu"],
    ["password_changed", "Zmiana hasła"],
  ];
  return {
    enabled: false,
    updated_at: null,
    updated_by: null,
    send_not_before: null,
    provider: {
      kind: "graph_app", sender: "powiadomienia@example.test", configured: true,
      observed_status: "degraded", last_success_at: null,
      last_failure_at: "2026-09-22T09:00:00Z", failure_code: "access_denied", cooldown_until: null,
    },
    backlog: { scope: "chat_unread", pending_retry: 7, ready_upper_bound: 0, uncertain: 1, legacy_suppressed: 83 },
    types: families.map(([id, label], index) => ({
      id, label, module: index < 5 ? "Rekrutacja" : "Konto",
      trigger: `Zdarzenie: ${label}.`, recipient_rule: `Przypisany użytkownik — ${label}.`,
      email_enabled: index >= 5, effective_enabled: index >= 5,
      send_not_before: null, channels: id === "delivery_alert" ? ["client_panel", "email"] : index < 5 ? ["in_app", "email"] : ["email"],
      sender: index === 3 ? "rekruter@example.test" : "powiadomienia@example.test",
      editable: index < 5, provider_kind: index === 3 ? "graph_delegated" : "graph_app",
      provider_status: index === 3 ? "unknown" : "degraded",
    })),
    excluded_channels: [
      { id: "manual_m365", label: "Maile wysyłane ręcznie", description: "Wysyłka z własnej skrzynki wymaga osobnej akcji użytkownika." },
      { id: "order_read", label: "Odczyt zamówień", description: "Odczyt skrzynki nie jest wysyłką powiadomień." },
    ],
  };
}

function renderSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><NotificationDeliverySettings /></QueryClientProvider>);
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.user = { role: "admin", roles: ["admin"], effective_section_access: { system_admin: "write" } };
  mocks.get.mockResolvedValue(overview());
});

describe("NotificationDeliverySettings", () => {
  it("nie odczytuje ani nie zapisuje ustawień bez uprawnień administratora", () => {
    mocks.user = { role: "recruiter", roles: ["recruiter"], effective_section_access: { system_admin: "write" } };
    renderSettings();
    expect(screen.getByText("Brak uprawnień")).toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalled();
    expect(mocks.update).not.toHaveBeenCalled();
  });

  it("pokazuje pięć wyłączonych typów i trzy wiadomości bezpieczeństwa bez akcji wysyłki", async () => {
    renderSettings();
    expect(await screen.findByRole("switch", { name: "Automatyczna wysyłka e-mail" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getAllByRole("switch")).toHaveLength(6);
    expect(screen.getAllByText("Bez przełącznika — bezpieczeństwo konta")).toHaveLength(3);
    expect(screen.getByText("Reset hasła")).toBeInTheDocument();
    expect(screen.getByText("rekruter@example.test")).toBeInTheDocument();
    expect(screen.getByText("Zdarzenie: Termin rekrutacji.")).toBeInTheDocument();
    expect(screen.getByText("Przypisany użytkownik — Termin rekrutacji.")).toBeInTheDocument();
    expect(screen.getByText(/Starsze wiadomości są wykluczone z wysyłki/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Kolejka powiadomień czatu" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /test|wyślij|zaległe/i })).not.toBeInTheDocument();
    expect(mocks.update).not.toHaveBeenCalled();
  });

  it("oddziela wyłączoną wysyłkę od problemu dostawcy i nieweryfikowanej skrzynki użytkownika", async () => {
    renderSettings();
    await screen.findByRole("switch", { name: "Automatyczna wysyłka e-mail" });
    expect(screen.getByText(/Konfiguracja jest obecna. Ostatnia obserwacja: problem z wysyłką/)).toBeInTheDocument();
    expect(screen.getByText("Brak potwierdzenia poprawnej wysyłki")).toBeInTheDocument();
    expect(screen.queryByText(/wysyłka działała/)).not.toBeInTheDocument();
  });

  it("pokazuje alerty Delivery w panelu klientów zamiast przypisywać je do dzwonka", async () => {
    renderSettings();
    const row = await screen.findByRole("row", { name: /Alert Delivery/ });
    expect(within(row).getByText("Panel klientów, E-mail")).toBeInTheDocument();
    expect(within(row).queryByText(/Dzwonek NEXUS/)).not.toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: /Nieprzeczytana wiadomość/ })).getByText("Dzwonek NEXUS, E-mail")).toBeInTheDocument();
  });

  it("zapisuje globalne włączenie bez zmiany typów ani wiadomości bezpieczeństwa i odświeża dane", async () => {
    const saved = { ...overview(), enabled: true, send_not_before: "2026-09-22T10:00:00Z" };
    mocks.update.mockImplementation(async () => {
      mocks.get.mockResolvedValue(saved);
      return saved;
    });
    renderSettings();
    fireEvent.click(await screen.findByRole("switch", { name: "Automatyczna wysyłka e-mail" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    const payload = mocks.update.mock.calls[0][0] as NotificationDeliveryUpdate;
    expect(payload.enabled).toBe(true);
    expect(payload.types).toEqual(overview().types.filter((type) => type.editable).map(({ id }) => ({ id, email_enabled: false })));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("switch", { name: "Automatyczna wysyłka e-mail" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText(/Bieżąca wysyłka obejmuje zdarzenia od:/)).toBeInTheDocument();
  });

  it("pozwala skonfigurować pojedynczy typ przy globalnym OFF i pokazuje rzeczywisty brak zgody na wysyłkę", async () => {
    const saved = overview();
    saved.types[1].email_enabled = true;
    mocks.update.mockImplementation(async () => {
      mocks.get.mockResolvedValue(saved);
      return saved;
    });
    renderSettings();
    fireEvent.click(await screen.findByRole("switch", { name: "E-mail: Wzmianka" }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    const payload = mocks.update.mock.calls[0][0] as NotificationDeliveryUpdate;
    expect(payload.enabled).toBe(false);
    expect(payload.types.filter((type) => type.email_enabled)).toEqual([{ id: "mentions", email_enabled: true }]);
    expect(await screen.findByText("Wysyłka globalna jest wyłączona.")).toBeInTheDocument();
  });

  it("nie udaje zapisu, gdy serwer odrzuci zmianę", async () => {
    mocks.update.mockRejectedValue(new Error("network unavailable"));
    renderSettings();
    fireEvent.click(await screen.findByRole("switch", { name: "Automatyczna wysyłka e-mail" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się zapisać ustawień");
    expect(screen.getByRole("switch", { name: "Automatyczna wysyłka e-mail" })).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByText("Ustawienia zapisane.")).not.toBeInTheDocument();
  });

  it("blokuje zapis podczas żądania i nie zmienia przełącznika przed odpowiedzią", async () => {
    mocks.update.mockImplementation(() => new Promise(() => {}));
    renderSettings();
    const toggle = await screen.findByRole("switch", { name: "Automatyczna wysyłka e-mail" });
    fireEvent.click(toggle);
    await screen.findByText("Zapisuję ustawienia…");
    expect(toggle).toBeDisabled();
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("switch", { name: "E-mail: Wzmianka" })).toBeDisabled();
  });

  it.each([403, 500])("błąd GET %s nie pokazuje pustej konfiguracji ani przełączników", async (status) => {
    mocks.get.mockRejectedValue({ response: { status } });
    renderSettings();
    await screen.findByText(status === 403 ? "Brak uprawnień" : "Nie udało się pobrać danych");
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(mocks.update).not.toHaveBeenCalled();
  });

  it("respektuje dostęp tylko do odczytu", async () => {
    mocks.user = { role: "admin", roles: ["admin"], effective_section_access: { system_admin: "read" } };
    renderSettings();
    expect(await screen.findByText("Masz dostęp tylko do odczytu.")).toBeInTheDocument();
    for (const toggle of screen.getAllByRole("switch")) expect(toggle).toBeDisabled();
  });
});
