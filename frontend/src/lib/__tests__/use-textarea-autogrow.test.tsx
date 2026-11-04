import { useRef, useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mirror = vi.hoisted(() => ({ height: 0 }));
vi.mock("@/lib/textarea-mirror", () => ({ contentScrollHeight: () => mirror.height }));

import { useTextareaAutogrow } from "@/lib/use-textarea-autogrow";

function Field({ maxRows = 8 }: { maxRows?: number }) {
  const [text, setText] = useState("");
  const field = useRef<HTMLTextAreaElement | null>(null);
  const [wrapper, setWrapper] = useState<HTMLDivElement | null>(null);
  useTextareaAutogrow(field, wrapper, text, maxRows);
  return (
    <div ref={setWrapper}>
      <textarea ref={field} aria-label="Pole" rows={1} value={text} onChange={(e) => setText(e.target.value)} />
    </div>
  );
}

function stubFieldStyle() {
  vi.spyOn(window, "getComputedStyle").mockReturnValue({
    lineHeight: "20px",
    paddingTop: "6px",
    paddingBottom: "6px",
    borderTopWidth: "1px",
    borderBottomWidth: "1px",
    // `getByRole` pyta o widoczność elementów.
    getPropertyValue: () => "",
  } as unknown as CSSStyleDeclaration);
}

function type(text: string): HTMLTextAreaElement {
  const field = screen.getByRole("textbox", { name: "Pole" }) as HTMLTextAreaElement;
  fireEvent.change(field, { target: { value: text } });
  return field;
}

beforeEach(() => {
  mirror.height = 0;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useTextareaAutogrow — pole listy poprawek rośnie z treścią", () => {
  it("ma wysokość treści, a ponad `maxRows` linii przewija się w środku", () => {
    stubFieldStyle();
    render(<Field />);
    mirror.height = 72;
    const field = type("1. krócej\n2. więcej o Kafce\n3. bez hobby");
    // Treść z paddingiem 72 px plus ramka — pole jest `border-box`.
    expect(field.style.height).toBe("74px");
    expect(field.style.overflowY).toBe("hidden");

    mirror.height = 600;
    type("bardzo długa lista");
    // Sufit 8 linii: 8 × 20 + 12, plus ramka.
    expect(field.style.height).toBe("174px");
    expect(field.style.overflowY).toBe("auto");
  });

  it("`maxRows` ustawia sufit (asystent: 4 linie)", () => {
    stubFieldStyle();
    render(<Field maxRows={4} />);
    mirror.height = 600;
    expect(type("długa lista").style.height).toBe("94px");
  });

  it("bez policzonego układu nie ustawia wysokości", () => {
    render(<Field />);
    expect(type("tekst").style.height).toBe("");
  });
});
