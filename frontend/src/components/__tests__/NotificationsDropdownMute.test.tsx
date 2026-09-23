import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationsDropdown } from "@/components/NotificationsDropdown";
import { api, notificationsApi } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: { put: vi.fn(), get: vi.fn() },
  notificationsApi: { list: vi.fn(), markRead: vi.fn(), markAllRead: vi.fn() },
}));
vi.mock("@/hooks/useNotifications", () => ({
  useNotifications: () => ({ unreadCount: 0, clearUnread: vi.fn(), wsConnected: true }),
}));
const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector?: (state: unknown) => unknown) => {
    const state = { user: { id: 1, authorization_version: 1 } };
    return selector ? selector(state) : state;
  },
}));
vi.mock("@/components/feedback/InterviewFeedbackModal", () => ({
  InterviewFeedbackModal: () => null,
}));

const items = [
  {
    id: 1,
    user_id: 1,
    title: "Kandydat utknął",
    message: "Anna stoi na etapie 8 dni",
    link: null,
    notification_type: "stage_stuck_7d",
    is_read: false,
    created_at: "2026-09-22T08:00:00Z",
    category: "reminders",
    category_label: "Zaległości i przypomnienia",
    category_mutable: true,
  },
  {
    id: 2,
    user_id: 1,
    title: "Wzmianka",
    message: "Ktoś Cię oznaczył",
    link: null,
    notification_type: "note_mention",
    is_read: false,
    created_at: "2026-09-22T08:00:00Z",
    category: "mentions",
    category_label: "Wzmianki (@)",
    category_mutable: false,
  },
];

function renderOpen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NotificationsDropdown />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

describe("dzwonek — „Nie pokazuj takich”", () => {
  beforeEach(() => {
    vi.mocked(notificationsApi.list).mockResolvedValue({
      data: { items, unread_count: 2 },
    } as never);
    vi.mocked(api.put).mockReset();
    vi.mocked(api.put).mockResolvedValue({ data: { categories: [] } } as never);
    push.mockReset();
  });

  it("wycisza kategorię tylko dla kategorii, które wolno wyłączyć, i pozwala cofnąć", async () => {
    const user = renderOpen();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    await screen.findByText("Kandydat utknął");

    expect(
      screen.queryByRole("button", { name: /Nie pokazuj takich: Wzmianki/ }),
    ).toBeNull();

    await user.click(
      screen.getByRole("button", {
        name: "Nie pokazuj takich: Zaległości i przypomnienia",
      }),
    );
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        "/api/notifications/preferences/reminders",
        { muted: true },
      ),
    );
    expect(await screen.findByText("Zaległości i przypomnienia")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Wyłączono");

    await user.click(screen.getByRole("button", { name: "Cofnij" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenLastCalledWith(
        "/api/notifications/preferences/reminders",
        { muted: false },
      ),
    );
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  });

  it("prowadzi do ustawień powiadomień", async () => {
    const user = renderOpen();
    await user.click(screen.getByRole("button", { name: "Powiadomienia" }));
    await user.click(screen.getByRole("button", { name: "Ustawienia powiadomień" }));
    expect(push).toHaveBeenCalledWith("/settings?item=my-notifications");
  });
});
