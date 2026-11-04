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

  it("collapsed Traffit note previews real text, not empty paragraphs", () => {
    const content = [
      "<p>@Anna Nowak</p>",
      "<p>&nbsp;</p>",
      "<p>&nbsp;</p>",
      "<p>Pierwsza linia treści.</p>",
      "<p>&nbsp;</p>",
      "<p>Druga linia treści.</p>",
      "<p>&nbsp;</p>",
      "<p>Trzecia linia treści.</p>",
      "<p>Czwarta linia.</p>",
      "<p>Piąta linia — widoczna dopiero po rozwinięciu.</p>",
    ].join("");
    renderList({
      notes: [
        { id: 40, type: "note", author_id: 6, author_name: "Kamil W.", content, replies: [] },
      ],
    });
    const body = screen.getByText(/Pierwsza linia treści/);
    expect(body.textContent).toBe(
      "@Anna Nowak\nPierwsza linia treści.\nDruga linia treści.\nTrzecia linia treści.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Pokaż więcej" }));
    expect(screen.getByText(/Piąta linia/)).toBeTruthy();
  });

  it("job-scoped list hides the recruitment filter and badge", () => {
    renderList({ hideRecruitment: true, emptyText: "Brak notatek dla tej rekrutacji." });
    expect(screen.queryByLabelText("Pokaż notatki z rekrutacji")).toBeNull();
    expect(screen.queryByText("Java Dev")).toBeNull();
    // Odpowiedź dalej jedzie pod notatką.
    expect(screen.getByText("Potwierdzone.")).toBeTruthy();
  });

  it("zakładka „Automat” pokazuje wpisy systemowe od razu, bez przełącznika", () => {
    renderList({ notes: [baseNotes[2]], includeSystem: true });
    expect(screen.getByText(/Auto-match 70\/100/)).toBeTruthy();
    expect(screen.queryByLabelText(/Pokaż systemowe/)).toBeNull();
  });

  it("mówi, co z notatki trafiło do screeningu, i otwiera screening tej rekrutacji", () => {
    const link = {
      note_id: 2,
      job_id: 10,
      job_title: "Java Dev",
      fields: ["rate", "availability"],
      field_labels: ["Stawka", "Dostępność"],
      answers: 2,
    };
    const onOpenCard = vi.fn();
    renderList({ cardLinks: new Map([[2, link]]), onOpenCard });

    expect(
      screen.getByText("Do screeningu trafiło: stawka, dostępność i 2 odpowiedzi."),
    ).toBeTruthy();
    const buttons = screen.getAllByRole("button", { name: "Screening tej rekrutacji" });
    // Tylko notatka, która zasiliła screening, ma link.
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    expect(onOpenCard).toHaveBeenCalledWith(link);
  });

  it("read-only viewer sees no pin, reply or edit buttons", () => {
    renderList({ readOnly: true });
    expect(screen.queryByRole("button", { name: /Przypnij|Odepnij/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Odpowiedz na notatkę" })).toBeNull();
  });

  it("ikony akcji są w DOM, ale widać je po najechaniu albo fokusie (na dotyku zawsze)", () => {
    renderList();
    const plain = screen.getAllByRole("article", { name: "Notatka" })[0];
    expect(plain.className).toContain("group/note");
    const pin = within(plain).getByRole("button", { name: "Przypnij notatkę" });
    const actions = pin.parentElement as HTMLElement;
    expect(actions.className).toContain("pointer-fine:opacity-0");
    expect(actions.className).toContain("pointer-fine:group-hover/note:opacity-100");
    expect(actions.className).toContain("pointer-fine:group-focus-within/note:opacity-100");
    expect(actions.className).toContain("focus-within:opacity-100");
    // Odpowiedź ma własną grupę — najechanie na wątek nie odsłania jej ikon.
    const replyEdit = within(plain).getByRole("button", { name: "Edytuj odpowiedź" });
    expect((replyEdit.parentElement as HTMLElement).className).toContain(
      "pointer-fine:group-hover/reply:opacity-100",
    );
    // Klawiatura: przyciski zostają w kolejności Tab (bez tabIndex=-1).
    expect(pin.getAttribute("tabindex")).toBeNull();
  });

  it("bez opcji lista zostaje płaska — bez nagłówków miesięcy i „Pokaż starsze” (dok osoby)", () => {
    renderList();
    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.queryByRole("button", { name: /Pokaż starsze/ })).toBeNull();
  });
});

