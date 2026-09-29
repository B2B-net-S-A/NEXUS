import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useMentionableUsers", () => ({
  useMentionableUsers: () => ({ data: [] }),
}));

import { NotesList } from "../Notes";

const NOW = new Date(2026, 8, 29, 12, 0);

const baseNotes = [
  {
    id: 1,
    type: "note",
    author_id: 5,
    author_name: "Ola Nowak",
    created_at: new Date(2026, 8, 1, 9, 5).toISOString(),
    content: "Nie dzwonić przed 10.",
    pinned_at: new Date(2026, 8, 20).toISOString(),
    job_id: null,
    replies: [],
  },
  {
    id: 2,
    type: "note",
    author_id: 6,
    author_name: "Kamil W.",
    created_at: new Date(2026, 8, 29, 10, 0).toISOString(),
    content: "linia\n".repeat(8),
    job_id: 10,
    job_title: "Java Dev",
    replies: [
      {
        id: 9,
        author_id: 5,
        author_name: "Ola Nowak",
        created_at: new Date(2026, 8, 29, 11, 0).toISOString(),
        content: "Potwierdzone.",
        parent_note_id: 2,
      },
    ],
  },
  {
    id: 3,
    type: "note",
    author_id: null,
    author_name: null,
    created_at: new Date(2026, 7, 1).toISOString(),
    content: "Auto-match 70/100 — kandydat dodany automatycznie.",
    is_system: true,
    job_id: 11,
    job_title: "QA",
    replies: [],
  },
];

function renderList(extra: Partial<React.ComponentProps<typeof NotesList>> = {}) {
  const props = {
    notes: baseNotes,
    onEdit: vi.fn(async () => true),
    onDelete: vi.fn(async () => true),
    onPin: vi.fn(async () => true),
    onReply: vi.fn(async () => true),
    currentUserId: 5,
    now: NOW,
    ...extra,
  };
  render(<NotesList {...props} />);
  return props;
}

describe("NotesList (0399)", () => {
  it("hides system notes behind the toggle and shows the absolute date for older notes", () => {
    renderList();
    expect(screen.queryByText(/Auto-match 70\/100/)).toBeNull();
    expect(screen.getByText("01.09.2026 09:05")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Pokaż systemowe (1)"));
    expect(screen.getByText(/Auto-match 70\/100/)).toBeTruthy();
  });

  it("filters by a recruitment present in the notes", () => {
    renderList();
    const select = screen.getByLabelText("Pokaż notatki z rekrutacji");
    fireEvent.change(select, { target: { value: "10" } });
    expect(screen.queryByText("Nie dzwonić przed 10.")).toBeNull();
    expect(screen.getByText("Potwierdzone.")).toBeTruthy();
  });

  it("collapses a long note behind „Pokaż więcej”", () => {
    renderList();
    const toggle = screen.getByRole("button", { name: "Pokaż więcej" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Pokaż mniej" })).toBeTruthy();
  });

  it("pins and unpins through the shared handler", async () => {
    const props = renderList();
    const pinned = screen.getByRole("article", { name: "Przypięta notatka" });
    fireEvent.click(within(pinned).getByRole("button", { name: "Odepnij notatkę" }));
    await waitFor(() => expect(props.onPin).toHaveBeenCalledWith(1, false));
    const plain = screen.getAllByRole("article", { name: "Notatka" })[0];
    fireEvent.click(within(plain).getByRole("button", { name: "Przypnij notatkę" }));
    await waitFor(() => expect(props.onPin).toHaveBeenCalledWith(2, true));
  });

  it("replies to a note (one level — replies have no reply button)", async () => {
    const props = renderList();
    const thread = screen.getAllByRole("article", { name: "Notatka" })[0];
    expect(within(thread).getAllByRole("button", { name: "Odpowiedz na notatkę" })).toHaveLength(1);
    fireEvent.click(within(thread).getByRole("button", { name: "Odpowiedz na notatkę" }));
    fireEvent.change(screen.getByLabelText("Treść odpowiedzi"), {
      target: { value: "Dzięki!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Odpowiedz" }));
    await waitFor(() => expect(props.onReply).toHaveBeenCalledWith(2, "Dzięki!"));
    // Autor odpowiedzi (5) może ją edytować; notatki głównej (autor 6) — nie.
    expect(within(thread).getAllByRole("button", { name: "Edytuj odpowiedź" })).toHaveLength(1);
    expect(within(thread).queryByRole("button", { name: "Edytuj notatkę" })).toBeNull();
  });

  it("system notes get neither pin nor reply", () => {
    renderList();
    fireEvent.click(screen.getByLabelText("Pokaż systemowe (1)"));
    const system = screen
      .getAllByRole("article", { name: "Notatka" })
      .find((el) => el.textContent?.includes("Auto-match 70/100"));
    expect(system).toBeTruthy();
    expect(within(system!).queryByRole("button", { name: /Przypnij|Odepnij/ })).toBeNull();
    expect(within(system!).queryByRole("button", { name: "Odpowiedz na notatkę" })).toBeNull();
  });

  it("read-only viewer sees no pin, reply or edit buttons", () => {
    renderList({ readOnly: true });
    expect(screen.queryByRole("button", { name: /Przypnij|Odepnij/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Odpowiedz na notatkę" })).toBeNull();
  });
});
