import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MentionTextarea } from "@/components/v2/forms/MentionTextarea";

const hook = vi.hoisted(() => ({ result: {} as Record<string, unknown> }));
vi.mock("@/hooks/useMentionableUsers", () => ({
  useMentionableUsers: () => hook.result,
}));

const users = [
  { id: 1, name: "Marta Nowak", email: "marta@example.com", role: "recruiter" },
  { id: 2, name: "Łukasz Żak", email: "lzak@example.com", role: "delivery_lead" },
  { id: 3, name: "Jan Kowalski", email: "jan@example.com", role: "head_of_recruitment" },
];

function Field({ onKeyDown }: { onKeyDown?: () => void }) {
  const [value, setValue] = useState("");
  return (
    <div data-testid="card" style={{ overflowY: "hidden" }}>
      <MentionTextarea
        value={value}
        onChange={setValue}
        scope={{ kind: "global" }}
        ariaLabel="Treść"
        onKeyDown={onKeyDown}
      />
    </div>
  );
}

function type(text: string) {
  const field = screen.getByLabelText("Treść") as HTMLTextAreaElement;
  fireEvent.change(field, { target: { value: text, selectionStart: text.length } });
  return field;
}

function rect(top: number, bottom: number): DOMRect {
  return { top, bottom, left: 0, right: 300, width: 300, height: bottom - top, x: 0, y: top, toJSON: () => ({}) };
}

beforeEach(() => {
  hook.result = { data: users, isPending: false, isError: false, refetch: vi.fn() };
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MentionTextarea", () => {
  it("samo „@” otwiera listę osób", () => {
    render(<Field />);
    type("@");
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
      expect.stringContaining("Marta Nowak"),
      expect.stringContaining("Łukasz Żak"),
      expect.stringContaining("Jan Kowalski"),
    ]);
    expect(screen.getByText("Head of Recruitment")).toBeInTheDocument();
  });

  it("szuka po imieniu i nazwisku bez polskich znaków, także ze spacją", () => {
    render(<Field />);
    type("@lukasz");
    expect(screen.getAllByRole("option")).toHaveLength(1);
    type("Hej @Jan Kow");
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getByRole("option")).toHaveTextContent("Jan Kowalski");
  });

  it("Enter wstawia adres osoby i nie trafia do rodzica", () => {
    const parentKeyDown = vi.fn();
    render(<Field onKeyDown={parentKeyDown} />);
    const field = type("Hej @mar");
    fireEvent.keyDown(field, { key: "Enter" });
    expect(field.value).toBe("Hej @marta@example.com ");
    expect(parentKeyDown).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("adres e-mail w tekście nie otwiera listy, a Enter idzie do rodzica", () => {
    const parentKeyDown = vi.fn();
    render(<Field onKeyDown={parentKeyDown} />);
    const field = type("pisz na biuro@fir");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    fireEvent.keyDown(field, { key: "Enter" });
    expect(parentKeyDown).toHaveBeenCalledTimes(1);
  });

  it("pole przy górnej krawędzi karty: lista staje pod polem", () => {
    render(<Field />);
    const field = screen.getByLabelText("Treść");
    vi.spyOn(field, "getBoundingClientRect").mockReturnValue(rect(100, 130));
    vi.spyOn(screen.getByTestId("card"), "getBoundingClientRect").mockReturnValue(rect(90, 700));
    type("@");
    expect(screen.getByRole("listbox").className).toContain("top-full");
  });

  it("pole na dole czatu: lista staje nad polem", () => {
    render(<Field />);
    const field = screen.getByLabelText("Treść");
    vi.spyOn(field, "getBoundingClientRect").mockReturnValue(rect(600, 650));
    vi.spyOn(screen.getByTestId("card"), "getBoundingClientRect").mockReturnValue(rect(90, 660));
    type("@");
    expect(screen.getByRole("listbox").className).toContain("bottom-full");
  });

  it("awaria listy jest komunikatem z ponowieniem, nie ciszą", () => {
    const refetch = vi.fn();
    hook.result = { data: undefined, isPending: false, isError: true, refetch };
    render(<Field />);
    type("@ma");
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się wczytać listy osób.");
    fireEvent.mouseDown(screen.getByRole("button", { name: "Spróbuj ponownie" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("nikt nie pasuje: mówi to; godzina po „@” nie otwiera niczego", () => {
    render(<Field />);
    type("@xyz");
    expect(screen.getByRole("listbox")).toHaveTextContent("Nie ma osoby pasującej do „xyz”.");
    type("spotkanie @10:00");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
