/**
 * „Jak rozpoznać dobrego kandydata”: warunki z profilu po ludzku. Bez powodu
 * odrzucenia w profilu nie ma wiersza „Odpada, gdy” — AI nie dopisuje warunków.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlainScreeningCards } from "@/components/champion/plain/PlainScreeningCards";
import type { ScreeningPlain } from "@/lib/api/plainKnowledge";

const ITEMS: ScreeningPlain[] = [
  {
    question_id: "q1",
    question: "„Opisz ostatni system w Spring Boocie”",
    why: "Sprawdzasz, czy pisał usługi w Springu.",
    good: "Mówi, z jakich części składał się system.",
    reject: "Pracował tylko przy utrzymaniu.",
    original: { ideal_answer: "Konkretny projekt", deal_breaker: "Wyłącznie utrzymanie" },
  },
  {
    question_id: "q2",
    question: "„Jak używałeś Kafki?”",
    why: "Klient chce kogoś, kto zna ją z praktyki.",
    good: "Opowiada o konkretnej integracji.",
    reject: null,
    original: { ideal_answer: "Producent/konsument", deal_breaker: null },
  },
];

describe("PlainScreeningCards", () => {
  it("pokazuje notę o tym, kto ustala warunki", () => {
    render(<PlainScreeningCards items={ITEMS} />);
    expect(screen.getByText(/nie dopisuje nowych warunków/)).toBeInTheDocument();
  });

  it("karta bez powodu odrzucenia nie ma wiersza „Odpada, gdy”", () => {
    render(<PlainScreeningCards items={ITEMS} />);
    const [first, second] = screen.getAllByTestId("plain-screening-card");
    expect(within(first).getByText("Odpada, gdy")).toBeInTheDocument();
    expect(within(second).queryByText("Odpada, gdy")).not.toBeInTheDocument();
    expect(within(second).getByText("Dobra odpowiedź")).toBeInTheDocument();
    expect(within(second).getByText("sekcja 6 · pytanie 2")).toBeInTheDocument();
  });

  it("„Tak brzmi w profilu” pokazuje oryginał", () => {
    render(<PlainScreeningCards items={ITEMS} />);
    const [first] = screen.getAllByTestId("plain-screening-card");
    expect(within(first).getByText("Tak brzmi w profilu")).toBeInTheDocument();
    expect(within(first).getByText("Idealnie: Konkretny projekt")).toBeInTheDocument();
    expect(within(first).getByText("Odpada, gdy: Wyłącznie utrzymanie")).toBeInTheDocument();
  });

  it("pusta lista nic nie renderuje", () => {
    const { container } = render(<PlainScreeningCards items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("pokazuje 3 pytania, resztę za „Pokaż wszystkie”", () => {
    const five = Array.from({ length: 5 }, (_, i) => ({ ...ITEMS[0], question_id: `q${i}`, question: `Pytanie ${i + 1}` }));
    render(<PlainScreeningCards items={five} />);
    expect(screen.getAllByTestId("plain-screening-card")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Pokaż wszystkie pytania (5)" }));
    expect(screen.getAllByTestId("plain-screening-card")).toHaveLength(5);
  });
});
