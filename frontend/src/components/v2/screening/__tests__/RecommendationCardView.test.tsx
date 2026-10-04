import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { RecommendationCard } from "@/lib/api/recommendationCards";

import { RecommendationCardForm } from "../RecommendationCardDialog";
import { RecommendationCardQuestions, RecommendationCardView } from "../RecommendationCardView";

const LABELS = {
  rate: "Stawka",
  availability: "Dostępność",
  work_mode: "Tryb pracy",
  location: "Lokalizacja",
  nationality: "Narodowość",
  worked_at_client: "Czy pracował u Klienta",
  english: "Angielski",
  red_flags: "Red flags",
  recommendation: "Notatka",
  motivation: "Motywacja",
};

const CARD: RecommendationCard = {
  candidate_id: 1,
  job_id: 2,
  exists: true,
  fields: {
    rate: { raw: "135 zł/h", value: 135, source: "note" },
    english: { raw: "C1", level: "C1", source: "note" },
  },
  previous: {},
  suggestions: { nationality: "polska" },
  questions: [
    { number: 1, question: "Java 17+?", answer: "Java 21 w banku.", source: "note" },
    { number: 2, question: "Chmura?", answer: "", source: null },
  ],
  completeness: {
    status: "partial",
    filled: 2,
    total: 10,
    missing: ["availability", "motivation"],
  },
  labels: LABELS,
  editable_fields: Object.keys(LABELS),
  legacy_text: "Imię i nazwisko: Tomasz Wzorcowy\nStawka: 135 zł/h",
};

describe("RecommendationCardView", () => {
  it("pokazuje wartości, braki i liczbę odpowiedzi", () => {
    render(<RecommendationCardView card={CARD} onSave={vi.fn()} />);

    expect(screen.getByText("135 zł/h")).toBeInTheDocument();
    expect(screen.getByText("1 z 2 odpowiedzi")).toBeInTheDocument();
    expect(screen.getByText("brak — ostatnio: polska")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dopisz: Motywacja" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zmień: Stawka" })).toBeInTheDocument();
    // „Notatka” ze wzoru działu ma na ekranie zrozumiałą nazwę.
    expect(screen.getByRole("button", { name: "Dopisz: Dlaczego ten kandydat" })).toBeInTheDocument();
  });

  it("zapisuje jedno pole i podpowiada wartość z poprzedniej karty", () => {
    const onSave = vi.fn();
    render(<RecommendationCardView card={CARD} onSave={onSave} />);

    fireEvent.click(screen.getByRole("button", { name: "Dopisz: Narodowość" }));
    const input = screen.getByLabelText("Narodowość");
    expect(input).toHaveValue("polska");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(onSave).toHaveBeenCalledWith({ nationality: "polska" });
  });

  it("nie zapisuje niezmienionej wartości", () => {
    const onSave = vi.fn();
    render(<RecommendationCardView card={CARD} onSave={onSave} />);

    fireEvent.click(screen.getByRole("button", { name: "Zmień: Stawka" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(onSave).not.toHaveBeenCalled();
  });

  it("wyczyszczenie pola z notatki niczego nie wysyła", () => {
    const onSave = vi.fn();
    render(<RecommendationCardView card={CARD} onSave={onSave} />);

    fireEvent.click(screen.getByRole("button", { name: "Zmień: Stawka" }));
    fireEvent.change(screen.getByLabelText("Stawka"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(onSave).not.toHaveBeenCalled();
  });

  it("wyczyszczenie pola wpisanego ręcznie zdejmuje je", () => {
    const onSave = vi.fn();
    const manual: RecommendationCard = {
      ...CARD,
      fields: { ...CARD.fields, rate: { raw: "150 zł/h", source: "manual" } },
    };
    render(<RecommendationCardView card={manual} onSave={onSave} />);

    fireEvent.click(screen.getByRole("button", { name: "Zmień: Stawka" }));
    fireEvent.change(screen.getByLabelText("Stawka"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(onSave).toHaveBeenCalledWith({ rate: null });
  });

  it("w trybie tylko do odczytu nie ma przycisków edycji", () => {
    render(<RecommendationCardView card={CARD} readOnly onSave={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Dopisz|Zmień/ })).not.toBeInTheDocument();
  });
});

describe("RecommendationCardForm", () => {
  it("pokazuje pytania, braki i tekst w starym formacie", () => {
    const onCopy = vi.fn();
    render(
      <RecommendationCardForm
        card={CARD}
        draft={{ rate: "135 zł/h" }}
        onDraftChange={vi.fn()}
        onCopy={onCopy}
      />,
    );

    expect(screen.getByText("1. Java 17+?")).toBeInTheDocument();
    expect(screen.getByText("odpowiedź z notatki")).toBeInTheDocument();
    expect(screen.getByText("brak odpowiedzi")).toBeInTheDocument();
    expect(screen.getByText(/Brakuje: Dostępność, Motywacja\./)).toBeInTheDocument();
    expect(screen.getByText(/Imię i nazwisko: Tomasz Wzorcowy/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Kopiuj/ }));
    expect(onCopy).toHaveBeenCalled();
  });
});

describe("RecommendationCardQuestions — „Odpada, gdy…”", () => {
  const withDealBreakers = {
    ...CARD,
    questions: [
      {
        number: 1,
        question: "Java 17+?",
        answer: "Java 21 w banku.",
        source: "sheet" as const,
        question_id: "q1",
        deal_breaker: "nie pracował z Javą 17+",
        deal_breaker_hit: false,
      },
      {
        number: 2,
        question: "Biuro 2 dni?",
        answer: "Tylko zdalnie.",
        source: "note" as const,
        question_id: "q2",
        deal_breaker: "nie przyjedzie do biura",
        deal_breaker_hit: false,
      },
    ],
  };

  it("pole wyboru stoi tylko przy odpowiedzi z arkusza — notatka nie trafia do arkusza", () => {
    const onChange = vi.fn();
    render(
      <RecommendationCardQuestions
        card={withDealBreakers}
        editable
        onDealBreakerHitChange={onChange}
      />,
    );

    expect(screen.getByText("Odpada, gdy: nie pracował z Javą 17+")).toBeInTheDocument();
    expect(screen.getByText("Odpada, gdy: nie przyjedzie do biura")).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);
  });
});
