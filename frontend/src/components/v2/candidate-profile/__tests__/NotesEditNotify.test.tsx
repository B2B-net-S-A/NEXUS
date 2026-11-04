import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const USERS = [
  { id: 7, name: "Anna Nowak", email: "anna@b2b.test", role: "delivery_lead" },
  { id: 5, name: "Ewa Wiśniewska", email: "ewa@b2b.test", role: "recruiter" },
];

vi.mock("@/hooks/useMentionableUsers", () => ({
  useMentionableUsers: () => ({ data: USERS }),
}));

import { NotesList } from "../Notes";

function renderNote(content: string) {
  const onEdit = vi.fn(async () => true);
  render(
    <NotesList
      notes={[
        {
          id: 41,
          type: "note",
          author_id: 5,
          author_name: "Ewa Wiśniewska",
          created_at: new Date(2026, 9, 21, 9, 12).toISOString(),
          content,
          job_id: null,
          replies: [],
        },
      ]}
      onEdit={onEdit}
      onDelete={vi.fn(async () => true)}
      currentUserId={5}
      now={new Date(2026, 9, 21, 13, 0)}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Edytuj notatkę" }));
  const field = screen.getByLabelText("Edytuj treść notatki");
  return { onEdit, field };
}

describe("NotesList — „Powiadom oznaczonych o zmianie” (21.10.2026)", () => {
  it("is ticked by default when an already mentioned person stays in the changed note", async () => {
    const { onEdit, field } = renderNote("Prep 2 śr 10:00 @anna@b2b.test");
    expect(screen.queryByLabelText("Powiadom oznaczonych o zmianie")).toBeNull();

    fireEvent.change(field, { target: { value: "Prep 2 czw 14:00 @anna@b2b.test" } });

    const box = screen.getByRole("checkbox", { name: "Powiadom oznaczonych o zmianie" });
    expect(box.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText(/Anna Nowak zobaczy zmianę w „Wiadomościach”/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz i powiadom" }));
    await waitFor(() =>
      expect(onEdit).toHaveBeenCalledWith(41, "Prep 2 czw 14:00 @anna@b2b.test", {
        notifyMentions: true,
      }),
    );
  });

  it("saves without notifying after the author unticks it", async () => {
    const { onEdit, field } = renderNote("Prep 2 śr 10:00 @anna@b2b.test");
    fireEvent.change(field, { target: { value: "Prep 2 śr 10:00, poprawka @anna@b2b.test" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Powiadom oznaczonych o zmianie" }));

    expect(screen.getByText(/Bez powiadomienia/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(onEdit).toHaveBeenCalledWith(41, "Prep 2 śr 10:00, poprawka @anna@b2b.test", {
        notifyMentions: false,
      }),
    );
  });

  it("does not offer it for a note that mentions only its author", () => {
    const { field } = renderNote("Notatka dla siebie @ewa@b2b.test");
    fireEvent.change(field, { target: { value: "Notatka dla siebie, zmiana @ewa@b2b.test" } });
    expect(screen.queryByRole("checkbox", { name: "Powiadom oznaczonych o zmianie" })).toBeNull();
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeTruthy();
  });
});
