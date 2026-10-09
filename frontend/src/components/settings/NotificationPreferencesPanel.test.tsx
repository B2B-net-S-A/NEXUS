import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationPreferencesPanel } from "@/components/settings/NotificationPreferencesPanel";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn(), put: vi.fn(), patch: vi.fn() },
}));

const categories = [
  {
    key: "mentions",
    label: "Wzmianki (@)",
    description: "Ktoś oznaczył Cię w notatce albo na czacie.",
    mandatory: true,
    muted: false,
    received_30d: 4,
  },
  {
    key: "reminders",
    label: "Zaległości i przypomnienia",
    description: "Kandydat stoi na etapie od kilku dni.",
    mandatory: false,
    muted: false,
    received_30d: 312,
  },
];

const USER_PREFERENCES = {
  kpi_coach_enabled: true,
  daily_digest_email_enabled: true,
  daily_digest_email_available: true,
};

/** Dwa odczyty panelu: kategorie dzwonka i własne przełączniki konta. */
function mockReads(
  preferences: Record<string, unknown> | Error,
  userPreferences: Record<string, unknown> | Error = {
    ...USER_PREFERENCES,
    daily_digest_email_available: false,
  },
) {
  vi.mocked(api.get).mockImplementation(async (url: string) => {
    const body = url === "/api/users/me/preferences" ? userPreferences : preferences;
    if (body instanceof Error) throw body;
    return { data: body } as never;
  });
}

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <NotificationPreferencesPanel />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

describe("Moje powiadomienia", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    mockReads({ categories });
    vi.mocked(api.put).mockReset();
    vi.mocked(api.patch).mockReset();
  });

  it("pokazuje kategorie z liczbą z 30 dni; obowiązkowej nie da się wyłączyć", async () => {
    renderPanel();
    const mandatory = await screen.findByRole("switch", {
      name: "Wzmianki (@)",
    });
    expect(mandatory).toBeDisabled();
    expect(screen.getByText("Zawsze włączone")).toBeTruthy();
    expect(screen.getByText("312 w ostatnich 30 dniach")).toBeTruthy();
    expect(
      screen.getByRole("switch", { name: "Zaległości i przypomnienia" }),
    ).toBeEnabled();
  });

  it("wyłączenie kategorii zapisuje ją jako wyciszoną", async () => {
    vi.mocked(api.put).mockResolvedValue({
      data: {
        categories: categories.map((c) =>
          c.key === "reminders" ? { ...c, muted: true } : c,
        ),
      },
    } as never);
    const user = renderPanel();
    const toggle = await screen.findByRole("switch", {
      name: "Zaległości i przypomnienia",
    });
    await user.click(toggle);
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        "/api/notifications/preferences/reminders",
        { muted: true },
      ),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("switch", { name: "Zaległości i przypomnienia" }),
      ).toHaveAttribute("aria-checked", "false"),
    );
  });

  it("awaria wczytania mówi o awarii, nie pokazuje pustej listy", async () => {
    mockReads(new Error("boom"));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się wczytać ustawień powiadomień",
    );
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("kategoria wyłączona dla roli: przełącznik stoi na „wyłączone” i nie da się go ruszyć", async () => {
    mockReads({
      categories: categories.map((c) =>
        c.key === "reminders" ? { ...c, role_muted: true } : c,
      ),
    });
    const user = renderPanel();
    const toggle = await screen.findByRole("switch", {
      name: "Zaległości i przypomnienia",
    });
    expect(toggle).toBeDisabled();
    // Konto samo jej nie wyciszyło (`muted: false`), a mimo to nic nie przychodzi.
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(
      screen.getAllByText("Wyłączone dla Twojej roli przez administratora").length,
    ).toBeGreaterThan(0);
    await user.click(toggle);
    expect(api.put).not.toHaveBeenCalled();
  });
});

describe("Moje powiadomienia — poranny skrót mailem", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.put).mockReset();
    vi.mocked(api.patch).mockReset();
  });

  it("wyłączenie skrótu zapisuje go tylko na własnym koncie", async () => {
    mockReads({ categories }, USER_PREFERENCES);
    vi.mocked(api.patch).mockResolvedValue({
      data: { ...USER_PREFERENCES, daily_digest_email_enabled: false },
    } as never);
    const user = renderPanel();
    const toggle = await screen.findByRole("switch", {
      name: "Poranny skrót „Twój dzień w NEXUSIE”",
    });
    expect(toggle).toBeChecked();
    expect(screen.getByText(/Wyłączasz go tylko sobie\./)).toBeInTheDocument();

    await user.click(toggle);
    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith("/api/users/me/preferences", {
        daily_digest_email_enabled: false,
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("switch", { name: "Poranny skrót „Twój dzień w NEXUSIE”" }),
      ).not.toBeChecked(),
    );
    expect(api.put).not.toHaveBeenCalled();
  });

  it("rola, która nigdy nie dostaje skrótu, nie widzi przełącznika", async () => {
    mockReads({ categories }, { ...USER_PREFERENCES, daily_digest_email_available: false });
    renderPanel();
    await screen.findByRole("switch", { name: "Zaległości i przypomnienia" });
    expect(screen.queryByRole("heading", { name: "Maile" })).toBeNull();
    expect(screen.queryByRole("switch", { name: /Poranny skrót/ })).toBeNull();
  });

  it("awaria wczytania przełącznika maili mówi o awarii zamiast go ukrywać", async () => {
    mockReads({ categories }, new Error("boom"));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się wczytać ustawień maili",
    );
    // Kategorie dzwonka wczytały się i zostają na ekranie.
    expect(
      screen.getByRole("switch", { name: "Zaległości i przypomnienia" }),
    ).toBeInTheDocument();
  });

  it("odrzucony zapis zostawia przełącznik włączony i pokazuje błąd", async () => {
    mockReads({ categories }, USER_PREFERENCES);
    vi.mocked(api.patch).mockRejectedValue(new Error("network unavailable"));
    const user = renderPanel();
    await user.click(
      await screen.findByRole("switch", { name: "Poranny skrót „Twój dzień w NEXUSIE”" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się zapisać zmiany.");
    expect(
      screen.getByRole("switch", { name: "Poranny skrót „Twój dzień w NEXUSIE”" }),
    ).toBeChecked();
  });
});
