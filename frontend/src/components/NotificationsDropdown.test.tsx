import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationsDropdown } from "@/components/NotificationsDropdown";
import { notificationsApi } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  notificationsApi: { list: vi.fn(), markRead: vi.fn(), markAllRead: vi.fn() },
}));
vi.mock("@/hooks/useNotifications", () => ({
  useNotifications: () => ({ unreadCount: 0, clearUnread: vi.fn(), wsConnected: true }),
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

    await user.click(screen.getByRole("button", { name: "Pokaż więcej" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(50));
    expect(listNotifications).toHaveBeenLastCalledWith(50);

    await user.click(screen.getByRole("button", { name: "Pokaż więcej" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(60));
    expect(listNotifications).toHaveBeenLastCalledWith(200);
    // 60 < 200 — to już wszystko: bez przycisku i bez „Pokazano 200".
    expect(screen.queryByRole("button", { name: "Pokaż więcej" })).toBeNull();
    expect(screen.queryByText(/Pokazano/)).toBeNull();
    expect(screen.getByRole("button", { name: "Zamknij" })).toBeInTheDocument();
  });

  it("krótsza lista niż limit nie pokazuje „Pokaż więcej”", async () => {
    mockAvailable(5);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(5));
    expect(screen.queryByRole("button", { name: "Pokaż więcej" })).toBeNull();
  });

  it("na suficie 200 mówi wprost, że pokazano 200 najnowszych", async () => {
    mockAvailable(1000);
    const user = userEvent.setup();
    renderDropdown();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(20));
    await user.click(screen.getByRole("button", { name: "Pokaż więcej" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(50));
    await user.click(screen.getByRole("button", { name: "Pokaż więcej" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(200));
    expect(screen.queryByRole("button", { name: "Pokaż więcej" })).toBeNull();
    expect(screen.getByText("Pokazano 200 najnowszych")).toBeInTheDocument();
  });
});
