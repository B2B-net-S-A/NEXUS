import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { EmploymentMarker } from "@/lib/employment-marker";
import { PickList, type PickRow } from "../pick-list";

const WORKING: EmploymentMarker = {
  phase: "working",
  source: "contract",
  elsewhere: true,
  clients: [
    {
      client_id: 4,
      client_name: "Bank Przykładowy",
      contract_id: 40,
      phase: "working",
      order_end_date: "2026-12-31",
    },
  ],
};

function row(overrides: Partial<PickRow> = {}): PickRow {
  return {
    candidateId: 1,
    fullName: "Anna Przykładowa",
    fitScore: 80,
    rateLabel: null,
    availabilityLabel: null,
    note: null,
    facts: "Java Developer · 8 lat dośw. · Warszawa",
    sourceLabel: null,
    warnings: [],
    ...overrides,
  };
}

describe("PickList — znacznik „Pracuje u nas”", () => {
  it("pigułka stoi obok, nie w nazwie przycisku ani w linii faktów", () => {
    render(
      <PickList
        rows={[row({ employment: WORKING }), row({ candidateId: 2, fullName: "Jan Testowy" })]}
        selected={new Set()}
        onToggle={vi.fn()}
        readOnly={false}
        emptyText="Brak"
        label="Osoby"
        onPreview={vi.fn()}
      />,
    );

    const [employed, other] = screen.getAllByRole("listitem");
    expect(
      within(employed).getByText("Pracuje u nas · Bank Przykładowy · do 31.12.2026"),
    ).toBeInTheDocument();
    // Nazwa dostępna przycisku to samo nazwisko — po niej szukają testy i czytnik.
    expect(within(employed).getByRole("button", { name: "Anna Przykładowa" })).toBeInTheDocument();
    expect(within(employed).getByText("Java Developer · 8 lat dośw. · Warszawa")).toBeInTheDocument();
    // Znacznik niczego nie blokuje: osobę da się zaznaczyć.
    expect(within(employed).getByRole("checkbox", { name: "Zaznacz Anna Przykładowa" })).toBeEnabled();
    expect(within(other).queryByText(/Pracuje u nas/)).toBeNull();
  });
});