const monthNote = (id: number, created: Date, extra: object = {}) => ({
  id,
  type: "note",
  author_id: 6,
  author_name: "Kamil W.",
  created_at: created.toISOString(),
  content: `Notatka ${id}.`,
  job_id: null,
  replies: [],
  ...extra,
});

describe("NotesList — grupy miesięczne i „Pokaż starsze” (E4, 13.10.2026)", () => {
  // 1 przypięta (lipiec), 4 z września, 3 z sierpnia.
  const notes = [
    monthNote(50, new Date(2026, 6, 3, 9), { pinned_at: new Date(2026, 8, 1).toISOString() }),
    monthNote(51, new Date(2026, 8, 28, 9)),
    monthNote(52, new Date(2026, 8, 20, 9)),
    monthNote(53, new Date(2026, 8, 10, 9)),
    monthNote(54, new Date(2026, 8, 1, 9)),
    monthNote(55, new Date(2026, 7, 30, 9)),
    monthNote(56, new Date(2026, 7, 15, 9)),
    monthNote(57, new Date(2026, 7, 2, 9)),
  ];

  it("przypięte na górze, potem miesiące od najnowszego z liczbą notatek", () => {
    renderList({ notes, groupByMonth: true });
    const headings = screen.getAllByRole("heading").map((h) => h.textContent);
    expect(headings).toEqual(["Przypięte · 1", "Wrzesień 2026 · 4", "Sierpień 2026 · 3"]);
    const pinned = screen.getByRole("region", { name: "Przypięte notatki" });
    expect(within(pinned).getByText("Notatka 50.")).toBeTruthy();
    const august = screen.getByRole("region", { name: "Sierpień 2026" });
    expect(within(august).getAllByRole("article")).toHaveLength(3);
  });

  it("pokazuje N najnowszych bez przypiętych, reszta po „Pokaż starsze (M)”", () => {
    renderList({ notes, groupByMonth: true, initialVisible: 3 });
    expect(screen.getByText("Notatka 50.")).toBeTruthy();
    expect(screen.getByText("Notatka 53.")).toBeTruthy();
    expect(screen.queryByText("Notatka 54.")).toBeNull();
    // Nagłówek mówi o całym miesiącu, także o schowanych.
    expect(screen.getByRole("heading", { name: "Wrzesień 2026 · 4" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: /Sierpień/ })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Pokaż starsze (4)" }));
    expect(screen.getByText("Notatka 57.")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Sierpień 2026 · 3" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Pokaż starsze/ })).toBeNull();
  });

  it("notatka z adresu (`?note=`) leżąca w starszych rozwija listę do niej", () => {
    renderList({ notes, groupByMonth: true, initialVisible: 3, focusedNoteId: 56 });
    expect(screen.getByText("Notatka 56.")).toBeTruthy();
    expect(screen.queryByText("Notatka 57.")).toBeNull();
    expect(screen.getByRole("button", { name: "Pokaż starsze (1)" })).toBeTruthy();
  });

  it("odpowiedź w starszym wątku też rozwija listę do jej notatki", () => {
    const withReply = notes.map((n) =>
      n.id === 57
        ? { ...n, replies: [{ id: 99, author_id: 5, content: "Odpowiedź.", parent_note_id: 57 }] }
        : n,
    );
    renderList({ notes: withReply, groupByMonth: true, initialVisible: 3, focusedNoteId: 99 });
    expect(screen.getByText("Odpowiedź.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Pokaż starsze/ })).toBeNull();
  });
});
