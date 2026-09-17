import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import JobChatTab from "@/components/v2/pages/JobChatTab";

const chatApi = vi.hoisted(() => ({
  getMembers: vi.fn(),
  getPinned: vi.fn(),
  listMessages: vi.fn(),
  markRead: vi.fn(),
  sendMessage: vi.fn(),
  editMessage: vi.fn(),
  deleteMessage: vi.fn(),
  pinMessage: vi.fn(),
  unpinMessage: vi.fn(),
  addReaction: vi.fn(),
  removeReaction: vi.fn(),
  getReadBy: vi.fn(),
}));

const navigation = vi.hoisted(() => ({ search: "" }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(navigation.search),
}));

vi.mock("@/lib/api", () => ({ jobChatApi: chatApi }));
vi.mock("@/components/v2/forms/MentionTextarea", () => ({
  MentionTextarea: ({ ariaLabel }: { ariaLabel: string }) => (
    <textarea aria-label={ariaLabel} />
  ),
}));

const message = {
  id: 31,
  job_id: 12,
  content: "Kandydat gotowy do rozmowy z klientem.",
  author: {
    id: 7,
    name: "Anna Nowak",
    email: "anna@example.com",
    role: "recruiter",
  },
  reply_to_message_id: null,
  reply_to_preview: null,
  is_edited: false,
  edited_at: null,
  is_deleted: false,
  pinned: true,
  pinned_at: "2026-09-02T08:00:00Z",
  pinned_by: 7,
  mentions: [],
  reactions: [{ emoji: "👍", count: 1, user_ids: [7] }],
  created_at: "2026-09-02T08:00:00Z",
  updated_at: "2026-09-02T08:00:00Z",
};

function renderChat() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <JobChatTab jobId={12} readOnly />
    </QueryClientProvider>,
  );
}

describe("JobChatTab read-only", () => {
  it("renders messages without chat mutations or read receipts", async () => {
    chatApi.getMembers.mockResolvedValue({ data: [message.author] });
    chatApi.getPinned.mockResolvedValue({ data: [message] });
    chatApi.listMessages.mockResolvedValue({
      data: { items: [message], has_more: false, next_before_id: null },
    });

    renderChat();

    expect(
      await screen.findAllByText("Kandydat gotowy do rozmowy z klientem."),
    ).toHaveLength(2);
    expect(screen.queryByLabelText("Treść wiadomości chatu")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Wyślij" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Odepnij" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Odpowiedz")).not.toBeInTheDocument();
    expect(screen.queryByText("Reakcja")).not.toBeInTheDocument();

    await waitFor(() => expect(chatApi.listMessages).toHaveBeenCalled());
    expect(chatApi.markRead).not.toHaveBeenCalled();
    expect(chatApi.sendMessage).not.toHaveBeenCalled();
    expect(chatApi.addReaction).not.toHaveBeenCalled();
  });
});

describe("JobChatTab — link z powiadomienia `&msg=`", () => {
  afterEach(() => {
    navigation.search = "";
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/");
  });

  it("przewija do wskazanej wiadomości, podświetla ją i zdejmuje `msg` z adresu", async () => {
    const other = { ...message, id: 30, pinned: false, content: "Wcześniejsza wiadomość." };
    const target = { ...message, pinned: false };
    chatApi.getMembers.mockResolvedValue({ data: [message.author] });
    chatApi.getPinned.mockResolvedValue({ data: [] });
    chatApi.listMessages.mockResolvedValue({
      data: { items: [target, other], has_more: false, next_before_id: null },
    });
    navigation.search = "tab=chat&msg=31";
    window.history.replaceState(null, "", "/jobs/12?tab=chat&msg=31");
    const scrollIntoView = vi
      .spyOn(Element.prototype, "scrollIntoView")
      .mockImplementation(() => undefined);

    const { container } = renderChat();

    await screen.findByText("Kandydat gotowy do rozmowy z klientem.");
    await waitFor(() =>
      expect(container.querySelector("#chat-msg-31")).toHaveAttribute(
        "data-highlighted",
        "true",
      ),
    );
    expect(container.querySelector("#chat-msg-30")).not.toHaveAttribute(
      "data-highlighted",
    );
    expect(scrollIntoView).toHaveBeenCalled();
    expect(window.location.search).toBe("?tab=chat");
  });
});
