import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MentionTextarea } from "@/components/v2/forms/MentionTextarea";

const hook = vi.hoisted(() => ({ result: {} as Record<string, unknown> }));
vi.mock("@/hooks/useMentionableUsers", () => ({
  useMentionableUsers: () => hook.result,
}));

// jsdom nie liczy układu — pomiary ukrytej kopii pola podstawiamy. Zero =
// „układ niepoliczony”, czyli zachowanie pola sprzed 12.10.2026.
const mirror = vi.hoisted(() => ({ height: 0, caretTop: 0 }));
vi.mock("@/lib/textarea-mirror", () => ({
  contentScrollHeight: () => mirror.height,
  caretOffsetTop: () => mirror.caretTop,
}));

const users = [
  { id: 1, name: "Marta Nowak", email: "marta@example.com", role: "recruiter" },
  { id: 2, name: "Łukasz Żak", email: "lzak@example.com", role: "delivery_lead" },
  { id: 3, name: "Jan Kowalski", email: "jan@example.com", role: "head_of_recruitment" },
];

function Field({
  onKeyDown,
  clearOnEnter = false,
  autoGrow,
  maxRows,
}: {
  onKeyDown?: () => void;
  clearOnEnter?: boolean;
  autoGrow?: boolean;
  maxRows?: number;
}) {
  const [value, setValue] = useState("");
  return (
    <div data-testid="card" style={{ overflowY: "hidden" }}>
      <MentionTextarea
        value={value}
        onChange={setValue}
        scope={{ kind: "global" }}
        ariaLabel="Treść"
        autoGrow={autoGrow}
        maxRows={maxRows}
        onKeyDown={(e) => {
          onKeyDown?.();
          if (clearOnEnter && e.key === "Enter") setValue("");
        }}
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

/** Krój pola `text-sm`: linia 20 px, padding 8 + 8, ramka 1 + 1 — jsdom sam go nie policzy. */
function stubFieldStyle() {
  vi.spyOn(window, "getComputedStyle").mockReturnValue({
    lineHeight: "20px",
    paddingTop: "8px",
    paddingBottom: "8px",
    borderTopWidth: "1px",
    borderBottomWidth: "1px",
    overflowY: "visible",
  } as CSSStyleDeclaration);
}

beforeEach(() => {
  hook.result = { data: users, isPending: false, isError: false, refetch: vi.fn() };
  mirror.height = 0;
  mirror.caretTop = 0;
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

  it("po wysłaniu Enterem (rodzic czyści pole) lista znika", () => {
    render(<Field clearOnEnter />);
    const field = type("test @xyz");
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(field, { key: "Enter" });
    expect(field.value).toBe("");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("nikt nie pasuje: mówi to; godzina po „@” nie otwiera niczego", () => {
    render(<Field />);
    type("@xyz");
    expect(screen.getByRole("listbox")).toHaveTextContent("Nie ma osoby pasującej do „xyz”.");
    type("spotkanie @10:00");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

describe("MentionTextarea — pole rośnie z tekstem", () => {
  it("ma wysokość treści, a ponad `maxRows` linii przewija się w środku", () => {
    stubFieldStyle();
    render(<Field />);
    mirror.height = 96;
    const field = type("cztery\nlinie\nnotatki\nz rozmowy");
    // Treść z paddingiem 96 px plus ramka — pole jest `border-box`.
    expect(field.style.height).toBe("98px");
    expect(field.style.overflowY).toBe("hidden");

    mirror.height = 400;
    type("bardzo długa notatka");
    // Sufit 10 linii: 10 × 20 + 16, plus ramka.
    expect(field.style.height).toBe("218px");
    expect(field.style.overflowY).toBe("auto");
  });

  it("`maxRows` ustawia sufit", () => {
    stubFieldStyle();
    render(<Field maxRows={3} />);
    mirror.height = 400;
    expect(type("długa notatka").style.height).toBe("78px");
  });

  it("`autoGrow={false}` zostawia wysokość klasom (czat, duże okno notatki)", () => {
    stubFieldStyle();
    mirror.height = 96;
    const view = render(<Field />);
    const field = type("tekst");
    expect(field.style.height).toBe("98px");
    view.rerender(<Field autoGrow={false} />);
    expect(field.style.height).toBe("");
    expect(field.style.overflowY).toBe("");
  });

  it("bez policzonego układu nie ustawia wysokości", () => {
    render(<Field />);
    expect(type("tekst").style.height).toBe("");
  });
});

describe("MentionTextarea — lista przy linii z „@” w wysokim polu", () => {
  function tallField() {
    stubFieldStyle();
    render(<Field autoGrow={false} />);
    const field = screen.getByLabelText("Treść");
    // Duże okno notatki: pole 300 px, pod nim 16 px do dołu okna (768 px) —
    // lista nie zmieści się ani nad całym polem, ani pod nim.
    Object.defineProperty(field, "clientHeight", { value: 300, configurable: true });
    Object.defineProperty(field, "offsetHeight", { value: 302, configurable: true });
    vi.spyOn(field, "getBoundingClientRect").mockReturnValue(rect(450, 752));
    return field;
  }

  it("kursor u góry pola → lista pod linią, nie pod całym polem", () => {
    tallField();
    mirror.caretTop = 8;
    type("@");
    const list = screen.getByRole("listbox");
    expect(list.className).not.toContain("top-full");
    expect(list.className).not.toContain("bottom-full");
    // Linia 8–28 px od góry pola, 4 px odstępu.
    expect(list.style.top).toBe("32px");
    expect(list.style.bottom).toBe("");
  });

  it("kursor u dołu pola → lista nad linią", () => {
    tallField();
    mirror.caretTop = 270;
    type("@");
    const list = screen.getByRole("listbox");
    // Od dołu pola do górnej krawędzi linii: 302 − 270, plus 4 px odstępu.
    expect(list.style.bottom).toBe("36px");
    expect(list.style.top).toBe("");
  });
});
