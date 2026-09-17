import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import CandidateChatTab from "@/components/v2/pages/CandidateChatTab";

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
vi.mock("@/lib/api", () => ({ candidateChatApi: chatApi }));
vi.mock("@/components/v2/forms/MentionTextarea", () => ({
  MentionTextarea: ({ ariaLabel }: { ariaLabel: string }) => (
    <textarea aria-label={ariaLabel} />
  ),
}));

function makeMessage(id: number, content: string) {
  return {
    id,
    candidate_id: 44,
    content,
    author: { id: 7, name: "Anna Nowak", email: "anna@example.com", role: "recruiter" },
    reply_to_message_id: null,
    reply_to_preview: null,
    is_edited: false,
    edited_at: null,
    is_deleted: false,
    pinned: false,
    pinned_at: null,
    pinned_by: null,
    mentions: [],
    reactions: [],
    created_at: "2026-09-02T08:00:00Z",
    updated_at: "2026-09-02T08:00:00Z",
  };
}

// Link powiadomienia czatu kandydata: `/candidates/{id}?tab=chat&msg=<id>`.
describe("CandidateChatTab — link z powiadomienia `&msg=`", () => {
  afterEach(() => {
    navigation.search = "";
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/");
  });

  it("podświetla wskazaną wiadomość i zdejmuje `msg` z adresu", async () => {
    chatApi.getMembers.mockResolvedValue({ data: [] });
    chatApi.getPinned.mockResolvedValue({ data: [] });
    chatApi.listMessages.mockResolvedValue({
      data: {
        items: [makeMessage(52, "Wzmianka o Tobie."), makeMessage(51, "Starsza.")],
        has_more: false,
        next_before_id: null,
      },
    });
    navigation.search = "tab=chat&msg=52";
    window.history.replaceState(null, "", "/candidates/44?tab=chat&msg=52");
    vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <CandidateChatTab candidateId={44} readOnly />
      </QueryClientProvider>,
    );

    await screen.findByText("Wzmianka o Tobie.");
    await waitFor(() =>
      expect(container.querySelector("#chat-msg-52")).toHaveAttribute(
        "data-highlighted",
        "true",
      ),
    );
    expect(window.location.search).toBe("?tab=chat");
  });
});