describe("PickList — dopasowanie bez klikania, „+ Dodaj”, „Cofnij” i powód (14.10.2026)", () => {
  const base = {
    selected: new Set<number>(),
    onToggle: vi.fn(),
    readOnly: false,
    emptyText: "Brak",
    label: "Osoby",
  };

  it("bez IntersectionObserver zgłasza się pierwszych 20 wierszy, nie więcej", () => {
    const onRowVisible = vi.fn();
    const rows = Array.from({ length: 25 }, (_, i) =>
      row({ candidateId: i + 1, fullName: `Osoba ${i + 1}` }),
    );
    render(<PickList {...base} rows={rows} onRowVisible={onRowVisible} />);
    expect(onRowVisible).toHaveBeenCalledTimes(20);
    expect(onRowVisible.mock.calls.map(([id]) => id)).toEqual(
      Array.from({ length: 20 }, (_, i) => i + 1),
    );
  });

  it("z obserwatorem zgłasza wiersz dopiero, gdy wejdzie na ekran — raz", () => {
    const callbacks: Array<(entries: Array<{ isIntersecting: boolean }>) => void> = [];
    const disconnect = vi.fn();
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(cb: (entries: Array<{ isIntersecting: boolean }>) => void) {
          callbacks.push(cb);
        }
        observe() {}
        disconnect = disconnect;
      },
    );
    try {
      const onRowVisible = vi.fn();
      render(<PickList {...base} rows={[row(), row({ candidateId: 2, fullName: "Jan" })]} onRowVisible={onRowVisible} />);
      expect(onRowVisible).not.toHaveBeenCalled();
      callbacks[1]([{ isIntersecting: true }]);
      expect(onRowVisible).toHaveBeenCalledWith(2);
      expect(disconnect).toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("„+ Dodaj” dodaje tę jedną osobę; dodana ma status i „Cofnij” zamiast przycisków", () => {
    const onAdd = vi.fn();
    const onUndo = vi.fn();
    render(
      <PickList
        {...base}
        rows={[row(), row({ candidateId: 2, fullName: "Jan Testowy", addState: "added" })]}
        onAdd={onAdd}
        onUndo={onUndo}
        onDismiss={vi.fn()}
      />,
    );
    const [first, added] = screen.getAllByRole("listitem");
    within(first).getByRole("button", { name: "Dodaj do „Nowych”: Anna Przykładowa" }).click();
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ candidateId: 1 }));
    expect(within(added).getByRole("status")).toHaveTextContent("Dodano do „Nowych” · rezerwacja 12 h");
    expect(within(added).queryByRole("button", { name: /Dodaj do „Nowych”/ })).toBeNull();
    expect(within(added).queryByRole("button", { name: /Pomiń:/ })).toBeNull();
    expect(within(added).getByRole("checkbox")).toBeDisabled();
    within(added).getByRole("button", { name: "Cofnij dodanie: Jan Testowy" }).click();
    expect(onUndo).toHaveBeenCalledWith(expect.objectContaining({ candidateId: 2 }));
  });

  it("cofanie w toku blokuje „Cofnij”; do odczytu nie ma ani „+ Dodaj”, ani „Cofnij”", () => {
    const { rerender } = render(
      <PickList {...base} rows={[row({ addState: "undoing" })]} onAdd={vi.fn()} onUndo={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Cofnij dodanie: Anna Przykładowa" })).toBeDisabled();
    rerender(
      <PickList {...base} readOnly rows={[row(), row({ candidateId: 2, fullName: "Jan", addState: "added" })]} onAdd={vi.fn()} onUndo={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: /Dodaj do „Nowych”/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Cofnij/ })).toBeNull();
  });

  it("chipy powodu pod całym wierszem (także pod przyciskami): do 2 linii, etykieta do 18 znaków, „+N”", () => {
    render(
      <PickList
        {...base}
        onAdd={vi.fn()}
        onDismiss={vi.fn()}
        onPreview={vi.fn()}
        rows={[
          row({
            note: "Spełnia: Java, Spring",
            chips: {
              shown: [
                { tone: "met", label: "Java" },
                { tone: "gap", label: "Kafka" },
                { tone: "ask", label: "Minimum 5 lat doświadczenia w projektach dla sektora finansowego" },
              ],
              hidden: [
                { tone: "met", label: "Spring" },
                { tone: "met", label: "SQL" },
              ],
            },
          }),
        ]}
      />,
    );
    const item = screen.getByRole("listitem");
    const reasons = within(item).getByRole("group", { name: "Dlaczego ta osoba" });
    // Wiersz chipów jest rodzeństwem bloku z przyciskami, nie jego kolumną.
    const addButton = within(item).getByRole("button", { name: "Dodaj do „Nowych”: Anna Przykładowa" });
    expect(reasons.parentElement).toBe(item);
    expect(reasons.contains(addButton)).toBe(false);
    expect(addButton.closest("div")?.contains(reasons)).toBe(false);
    expect(reasons.className).toContain("flex-wrap");
    expect(reasons.className).toContain("max-h-11");
    expect(within(reasons).getByText("Java")).toBeInTheDocument();
    expect(within(reasons).getByText("Kafka").parentElement).toHaveAttribute("data-tone", "gap");
    // Długa etykieta: 18 znaków na chipie, cała w podpowiedzi, bez „— zapytaj”.
    const ask = within(reasons).getByText("Minimum 5 lat doś…");
    expect(ask.parentElement).toHaveAttribute(
      "title",
      "Nie wiemy — zapytaj w rozmowie: Minimum 5 lat doświadczenia w projektach dla sektora finansowego",
    );
    // Bez dopisku „— zapytaj” — mówi to „?” na początku (i tekst dla czytnika).
    expect(ask.parentElement?.textContent).toBe("?Nie wiemy — zapytaj w rozmowie: Minimum 5 lat doś…");
    const more = within(reasons).getByText("+2").parentElement as HTMLElement;
    expect(more).toHaveAttribute("title", "✓ Spring, ✓ SQL");
    expect(screen.getByText("Spełnia: Java, Spring").className).toContain("line-clamp-1");
  });

  it("dodana osoba nie pokazuje chipów (ma status z „Cofnij”)", () => {
    render(
      <PickList
        {...base}
        rows={[row({ addState: "added", chips: { shown: [{ tone: "met", label: "Java" }], hidden: [] } })]}
        onUndo={vi.fn()}
      />,
    );
    expect(screen.queryByRole("group", { name: "Dlaczego ta osoba" })).toBeNull();
  });
});
