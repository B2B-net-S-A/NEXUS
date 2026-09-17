import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationsDropdown } from "@/components/NotificationsDropdown";
import { notificationsApi } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  notificationsApi: { list: vi.fn(), markRead: vi.fn(), markAllRead: vi.fn() },
}));
const hookState = vi.hoisted(() => ({ unreadCount: 0, clearUnread: vi.fn() }));
vi.mock("@/hooks/useNotifications", () => ({
  useNotifications: () => ({
    unreadCount: hookState.unreadCount,
    clearUnread: hookState.clearUnread,
    wsConnected: true,
  }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector?: (state: unknown) => unknown) => {
    const state = { user: { id: 1, authorization_version: 1 } };
    return selector ? selector(state) : state;
  },
}));
vi.mock("@/components/feedback/InterviewFeedbackModal", () => ({
  InterviewFeedbackModal: () => null,
}));

const listNotifications = vi.mocked(notificationsApi.list);

function makeItems(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    user_id: 1,
    title: "Powiadomienie " + (i + 1),
    message: "treść",
    link: null,
    notification_type: "candidate_added",
    is_read: false,
    created_at: "2026-09-01T08:00:00Z",
  }));
}

function mockAvailable(available: number) {
  listNotifications.mockImplementation(async (limit?: number) => ({
    data: { items: makeItems(Math.min(limit ?? 20, available)), unread_count: 0 },
  }) as unknown as Awaited<ReturnType<typeof notificationsApi.list>>);
}

function renderDropdown() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NotificationsDropdown />
    </QueryClientProvider>,
  );
}

// Pozycje listy mają `role="button"` (obsługa klawiatury), więc zapytania po
// roli liczyłyby nazwę dostępną dla 200 wierszy — przyciski stopki szukamy
// po tekście, żeby test nie mierzył wydajności jsdom.
// B51: dzwonek pokazywał 20 pozycji i kończył listę samym „Zamknij" — przy
// liczniku ponad tysiąca nieprzeczytanych starsze były niedostępne.
describe("NotificationsDropdown — „Pokaż więcej”", () => {
  beforeEach(() => {
    listNotifications.mockReset();
  });

  it("doładowuje 20 → 50 → 200 i chowa przycisk, gdy lista się skończy", async () => {
    mockAvailable(60);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));

    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(20));
    expect(listNotifications).toHaveBeenLastCalledWith(20);

    await user.click(screen.getByText("Pokaż więcej"));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(50));
    expect(listNotifications).toHaveBeenLastCalledWith(50);

    await user.click(screen.getByText("Pokaż więcej"));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(60));
    expect(listNotifications).toHaveBeenLastCalledWith(200);
    // 60 < 200 — to już wszystko: bez przycisku i bez „Pokazano 200".
    expect(screen.queryByText("Pokaż więcej")).toBeNull();
    expect(screen.queryByText(/Pokazano/)).toBeNull();
    expect(screen.getByText("Zamknij")).toBeInTheDocument();
   }, 15_000);

  it("krótsza lista niż limit nie pokazuje „Pokaż więcej”", async () => {
    mockAvailable(5);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(5));
    expect(screen.queryByText("Pokaż więcej")).toBeNull();
  });

  it("na suficie 200 mówi wprost, że pokazano 200 najnowszych", async () => {
    mockAvailable(1000);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(20));
    await user.click(screen.getByText("Pokaż więcej"));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(50));
    await user.click(screen.getByText("Pokaż więcej"));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(200));
    expect(screen.queryByText("Pokaż więcej")).toBeNull();
    expect(screen.getByText("Pokazano 200 najnowszych")).toBeInTheDocument();
   }, 15_000);
});

describe("NotificationsDropdown — dostępność, licznik i ładowanie", () => {
  beforeEach(() => {
    listNotifications.mockReset();
    vi.mocked(notificationsApi.markRead).mockReset();
    vi.mocked(notificationsApi.markRead).mockResolvedValue(
      {} as Awaited<ReturnType<typeof notificationsApi.markRead>>,
    );
    hookState.unreadCount = 0;
    hookState.clearUnread.mockReset();
  });

  it("pozycję da się otworzyć klawiaturą (Enter) — oznacza ją jako przeczytaną", async () => {
    mockAvailable(2);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    const item = await screen.findByRole("button", { name: /Powiadomienie 1\b/ });
    item.focus();
    await user.keyboard("{Enter}");
    expect(notificationsApi.markRead).toHaveBeenCalledWith(1);
  });

  it("przypomnienie w zastępstwie ma etykietę", async () => {
    listNotifications.mockResolvedValue({
      data: {
        items: [{ ...makeItems(1)[0], user_id: 2, on_behalf_of_name: "Anna Nowak" }],
        unread_count: 1,
      },
    } as unknown as Awaited<ReturnType<typeof notificationsApi.list>>);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    expect(await screen.findByText("w zastępstwie za Anna Nowak")).toBeInTheDocument();
  });

  it("po odświeżeniu listy zeruje deltę z gniazda (bez widmowego licznika)", async () => {
    mockAvailable(1);
    hookState.unreadCount = 7;
    renderDropdown();
    await waitFor(() => expect(hookState.clearUnread).toHaveBeenCalled());
  });

  it("„Pokaż więcej” nie znika w trakcie doładowania", async () => {
    const gate: { release: () => void } = { release: () => undefined };
    listNotifications.mockImplementation(async (limit?: number) => {
      if ((limit ?? 20) > 20) {
        await new Promise<void>((resolve) => {
          gate.release = resolve;
        });
      }
      return {
        data: { items: makeItems(Math.min(limit ?? 20, 60)), unread_count: 0 },
      } as unknown as Awaited<ReturnType<typeof notificationsApi.list>>;
    });
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(20));

    await user.click(screen.getByRole("button", { name: "Pokaż więcej" }));
    const loading = await screen.findByRole("button", { name: "Ładowanie…" });
    expect(loading).toBeDisabled();
    expect(screen.getAllByRole("listitem")).toHaveLength(20);

    gate.release();
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(50));
  });
});
