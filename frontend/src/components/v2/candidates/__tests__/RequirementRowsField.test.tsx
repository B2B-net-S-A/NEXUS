import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { get: (...args: unknown[]) => get(...args) },
  default: { get: (...args: unknown[]) => get(...args) },
}));

import { RequirementRowsField } from "@/components/v2/candidates/RequirementRowsField";
import type { ExperienceRange } from "@/lib/keyword-requirements";

function Harness({
  initial,
  onUseLocation,
  onUseExperience,
  onSubmitEmpty,
}: {
  initial: string[][];
  onUseLocation?: (city: string) => void;
  onUseExperience?: (range: ExperienceRange) => void;
  onSubmitEmpty?: () => void;
}) {
  const [rows, setRows] = useState(initial);
  const [exclude, setExclude] = useState<string[]>([]);
  return (
    <>
      <RequirementRowsField
        rows={rows}
        onRowsChange={setRows}
        exclude={exclude}
        onExcludeChange={setExclude}
        onUseLocation={onUseLocation}
        onUseExperience={onUseExperience}
        onSubmitEmpty={onSubmitEmpty}
      />
      <output data-testid="rows">{JSON.stringify(rows)}</output>
    </>
  );
}

const rows = () => JSON.parse(screen.getByTestId("rows").textContent ?? "[]");

const field = (n: number) => screen.getByLabelText(`Wymaganie ${n} — słowo albo wariant`);
const fieldOrNull = (n: number) => screen.queryByLabelText(`Wymaganie ${n} — słowo albo wariant`);
const addVariant = (n: number) =>
  screen.getByRole("button", { name: `Dodaj wariant do wymagania ${n}` });

function type(input: HTMLElement, text: string, key?: string) {
  fireEvent.change(input, { target: { value: text } });
  if (key) fireEvent.keyDown(input, { key });
}

beforeEach(() => {
  get.mockReset().mockResolvedValue({ data: { items: [] } });
});

