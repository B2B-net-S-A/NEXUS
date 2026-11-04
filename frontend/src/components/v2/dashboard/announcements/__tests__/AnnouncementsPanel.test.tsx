/**
 * Panel „Ogłoszenia” na pulpicie (28.10.2026): znika bez ogłoszeń i przy
 * błędzie, „Przeczytane” zapisuje per osoba, przeczytane szarzeje, publikujący
 * widzi „przeczytało N z M” i może zdjąć ogłoszenie, odbiorca — nie.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AnnouncementPublishButton, AnnouncementsPanel } from "../AnnouncementsPanel";

const state = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
const api = vi.hoisted(() => ({
  read: vi.fn(async () => undefined),
  withdraw: vi.fn(async () => ({ id: 1, notified: 0 })),
  invalidate: vi.fn(),
}));
const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
const confirm = vi.hoisted(() => ({ answer: true }));

vi.mock("@/lib/api/announcements", () => ({
  useAnnouncements: () => state.value,
  markAnnouncementRead: api.read,
  withdrawAnnouncement: api.withdraw,
  invalidateAnnouncements: api.invalidate,
  publishAnnouncement: vi.fn(),
  editAnnouncement: vi.fn(),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({}) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: async () => confirm.answer, confirmDialog: null }),
}));

function item(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    title: `Ogłoszenie testowe ${id}`,
    body: "Treść ogłoszenia testowego.",
    visible_until: "2026-11-07",
    audience_roles: [],
    pinned: false,
    important: false,
    author_name: "Anna Testowa",
    created_at: "2026-10-28T16:41:00Z",
    updated_at: "2026-10-28T16:41:00Z",
    for_me: true,
    read: false,
    read_count: null,
    recipient_count: null,
    ...overrides,
  };
}

function list(items: unknown[], can_publish = false) {
  return { isSuccess: true, data: { items, can_publish, audience_roles: ["recruiter", "delivery_lead"] } };
}

describe("AnnouncementsPanel", () => {
  beforeEach(() => {
    api.read.mockClear();
    api.withdraw.mockClear();
    api.invalidate.mockClear();
    confirm.answer = true;
  });

  it("bez ogłoszeń i przy błędzie nic nie renderuje", () => {
    state.value = list([]);
    const empty = render(<AnnouncementsPanel />);
    expect(empty.container).toBeEmptyDOMElement();
    empty.unmount();
    state.value = { isSuccess: false, isError: true };
    const failed = render(<AnnouncementsPanel />);
    expect(failed.container).toBeEmptyDOMElement();
  });

  it("odbiorca oznacza przeczytane, przeczytane jest wyszarzone i bez przycisku", async () => {
    state.value = list([item(1), item(2, { read: true })]);
    render(<AnnouncementsPanel />);
    const rows = screen.getAllByTestId("announcement-row");
    expect(rows[0]).toHaveAttribute("data-read", "false");
    expect(rows[1]).toHaveAttribute("data-read", "true");
    expect(rows[1].className).toContain("text-muted-foreground");
    expect(within(rows[1]).queryByRole("button", { name: "Przeczytane" })).toBeNull();
    expect(within(rows[1]).getByText(/przeczytane$/)).toBeInTheDocument();
    await userEvent.click(within(rows[0]).getByRole("button", { name: "Przeczytane" }));
    expect(api.read).toHaveBeenCalledWith(1);
    expect(api.invalidate).toHaveBeenCalled();
    // Odbiorca nie widzi licznika ani menu „Popraw / Zdejmij”.
    expect(screen.queryByTestId("announcement-read-count")).toBeNull();
    expect(screen.queryByRole("button", { name: /Więcej:/ })).toBeNull();
  });

  it("treść to zwykły tekst — znaczniki nie są interpretowane", () => {
    state.value = list([item(1, { body: "<b>pogrubione</b>" })]);
    render(<AnnouncementsPanel />);
    expect(screen.getByText("<b>pogrubione</b>")).toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();
  });

  it("publikujący widzi przeczytało N z M, odbiorców i zdejmuje ogłoszenie", async () => {
    state.value = list(
      [item(5, { read_count: 3, recipient_count: 12, audience_roles: ["delivery_lead"], for_me: false })],
      true,
    );
    render(<AnnouncementsPanel />);
    expect(screen.getByTestId("announcement-read-count")).toHaveTextContent("przeczytało 3 z 12");
    expect(screen.getByText(/do: Delivery Leadzi/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Przeczytane" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Więcej:/ }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Zdejmij przed terminem" }));
    expect(api.withdraw).toHaveBeenCalledWith(5);
  });

  it("anulowane potwierdzenie nie zdejmuje ogłoszenia", async () => {
    confirm.answer = false;
    state.value = list([item(5, { read_count: 0, recipient_count: 4 })], true);
    render(<AnnouncementsPanel />);
    await userEvent.click(screen.getByRole("button", { name: /Więcej:/ }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Zdejmij przed terminem" }));
    expect(api.withdraw).not.toHaveBeenCalled();
  });

  it("pokazuje najwyżej 3 od razu, resztę pod „Pokaż wszystkie”", async () => {
    state.value = list([1, 2, 3, 4, 5].map((id) => item(id)));
    render(<AnnouncementsPanel />);
    expect(screen.getAllByTestId("announcement-row")).toHaveLength(3);
    await userEvent.click(screen.getByTestId("announcements-toggle"));
    expect(screen.getAllByTestId("announcement-row")).toHaveLength(5);
  });

  it("przycisk „Ogłoszenie” tylko dla publikujących", () => {
    state.value = list([], false);
    const recruiter = render(<AnnouncementPublishButton />);
    expect(recruiter.container).toBeEmptyDOMElement();
    recruiter.unmount();
    state.value = list([], true);
    render(<AnnouncementPublishButton />);
    expect(screen.getByTestId("announcement-new")).toHaveTextContent("Ogłoszenie");
  });
});
