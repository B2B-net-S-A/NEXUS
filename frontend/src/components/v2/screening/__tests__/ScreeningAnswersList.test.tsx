/**
 * Jedyny renderer odpowiedzi ze screeningu (profil, dok, panel osoby).
 * Pilnujemy tego, co zgłosiła testerka: widać PYTANIE i ODPOWIEDŹ, a nie samą
 * liczbę odpowiedzi — także wtedy, gdy pytanie zniknęło z profilu Championa.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ScreeningAnswersList,
  screeningQuestionLabel,
} from "@/components/v2/screening/ScreeningAnswersList";

const ANSWERS = [
  {
    question_id: "q1",
    question_text: "Czy pracowałeś na mikroserwisach?",
    response: "Tak, 3 lata. Kafka i Spring Boot.",
    deal_breaker_hit: false,
    skipped: false,
  },
  { question_id: "q2", question_text: "Od kiedy dostępny?", response: "", deal_breaker_hit: false, skipped: true },
  { question_id: "q3", question_text: null, response: "B2B", deal_breaker_hit: true, skipped: false },
  { question_id: "q4", question_text: "Stawka?", response: "  ", deal_breaker_hit: false, skipped: false },
];

describe("ScreeningAnswersList", () => {
  it("pokazuje pytanie i odpowiedź, pominięte i brak odpowiedzi nazywa wprost", () => {
    render(<ScreeningAnswersList answers={ANSWERS} />);
    const rows = within(screen.getByRole("list", { name: "Pytania i odpowiedzi" })).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent("1. Czy pracowałeś na mikroserwisach?");
    expect(rows[0]).toHaveTextContent("Tak, 3 lata. Kafka i Spring Boot.");
    expect(rows[1]).toHaveTextContent("— pominięte —");
    expect(rows[3]).toHaveTextContent("— bez odpowiedzi —");
  });

  it("pytanie usunięte z profilu ma uczciwą etykietę, a deal-breaker jest oznaczony", () => {
    render(<ScreeningAnswersList answers={ANSWERS} />);
    const rows = screen.getAllByRole("listitem");
    expect(rows[2]).toHaveTextContent("3. Pytanie 3 (usunięte z profilu)");
    expect(rows[2]).toHaveTextContent("deal-breaker");
    expect(rows[0]).not.toHaveTextContent("deal-breaker");
    expect(screeningQuestionLabel({ question_id: "x", question_text: "   " }, 6)).toBe(
      "Pytanie 7 (usunięte z profilu)",
    );
  });

  // 09.10.2026: widok „Screening” pokazuje też odpowiedzi z notatek i warunek
  // z Profilu Championa. Profil kandydata tych pól nie podaje — jego widok się nie zmienia.
  it("odpowiedź z notatki i „Odpada, gdy…” stoją pod odpowiedzią tylko wtedy, gdy wiersz je niesie", () => {
    render(
      <ScreeningAnswersList
        answers={[
          { ...ANSWERS[0], source: "note", deal_breaker: "Mniej niż rok z Kafką" },
          { ...ANSWERS[3], source: "note" },
          ANSWERS[2],
        ]}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("odpowiedź z notatki");
    expect(rows[0]).toHaveTextContent("Odpada, gdy: Mniej niż rok z Kafką");
    // Pusta odpowiedź nie udaje, że przyszła z notatki.
    expect(rows[1]).not.toHaveTextContent("odpowiedź z notatki");
    expect(rows[2]).not.toHaveTextContent("Odpada, gdy");
    expect(rows[2]).not.toHaveTextContent("odpowiedź z notatki");
  });

  it("po filtrze szukania pytanie zachowuje swój numer z arkusza", () => {
    render(<ScreeningAnswersList answers={[{ ...ANSWERS[2], position: 3 }]} />);
    expect(screen.getByRole("listitem")).toHaveTextContent("3. Pytanie 3 (usunięte z profilu)");
  });

  it("„Sprawdzone w rozmowie” pokazuje tylko pozycje z wynikiem", () => {
    render(
      <ScreeningAnswersList
        answers={[]}
        experienceChecks={[
          { kind: "domains", name: "Bankowość", status: "confirmed", note: "2 lata w banku" },
          { kind: "certifications", name: "AWS SA", status: "not_confirmed", note: "" },
          { kind: "regulations", name: "DORA", status: "unknown", note: "" },
        ]}
      />,
    );
    expect(screen.getByText("Sprawdzone w rozmowie")).toBeTruthy();
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Dziedzina · Bankowość");
    expect(rows[0]).toHaveTextContent("potwierdzone w rozmowie — 2 lata w banku");
    expect(rows[1]).toHaveTextContent("Certyfikaty · AWS SA");
    expect(rows[1]).toHaveTextContent("brak");
    expect(screen.queryByText("DORA")).toBeNull();
    expect(screen.queryByRole("list", { name: "Pytania i odpowiedzi" })).toBeNull();
  });

  it("notatki: ze screeningu i wewnętrzna mają osobne nagłówki; puste się nie renderują", () => {
    const { rerender } = render(
      <ScreeningAnswersList answers={ANSWERS} notes="Dobra komunikacja." internalNote="pominięte — przepięcie" />,
    );
    expect(screen.getByText("Notatka z arkusza")).toBeTruthy();
    expect(screen.getByText("Dobra komunikacja.")).toBeTruthy();
    expect(screen.getByText("Notatka wewnętrzna")).toBeTruthy();
    expect(screen.getByText("pominięte — przepięcie")).toBeTruthy();

    rerender(<ScreeningAnswersList answers={ANSWERS} notes="  " internalNote={null} />);
    expect(screen.queryByText("Notatka z arkusza")).toBeNull();
    expect(screen.queryByText("Notatka wewnętrzna")).toBeNull();
  });

  it("wyróżnia frazę z szukania w pytaniu i w odpowiedzi, bez wielkości liter", () => {
    const { container } = render(<ScreeningAnswersList answers={ANSWERS} highlight=" KAFKA " />);
    const marks = Array.from(container.querySelectorAll("mark")).map((m) => m.textContent);
    expect(marks).toEqual(["Kafka"]);

    const again = render(<ScreeningAnswersList answers={ANSWERS} highlight="mikroserwis" />);
    expect(Array.from(again.container.querySelectorAll("mark")).map((m) => m.textContent)).toEqual(["mikroserwis"]);
  });
});
