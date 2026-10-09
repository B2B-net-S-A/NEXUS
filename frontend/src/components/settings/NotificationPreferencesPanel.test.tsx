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

const MY_EMAILS = {
  channel_ready: true,
  items: [
    {
      id: "daily_digest",
      label: "Poranny skrót „Twój dzień w NEXUSIE”",
      description: "Dzień roboczy od 8:00.",
      company_enabled: true,
      self_enabled: true,
      receiving: true,
      state: "on",
      note: null,
    },
    {
      id: "cv_returned",
      label: "CV wróciło do poprawy",
      description: "Delivery Lead cofnął kandydata z „QC CV”.",
      company_enabled: true,
      self_enabled: true,
      receiving: true,
      state: "on",
      note: null,
    },
    {
      id: "mentions",
      label: "Wzmianki w notatkach",
      description: "Oznaczenie przez @wzmiankę.",
      company_enabled: false,
      self_enabled: true,
      receiving: false,
      state: "company_off",
      note: "Wyłączone dla całej firmy przez administratora — teraz nikt go nie dostaje.",
    },
  ],
  not_applicable: [{ id: "system_failure", label: "Awaria automatu" }],
  always_on: [{ id: "password_reset", label: "Reset hasła", description: "Żądanie resetu." }],
};

const EMAILS_URL = "/api/users/me/email-notifications";

/** Dwa odczyty panelu: kategorie dzwonka i „Maile do Ciebie”. */
function mockReads(
  preferences: Record<string, unknown> | Error,
  myEmails: Record<string, unknown> | Error = MY_EMAILS,
) {
  vi.mocked(api.get).mockImplementation(async (url: string) => {
    const body = url === EMAILS_URL ? myEmails : preferences;
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
    expect(
      screen.queryByRole("switch", { name: "Zaległości i przypomnienia" }),
    ).toBeNull();
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

describe("Moje powiadomienia — „Maile do Ciebie”", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.put).mockReset();
    vi.mocked(api.patch).mockReset();
    mockReads({ categories });
  });

  it("pokazuje maile konta z opisem, a pozostałe jako niedotyczące roli", async () => {
    renderPanel();
    expect(await screen.findByRole("heading", { name: "Maile do Ciebie" })).toBeInTheDocument();
    expect(
      await screen.findByRole("switch", { name: "CV wróciło do poprawy" }),
    ).toBeChecked();
    expect(screen.getByText("Delivery Lead cofnął kandydata z „QC CV”.")).toBeInTheDocument();
    expect(screen.getByText("Maile, które nie dotyczą Twojej roli (1)")).toBeInTheDocument();
    expect(screen.getByText("Awaria automatu")).toBeInTheDocument();
    expect(
      screen.getByText("Zawsze przychodzą maile o bezpieczeństwie konta: reset hasła."),
    ).toBeInTheDocument();
  });

  it("mail wyłączony firmowo mówi to przy wierszu, a wybór konta zostaje do ustawienia", async () => {
    renderPanel();
    const toggle = await screen.findByRole("switch", { name: "Wzmianki w notatkach" });
    expect(toggle).toBeChecked();
    expect(toggle).toBeEnabled();
    expect(toggle).toHaveAccessibleDescription(
      "Wyłączone dla całej firmy przez administratora — teraz nikt go nie dostaje.",
    );
  });

  it("wyłączenie maila zapisuje go tylko na własnym koncie", async () => {
    vi.mocked(api.put).mockResolvedValue({
      data: {
        ...MY_EMAILS,
        items: MY_EMAILS.items.map((item) =>
          item.id === "cv_returned"
            ? {
                ...item,
                self_enabled: false,
                receiving: false,
                state: "self_off",
                note: "Wyłączone przez Ciebie.",
              }
            : item,
        ),
      },
    } as never);
    const user = renderPanel();
    await user.click(await screen.findByRole("switch", { name: "CV wróciło do poprawy" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        "/api/users/me/email-notifications/cv_returned",
        { enabled: false },
      ),
    );
    await waitFor(() =>
      expect(screen.getByRole("switch", { name: "CV wróciło do poprawy" })).not.toBeChecked(),
    );
    // Pozycja przełącznika mówi wszystko — bez drugiego zdania „wyłączone przez Ciebie”.
    expect(screen.queryByText("Wyłączone przez Ciebie.")).toBeNull();
    expect(api.patch).not.toHaveBeenCalled();
  });

  it("awaria wczytania maili mówi o awarii zamiast pokazywać pustą listę", async () => {
    mockReads({ categories }, new Error("boom"));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się wczytać ustawień maili",
    );
    expect(screen.queryByText(/nie trafia żaden/)).toBeNull();
    // Kategorie dzwonka wczytały się i zostają na ekranie.
    expect(
      await screen.findByRole("switch", { name: "Zaległości i przypomnienia" }),
    ).toBeInTheDocument();
  });

  it("odrzucony zapis zostawia przełącznik włączony i pokazuje błąd", async () => {
    vi.mocked(api.put).mockRejectedValue(new Error("network unavailable"));
    const user = renderPanel();
    await user.click(await screen.findByRole("switch", { name: "CV wróciło do poprawy" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się zapisać zmiany.");
    expect(screen.getByRole("switch", { name: "CV wróciło do poprawy" })).toBeChecked();
  });

  it("konto bez żadnego maila i bez kanału wysyłki dostaje zdania, nie pustkę", async () => {
    mockReads(
      { categories },
      { channel_ready: false, items: [], not_applicable: [], always_on: [] },
    );
    renderPanel();
    expect(
      await screen.findByText("Na Twoje konto nie trafia żaden z automatycznych maili NEXUSA."),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Wysyłka maili z NEXUSA nie jest teraz skonfigurowana",
    );
  });
});
