import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationPreferencesPanel } from "@/components/settings/NotificationPreferencesPanel";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: { get: vi.fn(), put: vi.fn() } }));

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
    vi.mocked(api.get).mockResolvedValue({ data: { categories } } as never);
    vi.mocked(api.put).mockReset();
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
    vi.mocked(api.get).mockRejectedValue(new Error("boom"));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się wczytać ustawień powiadomień",
    );
    expect(screen.queryByRole("switch")).toBeNull();
  });
});
