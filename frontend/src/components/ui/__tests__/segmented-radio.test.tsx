import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  SegmentedRadio,
  type SegmentedRadioOption,
} from "@/components/ui/segmented-radio";

type Level = "p1" | "p2" | "accepting";

const OPTIONS: SegmentedRadioOption<Level>[] = [
  { value: "p1", label: "P1 Pilne" },
  { value: "p2", label: "P2 Standard" },
  { value: "accepting", label: "Przyjmujemy kandydatów" },
];

/** Kontrolowany przełącznik — tak jak na ekranie, wartość trzyma rodzic. */
function Harness({
  initial = "p2",
  options = OPTIONS,
  onChange,
  disabled,
}: {
  initial?: Level | null;
  options?: SegmentedRadioOption<Level>[];
  onChange?: (value: Level) => void;
  disabled?: boolean;
}) {
  const [value, setValue] = useState<Level | null>(initial);
  return (
    <SegmentedRadio<Level>
      label="Priorytet"
      value={value}
      options={options}
      disabled={disabled}
      onChange={(next) => {
        onChange?.(next);
        setValue(next);
      }}
    />
  );
}

const radio = (name: string) => screen.getByRole("radio", { name });

describe("SegmentedRadio — semantyka", () => {
  it("to grupa radiowa z nazwą, a wybrana opcja ma aria-checked", () => {
    render(<Harness />);

    expect(screen.getByRole("radiogroup", { name: "Priorytet" })).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(radio("P2 Standard")).toHaveAttribute("aria-checked", "true");
    expect(radio("P2 Standard")).toBeChecked();
    expect(radio("P1 Pilne")).toHaveAttribute("aria-checked", "false");
    expect(radio("Przyjmujemy kandydatów")).not.toBeChecked();
  });

  it("nazwę grupy można wskazać widoczną etykietą (aria-labelledby)", () => {
    render(
      <>
        <span id="lead-label">Prowadzi</span>
        <SegmentedRadio
          labelledBy="lead-label"
          value="person"
          onChange={vi.fn()}
          options={[
            { value: "person", label: "Wybieram osobę" },
            { value: "automatic", label: "Przydziel automatycznie" },
          ]}
        />
      </>,
    );
    expect(screen.getByRole("radiogroup", { name: "Prowadzi" })).toBeInTheDocument();
  });

  it("grupa bez nazwy nie przechodzi kompilacji (label albo labelledBy)", () => {
    // @ts-expect-error — czytnik ekranu musi wiedzieć, czego dotyczy wybór
    render(<SegmentedRadio value="p1" onChange={vi.fn()} options={OPTIONS} />);
    expect(screen.getByRole("radiogroup")).toBeInTheDocument();
  });

  it("opcje to zwykłe przyciski — w formularzu niczego nie wysyłają", () => {
    render(<Harness />);
    for (const option of screen.getAllByRole("radio")) {
      expect(option).toHaveAttribute("type", "button");
    }
  });
});

