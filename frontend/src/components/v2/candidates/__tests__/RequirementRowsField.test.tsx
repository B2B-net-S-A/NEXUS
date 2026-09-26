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
}: {
  initial: string[][];
  onUseLocation?: (city: string) => void;
  onUseExperience?: (range: ExperienceRange) => void;
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
      />
      <output data-testid="rows">{JSON.stringify(rows)}</output>
    </>
  );
}

const rows = () => JSON.parse(screen.getByTestId("rows").textContent ?? "[]");

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
    const second = screen.getByLabelText("Wymaganie 2 — słowo albo wariant") as HTMLInputElement;
    fireEvent.change(second, { target: { value: "Rabbit" } });
    fireEvent.click(screen.getByRole("button", { name: "Usuń wymaganie 1" }));
    expect(rows()).toEqual([["Kafka"]]);
    expect(
      (screen.getByLabelText("Wymaganie 1 — słowo albo wariant") as HTMLInputElement).value,
    ).toBe("Rabbit");
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