describe("RequirementRowsField", () => {
  it("pusta lista to jeden wiersz do pisania; „Dodaj wymaganie” dokłada kolejny", () => {
    render(<Harness initial={[]} />);
    expect(screen.getByLabelText("Wymaganie 1 — słowo albo wariant")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj wymaganie" }));
    expect(screen.getByLabelText("Wymaganie 2 — słowo albo wariant")).toBeTruthy();
  });

  it("nowy wiersz dostaje kursor — od razu można pisać", () => {
    render(<Harness initial={[["Java"]]} />);
    fireEvent.click(screen.getByRole("button", { name: "Dodaj wymaganie" }));
    expect(document.activeElement).toBe(
      screen.getByLabelText("Wymaganie 2 — słowo albo wariant"),
    );
  });

  it("usunięcie wiersza wyżej nie przenosi pisanego tekstu do sąsiada", () => {
    render(<Harness initial={[["Java"], ["Kafka"]]} />);
    fireEvent.click(addVariant(2));
    const second = screen.getByLabelText("Wymaganie 2 — słowo albo wariant") as HTMLInputElement;
    fireEvent.change(second, { target: { value: "Rabbit" } });
    fireEvent.click(screen.getByRole("button", { name: "Usuń wymaganie 1" }));
    expect(rows()).toEqual([["Kafka"]]);
    expect(
      (screen.getByLabelText("Wymaganie 1 — słowo albo wariant") as HTMLInputElement).value,
    ).toBe("Rabbit");
  });

  it("po „Usuń wymaganie” kursor zostaje w polu, nie ucieka na stronę (U8)", async () => {
    render(<Harness initial={[["Java"], ["Kafka"], ["Spring"]]} />);
    fireEvent.click(screen.getByRole("button", { name: "Usuń wymaganie 2" }));
    expect(rows()).toEqual([["Java"], ["Spring"]]);
    // Wypełniony wiersz nie ma pola do pisania — kursor staje na jego „+ lub”.
    await waitFor(() => expect(document.activeElement).toBe(addVariant(2)));
  });

  // 11.10.2026: ta sama reguła co w wierszach wymagań rekrutacji (D1). Do tej
  // daty przecinek i Enter dopisywały słowo jako wariant „lub” tego samego
  // wiersza, więc „Java, Spring” znajdowało osoby z samą Javą.
  describe("wpisywanie: przecinek i Enter to kolejne wymaganie", () => {
    it("„Java, Spring” + Enter → dwa wiersze, kursor w pustym trzecim", async () => {
      render(<Harness initial={[]} />);
      type(field(1), "Java, Spring", "Enter");
      expect(rows()).toEqual([["Java"], ["Spring"], []]);
      await waitFor(() => expect(document.activeElement).toBe(field(3)));
    });

    it("przecinek w trakcie pisania kończy wymaganie i przenosi kursor niżej", async () => {
      render(<Harness initial={[]} />);
      type(field(1), "Java", ",");
      expect(rows()).toEqual([["Java"], []]);
      await waitFor(() => expect(document.activeElement).toBe(field(2)));
      type(field(2), "Spring", ";");
      expect(rows()).toEqual([["Java"], ["Spring"], []]);
    });

    it("„Kafka / RabbitMQ” to jedno wymaganie z wariantami; „CI/CD” zostaje słowem", () => {
      render(<Harness initial={[]} />);
      type(field(1), "Kafka / RabbitMQ, CI/CD", "Enter");
      expect(rows()).toEqual([["Kafka", "RabbitMQ"], ["CI/CD"], []]);
    });

    it("wklejona lista rozkłada się na wiersze", () => {
      render(<Harness initial={[]} />);
      fireEvent.paste(field(1), {
        clipboardData: { getData: () => "- Docker\n- Kubernetes\n- AWS" },
      });
      expect(rows()).toEqual([["Docker"], ["Kubernetes"], ["AWS"], []]);
    });

    it("wypełniony wiersz nie ma pola — wariant dodaje dopiero „+ lub”", async () => {
      render(<Harness initial={[["Java"]]} />);
      expect(fieldOrNull(1)).toBeNull();
      fireEvent.click(addVariant(1));
      await waitFor(() => expect(document.activeElement).toBe(field(1)));
      type(field(1), "JDK", "Enter");
      expect(rows()).toEqual([["Java", "JDK"]]);
      // Pole wariantu zostaje otwarte na kolejne słowo; pusty Enter je zamyka.
      fireEvent.keyDown(field(1), { key: "Enter" });
      expect(fieldOrNull(1)).toBeNull();
    });

    it("Enter w pustym wierszu uruchamia wyszukiwanie", () => {
      const onSubmitEmpty = vi.fn();
      render(<Harness initial={[]} onSubmitEmpty={onSubmitEmpty} />);
      type(field(1), "Java", "Enter");
      expect(onSubmitEmpty).not.toHaveBeenCalled();
      fireEvent.keyDown(field(2), { key: "Enter" });
      expect(onSubmitEmpty).toHaveBeenCalledTimes(1);
    });

    it("pusty Enter w polu wariantu też szuka", () => {
      const onSubmitEmpty = vi.fn();
      render(<Harness initial={[["Java"]]} onSubmitEmpty={onSubmitEmpty} />);
      fireEvent.click(addVariant(1));
      fireEvent.keyDown(field(1), { key: "Enter" });
      expect(onSubmitEmpty).toHaveBeenCalledTimes(1);
      expect(fieldOrNull(1)).toBeNull();
    });

    it("w polu wariantu średnik działa jak przecinek — warianty zostają w tym samym wierszu", () => {
      render(<Harness initial={[["Java"]]} />);
      fireEvent.click(addVariant(1));
      type(field(1), "JDK", ";");
      expect(rows()).toEqual([["Java", "JDK"]]);
      type(field(1), "OpenJDK; GraalVM", "Enter");
      expect(rows()).toEqual([["Java", "JDK", "OpenJDK", "GraalVM"]]);
    });

    it("Esc w pustym polu wariantu zamyka je bez szukania, kursor wraca na „+ lub”", async () => {
      const onSubmitEmpty = vi.fn();
      render(<Harness initial={[["Java"]]} onSubmitEmpty={onSubmitEmpty} />);
      fireEvent.click(addVariant(1));
      fireEvent.keyDown(field(1), { key: "Escape" });
      expect(fieldOrNull(1)).toBeNull();
      expect(onSubmitEmpty).not.toHaveBeenCalled();
      await waitFor(() => expect(document.activeElement).toBe(addVariant(1)));
      expect(rows()).toEqual([["Java"]]);
    });

    it("usunięcie wiersza nad otwartym polem wariantu zostawia kursor w tym polu", async () => {
      render(<Harness initial={[["Aa"], ["Bb"]]} />);
      fireEvent.click(addVariant(2));
      const remove = screen.getByRole("button", { name: "Usuń wymaganie 1" });
      remove.focus();
      fireEvent.click(remove);
      // Wiersz „Bb” zajął miejsce usuniętego; przycisku „+ lub” w nim nie ma.
      await waitFor(() => expect(document.activeElement).toBe(field(1)));
      expect(rows()).toEqual([["Bb"]]);
    });

    it("to samo wymaganie drugi raz i nadmiar ponad limit — pole mówi, czego nie dodało", () => {
      const nine = Array.from({ length: 9 }, (_, i) => [`s${i}`]);
      render(<Harness initial={[...nine, []]} />);
      type(field(10), "s0, Java, Spring", "Enter");
      expect(rows()).toEqual([...nine, ["Java"]]);
      const note = screen.getByTestId("requirement-entry-note");
      expect(note).toHaveTextContent("„s0” już jest na liście");
      expect(note).toHaveTextContent("Najwyżej 10 wymagań — nie dodano: Spring");
    });

    it("wyjście z pola zapisuje wpis, ale nie dokłada pustego wiersza", () => {
      render(<Harness initial={[]} />);
      type(field(1), "Java, Spring");
      fireEvent.blur(field(1));
      expect(rows()).toEqual([["Java"], ["Spring"]]);
    });
  });

  it("pojedyncza litera nie jest słowem kluczowym — pole mówi, gdzie ją wyszukać", () => {
    // Przegląd PR #2056: „R” i „C” jako słowo kluczowe znajdowały prawie całą
    // bazę („2019 r.”, „C++”). Nie znikają po cichu — pole tłumaczy.
    render(<Harness initial={[]} />);
    const input = screen.getByLabelText("Wymaganie 1 — słowo albo wariant");
    fireEvent.change(input, { target: { value: "R" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(rows()).toEqual([]);
    expect(screen.getByText(/„R” jest za krótkie/)).toHaveTextContent(
      "Pojedynczą literę (np. C albo R) wyszukaj w polu „Umiejętności”.",
    );
  });

  it("limit 10 wymagań", () => {
    render(<Harness initial={Array.from({ length: 10 }, (_, i) => [`s${i}`])} />);
    expect(screen.getByRole("button", { name: "Dodaj wymaganie" })).toBeDisabled();
    expect(screen.getByText("Najwyżej 10 wymagań.")).toBeTruthy();
  });

  it("„React / Vue” — podpowiedź rozdziela na warianty w tym samym wierszu", () => {
    render(<Harness initial={[["React / Vue"]]} />);
    fireEvent.click(screen.getByRole("button", { name: "Rozdziel" }));
    expect(rows()).toEqual([["React", "Vue"]]);
  });

  it("„senior” — filtr stażu zamiast słowa; „Zostaw” chowa podpowiedź", () => {
    const onUseExperience = vi.fn();
    const { unmount } = render(
      <Harness initial={[["Java"], ["senior"]]} onUseExperience={onUseExperience} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Użyj filtra stażu: 5+ lat" }));
    expect(onUseExperience).toHaveBeenCalledWith({ min: 5, max: null });
    expect(rows()).toEqual([["Java"]]);
    unmount();

    render(<Harness initial={[["senior"]]} onUseExperience={onUseExperience} />);
    fireEvent.click(screen.getByRole("button", { name: "Zostaw" }));
    expect(screen.queryByRole("button", { name: /Użyj filtra stażu/ })).toBeNull();
    expect(rows()).toEqual([["senior"]]);
  });

  it("„go” — słowo wieloznaczne, „Zamień na golang” podmienia je w tym samym wierszu", () => {
    render(<Harness initial={[["Java", "go"]]} />);
    expect(screen.getByText(/„go” to słowo wieloznaczne — łapie też „go-live”/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zamień na „golang”" }));
    expect(rows()).toEqual([["Java", "golang"]]);
    expect(screen.queryByText(/słowo wieloznaczne/)).toBeNull();
  });

  it("„it” — tylko ostrzeżenie bez zamiennika, „Zostaw” je chowa", () => {
    render(<Harness initial={[["it"]]} />);
    const note = screen.getByRole("note");
    expect(note.textContent).toContain("„it” to słowo wieloznaczne");
    expect(screen.queryByRole("button", { name: /Zamień na/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Zostaw" }));
    expect(screen.queryByRole("note")).toBeNull();
    expect(rows()).toEqual([["it"]]);
  });

  it("bez akcji stażu podpowiedzi o stażu nie ma (np. edytor Championa)", () => {
    render(<Harness initial={[["senior"]]} />);
    expect(screen.queryByRole("button", { name: /Użyj filtra stażu/ })).toBeNull();
  });

  it("słowo-miasto (≥ 20 tys. mieszkańców) → „Ustaw lokalizację”, mała wieś nie", async () => {
    get.mockImplementation((_url: string, config: { params: { q: string } }) =>
      Promise.resolve({
        data: {
          items:
            config.params.q === "Warszawa"
              ? [{ name: "Warszawa", voivodeship: "mazowieckie", population: 1790658 }]
              : config.params.q === "Kotlin"
                ? [{ name: "Kotlin", voivodeship: "wielkopolskie", population: 3416 }]
                : [],
        },
      }),
    );
    const onUseLocation = vi.fn();
    render(<Harness initial={[["Kotlin"], ["Warszawa"]]} onUseLocation={onUseLocation} />);
    const button = await screen.findByRole("button", { name: "Ustaw lokalizację: Warszawa" });
    expect(screen.queryByRole("button", { name: /Ustaw lokalizację: Kotlin/ })).toBeNull();
    await act(async () => {
      fireEvent.click(button);
    });
    expect(onUseLocation).toHaveBeenCalledWith("Warszawa");
    await waitFor(() => expect(rows()).toEqual([["Kotlin"]]));
  });
});