describe("SegmentedRadio — mysz", () => {
  it("klik wybiera opcję i woła onChange z jej wartością", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    fireEvent.click(radio("P1 Pilne"));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("p1");
    expect(radio("P1 Pilne")).toBeChecked();
    expect(radio("P2 Standard")).not.toBeChecked();
  });

  it("klik w już wybraną opcję niczego nie zmienia", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.click(radio("P2 Standard"));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("wyłączona opcja nie daje się wybrać i niesie opis", () => {
    const onChange = vi.fn();
    render(
      <Harness
        onChange={onChange}
        options={[
          OPTIONS[0],
          OPTIONS[1],
          { ...OPTIONS[2], disabled: true, title: "Automat wyłączony", describedBy: "why-off" },
        ]}
      />,
    );

    const blocked = radio("Przyjmujemy kandydatów");
    expect(blocked).toBeDisabled();
    expect(blocked).toHaveAttribute("title", "Automat wyłączony");
    expect(blocked).toHaveAttribute("aria-describedby", "why-off");
    fireEvent.click(blocked);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("wyłączona grupa blokuje wszystkie opcje", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} disabled />);

    expect(screen.getByRole("radiogroup")).toHaveAttribute("aria-disabled", "true");
    for (const option of screen.getAllByRole("radio")) {
      expect(option).toBeDisabled();
      expect(option).toHaveAttribute("tabindex", "-1");
    }
    fireEvent.click(radio("P1 Pilne"));
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("SegmentedRadio — klawiatura", () => {
  it("grupa ma jeden przystanek Tab: wybraną opcję", async () => {
    const user = userEvent.setup();
    render(
      <>
        <button type="button">przed</button>
        <Harness />
        <button type="button">po</button>
      </>,
    );

    expect(radio("P2 Standard")).toHaveAttribute("tabindex", "0");
    expect(radio("P1 Pilne")).toHaveAttribute("tabindex", "-1");
    expect(radio("Przyjmujemy kandydatów")).toHaveAttribute("tabindex", "-1");

    await user.tab();
    expect(screen.getByRole("button", { name: "przed" })).toHaveFocus();
    await user.tab();
    expect(radio("P2 Standard")).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "po" })).toHaveFocus();
  });

  it("bez wybranej wartości Tab zatrzymuje się na pierwszej dostępnej opcji", () => {
    render(
      <Harness
        initial={null}
        options={[{ ...OPTIONS[0], disabled: true }, OPTIONS[1], OPTIONS[2]]}
      />,
    );
    expect(radio("P1 Pilne")).toHaveAttribute("tabindex", "-1");
    expect(radio("P2 Standard")).toHaveAttribute("tabindex", "0");
    expect(radio("Przyjmujemy kandydatów")).toHaveAttribute("tabindex", "-1");
  });

  it("strzałka w prawo i w dół przenosi fokus dalej i od razu wybiera", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    radio("P2 Standard").focus();
    await user.keyboard("{ArrowRight}");

    expect(radio("Przyjmujemy kandydatów")).toHaveFocus();
    expect(radio("Przyjmujemy kandydatów")).toBeChecked();
    expect(radio("Przyjmujemy kandydatów")).toHaveAttribute("tabindex", "0");
    expect(radio("P2 Standard")).toHaveAttribute("tabindex", "-1");
    expect(onChange).toHaveBeenLastCalledWith("accepting");

    // Z ostatniej opcji strzałka wraca na pierwszą.
    await user.keyboard("{ArrowDown}");
    expect(radio("P1 Pilne")).toHaveFocus();
    expect(onChange).toHaveBeenLastCalledWith("p1");
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("strzałka w lewo i w górę cofa, z pierwszej opcji na ostatnią", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    radio("P2 Standard").focus();
    await user.keyboard("{ArrowLeft}");
    expect(radio("P1 Pilne")).toHaveFocus();
    expect(onChange).toHaveBeenLastCalledWith("p1");

    await user.keyboard("{ArrowUp}");
    expect(radio("Przyjmujemy kandydatów")).toHaveFocus();
    expect(onChange).toHaveBeenLastCalledWith("accepting");
  });

  it("strzałki pomijają wyłączoną opcję", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Harness
        initial="p1"
        onChange={onChange}
        options={[OPTIONS[0], { ...OPTIONS[1], disabled: true }, OPTIONS[2]]}
      />,
    );

    radio("P1 Pilne").focus();
    await user.keyboard("{ArrowRight}");

    expect(radio("Przyjmujemy kandydatów")).toHaveFocus();
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("accepting");
  });

  it("strzałka nie przewija strony (preventDefault), inne klawisze zostają w spokoju", () => {
    render(<Harness />);
    const current = radio("P2 Standard");
    current.focus();

    // `fireEvent` zwraca false, gdy obsługa zdarzenia wywołała preventDefault.
    expect(fireEvent.keyDown(current, { key: "ArrowRight" })).toBe(false);
    expect(fireEvent.keyDown(radio("Przyjmujemy kandydatów"), { key: "a" })).toBe(true);
    expect(fireEvent.keyDown(radio("Przyjmujemy kandydatów"), { key: "Tab" })).toBe(true);
  });

  it("strzałka z modyfikatorem (Alt+← = „wstecz”) nie zmienia wyboru", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const current = radio("P2 Standard");
    current.focus();

    for (const modifier of ["altKey", "ctrlKey", "metaKey", "shiftKey"] as const) {
      // `true` = zdarzenie nie zostało zatrzymane, skrót trafia do przeglądarki.
      expect(fireEvent.keyDown(current, { key: "ArrowLeft", [modifier]: true })).toBe(true);
    }

    expect(onChange).not.toHaveBeenCalled();
    expect(current).toHaveFocus();
    expect(current).toBeChecked();
  });

  it("spacja wybiera opcję pod fokusem", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    radio("P1 Pilne").focus();
    await user.keyboard(" ");

    expect(onChange).toHaveBeenCalledWith("p1");
    expect(radio("P1 Pilne")).toBeChecked();
  });

  it("przy jednej dostępnej opcji strzałka nie ma dokąd pójść", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Harness
        onChange={onChange}
        options={[
          { ...OPTIONS[0], disabled: true },
          OPTIONS[1],
          { ...OPTIONS[2], disabled: true },
        ]}
      />,
    );

    radio("P2 Standard").focus();
    await user.keyboard("{ArrowRight}");

    expect(radio("P2 Standard")).toHaveFocus();
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("SegmentedRadio — wygląd", () => {
  it("wybrana opcja jest wypełniona kolorem głównym, reszta ma neutralny hover", () => {
    render(<Harness />);
    expect(radio("P2 Standard").className).toContain("bg-primary");
    expect(radio("P2 Standard").className).toContain("text-primary-foreground");
    expect(radio("P1 Pilne").className).toContain("hover:bg-accent");
    expect(radio("P1 Pilne").className).not.toContain("bg-primary");
  });

  it("zawija opcje w wąskim kontenerze i ma mniejszy rozmiar", () => {
    const { rerender } = render(
      <SegmentedRadio label="Priorytet" value="p2" onChange={vi.fn()} options={OPTIONS} />,
    );
    const group = screen.getByRole("radiogroup");
    expect(group.className).toContain("flex-wrap");
    expect(group.className).toContain("max-w-full");
    expect(radio("P2 Standard").className).toContain("text-sm");

    rerender(
      <SegmentedRadio label="Priorytet" value="p2" onChange={vi.fn()} options={OPTIONS} size="sm" />,
    );
    expect(radio("P2 Standard").className).toContain("text-xs");
    // Na dotyku każda opcja ma 40 px wysokości.
    expect(radio("P2 Standard").className).toContain("pointer-coarse:min-h-10");
  });
});
