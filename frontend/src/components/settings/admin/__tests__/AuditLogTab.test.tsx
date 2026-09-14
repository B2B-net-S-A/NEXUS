import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuditLogTab, feedActionLabel } from "../AuditLogTab";

/**
 * B16 (audyt Codexa, 14.09.2026): log aktywności admina renderował wiersze
 * ZMYŚLONE z liczników rankingu — `Math.random()` w identyfikatorze obiektu
 * i w dacie, bez oznaczenia „przykład". Zakładka ma czytać prawdziwy feed
 * (`GET /api/activities/feed`) i pokazywać DOKŁADNIE to, co przyszło.
 */

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: mocks.get },
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.PropsWithChildren<{ href: string } & React.HTMLAttributes<HTMLAnchorElement>>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const COMPONENT_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "AuditLogTab.tsx",
);

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuditLogTab />
    </QueryClientProvider>,
  );
}

// Bez „Z" na końcu: `new Date()` czyta to jako czas LOKALNY, więc oczekiwana
// etykieta nie zależy od strefy maszyny, na której biegnie test.
const FEED = [
  {
    id: 101,
    user: "Jan Testowy",
    user_id: 7,
    action: "note_added",
    entity_type: "candidate",
    entity_id: 555,
    entity_name: "Kandydat Przykładowy",
    description: "dodał(a) notatkę kandydata Kandydat Przykładowy",
    timestamp: "2026-09-03T12:34:00",
    link: "/candidates?id=555",
  },
  {
    id: 102,
    user: "Anna Testowa",
    user_id: 8,
    action: "created",
    entity_type: "job",
    entity_id: 42,
    entity_name: "Rekrutacja testowa",
    description: "created ofertę Rekrutacja testowa",
    timestamp: "2026-09-02T08:05:00",
    link: "/jobs/42",
  },
];

describe("AuditLogTab — prawdziwy feed zamiast syntezy", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("nie syntetyzuje wierszy: zero Math.random / Date.now i brak rankingu w źródle", () => {
    const source = fs.readFileSync(COMPONENT_PATH, "utf8");
    expect(source).not.toContain("Math.random");
    expect(source).not.toContain("Date.now(");
    expect(source).not.toContain("/api/activities/leaderboard");
    expect(source).toContain("/api/activities/feed");
  });

  it("renderuje autora, datę DD.MM.RRRR GG:MM i link z odpowiedzi feedu", async () => {
    mocks.get.mockResolvedValue({ data: FEED });
    renderTab();

    expect(await screen.findByText("Jan Testowy")).toBeInTheDocument();
    expect(screen.getByText("03.09.2026 12:34")).toBeInTheDocument();
    expect(screen.getByText("Anna Testowa")).toBeInTheDocument();
    expect(screen.getByText("02.09.2026 08:05")).toBeInTheDocument();
    expect(screen.getByText("dodał(a) notatkę kandydata Kandydat Przykładowy")).toBeInTheDocument();
    expect(screen.getByText("Kandydat #555")).toBeInTheDocument();

    const links = screen.getAllByRole("link", { name: /Otwórz/ });
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["/candidates?id=555", "/jobs/42"]);

    expect(mocks.get).toHaveBeenCalledWith("/api/activities/feed", { params: { limit: 50 } });
    // Etykiety akcji: kandydat ze słownika osi czasu, reszta z mapy ogólnej.
    expect(screen.getByText("Dodano notatkę")).toBeInTheDocument();
    expect(screen.getByText("Utworzono")).toBeInTheDocument();
  });

  it("awaria pokazuje komunikat błędu z „Spróbuj ponownie”, a nie pusty stan", async () => {
    mocks.get.mockRejectedValueOnce({ response: { status: 500 } });
    mocks.get.mockResolvedValueOnce({ data: FEED });
    renderTab();

    const retry = await screen.findByRole("button", { name: /Spróbuj ponownie/ });
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("Brak zdarzeń w logu aktywności")).not.toBeInTheDocument();

    await userEvent.click(retry);
    expect(await screen.findByText("Jan Testowy")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledTimes(2);
  });

  it("403 to brak uprawnień, nie pustka", async () => {
    mocks.get.mockRejectedValue({ response: { status: 403 } });
    renderTab();

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByText("Brak zdarzeń w logu aktywności")).not.toBeInTheDocument();
  });

  it("pusty feed (sukces, zero wierszy) daje pusty stan", async () => {
    mocks.get.mockResolvedValue({ data: [] });
    renderTab();

    expect(await screen.findByText("Brak zdarzeń w logu aktywności")).toBeInTheDocument();
  });

  it("„Pokaż więcej” podnosi limit do sufitu feedu (100)", async () => {
    const fullPage = Array.from({ length: 50 }, (_, i) => ({
      ...FEED[0],
      id: 1000 + i,
      user: `Osoba ${i}`,
    }));
    mocks.get.mockResolvedValue({ data: fullPage });
    renderTab();

    const more = await screen.findByRole("button", { name: "Pokaż więcej" });
    await userEvent.click(more);

    await waitFor(() =>
      expect(mocks.get).toHaveBeenCalledWith("/api/activities/feed", { params: { limit: 100 } }),
    );
  });

  it("niepełna strona nie oferuje „Pokaż więcej”", async () => {
    mocks.get.mockResolvedValue({ data: FEED });
    renderTab();

    await screen.findByText("Jan Testowy");
    expect(screen.queryByRole("button", { name: "Pokaż więcej" })).not.toBeInTheDocument();
  });
});

describe("feedActionLabel", () => {
  it("nieznany slug nigdy nie wraca dosłownie", () => {
    expect(feedActionLabel("created", "job")).toBe("Utworzono");
    expect(feedActionLabel("created", "candidate")).toBe("Utworzono profil kandydata");
    expect(feedActionLabel("some_unknown_action", "client")).toBe("Zdarzenie systemowe");
  });
});
