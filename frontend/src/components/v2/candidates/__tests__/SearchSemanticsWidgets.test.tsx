import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { SkillBucketsField } from "@/components/v2/candidates/SkillBucketsField";
import { TextInterpretationLine } from "@/components/v2/candidates/TextInterpretationLine";
import {
  HideUnknownToggle,
  UnknownFieldBadges,
} from "@/components/v2/candidates/UnknownFieldBadges";
import type { SkillBucketsValue } from "@/lib/candidate-search-semantics";

function Buckets({ onChange }: { onChange: (v: SkillBucketsValue) => void }) {
  const [value, setValue] = useState<SkillBucketsValue>({
    required: [],
    preferred: [],
    excluded: [],
  });
  return (
    <SkillBucketsField
      value={value}
      onChange={(next) => {
        onChange(next);
        setValue(next);
      }}
    />
  );
}

describe("SkillBucketsField", () => {
  it("bez wyboru kubełka pozycja trafia do „Musi mieć”, `A OR B` to grupa", () => {
    const onChange = vi.fn();
    render(<Buckets onChange={onChange} />);
    const input = screen.getByLabelText("Dodaj umiejętność");
    fireEvent.change(input, { target: { value: "Java OR Kotlin" } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith({
      required: ["Java|Kotlin"],
      preferred: [],
      excluded: [],
    });
    expect(screen.getByText("Java lub Kotlin")).toBeInTheDocument();
  });

  it("duplikat w innym kubełku jest odrzucany z komunikatem", () => {
    const onChange = vi.fn();
    render(<Buckets onChange={onChange} />);
    const input = screen.getByLabelText("Dodaj umiejętność");
    fireEvent.change(input, { target: { value: "Java" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(screen.getByRole("radio", { name: "Wyklucz" }));
    fireEvent.change(input, { target: { value: "java" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status").textContent).toMatch(/jest już w „Musi mieć”/);
  });

  it("usunięcie chipu zdejmuje pozycję z kubełka", () => {
    const onChange = vi.fn();
    render(<Buckets onChange={onChange} />);
    const input = screen.getByLabelText("Dodaj umiejętność");
    fireEvent.change(input, { target: { value: "Go, -Perl" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Usuń Perl z „Wyklucz”" }));
    expect(onChange).toHaveBeenLastCalledWith({
      required: ["Go"],
      preferred: [],
      excluded: [],
    });
  });
});

describe("UnknownFieldBadges / HideUnknownToggle", () => {
  it("pokazuje plakietki w stałej kolejności i pomija nieznane kody", () => {
    render(<UnknownFieldBadges fields={["rate", "foo", "location"]} />);
    const labels = screen.getAllByText(/^brak /).map((el) => el.textContent);
    expect(labels).toEqual(["brak lokalizacji", "brak stawki"]);
  });

  it("nic nie renderuje bez pól", () => {
    const { container } = render(<UnknownFieldBadges fields={[]} />);
    expect(container.textContent).toBe("");
  });

  it("checkbox „Ukryj osoby bez danych” zgłasza zmianę", () => {
    const onChange = vi.fn();
    render(<HideUnknownToggle checked={false} onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Ukryj osoby bez danych"));
    expect(onChange).toHaveBeenCalledWith(true);
  });
});

describe("TextInterpretationLine", () => {
  const text = {
    kind: "text" as const,
    mode: "semantic" as const,
    rule: "known_skill",
    name: [],
    email: null,
    phone: null,
    skills: ["java"],
    locations: [],
    other: [],
  };

  it("bez przełącznika tylko informuje (lista)", () => {
    render(
      <TextInterpretationLine
        applied="literal"
        interpretation={text}
        note="Lista szuka tego tekstu dosłownie."
      />,
    );
    expect(screen.getByTestId("text-interpretation").textContent).toMatch(
      /Rozumiem to jako: dosłowny tekst/,
    );
    expect(screen.queryByRole("button", { name: "Dosłownie" })).toBeNull();
  });

  it("„Dosłownie” wymusza literal, „Automatycznie” wraca do auto", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <TextInterpretationLine
        applied="semantic"
        interpretation={text}
        textMode="auto"
        onTextModeChange={onChange}
      />,
    );
    expect(screen.getByTestId("text-interpretation").textContent).toMatch(
      /po znaczeniu/,
    );
    fireEvent.click(screen.getByRole("button", { name: "Dosłownie" }));
    expect(onChange).toHaveBeenLastCalledWith("literal");
    rerender(
      <TextInterpretationLine
        applied="literal"
        interpretation={text}
        textMode="literal"
        onTextModeChange={onChange}
      />,
    );
    expect(screen.getByTestId("text-interpretation").textContent).toMatch(
      /wybrane ręcznie/,
    );
    fireEvent.click(screen.getByRole("button", { name: "Automatycznie" }));
    expect(onChange).toHaveBeenLastCalledWith("auto");
  });

  it("brak tekstu = brak linii", () => {
    const { container } = render(
      <TextInterpretationLine applied="none" interpretation={null} />,
    );
    expect(container.textContent).toBe("");
  });
});
