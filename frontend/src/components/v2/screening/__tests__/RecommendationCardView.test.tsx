import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import type { RecommendationCard } from "@/lib/api/recommendationCards";

import { RecommendationCardFullView } from "../RecommendationCardDialog";
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

describe("RecommendationCardView (0424: tylko do odczytu)", () => {
  it("pokazuje wartości, braki i liczbę odpowiedzi — bez pól edycji", () => {
    render(<RecommendationCardView card={CARD} />);

    expect(screen.getByText("135 zł/h")).toBeInTheDocument();
    expect(screen.getByText("1 z 2 odpowiedzi")).toBeInTheDocument();
    expect(screen.getByText("brak — ostatnio: polska")).toBeInTheDocument();
    // „Notatka” ze wzoru działu ma na ekranie zrozumiałą nazwę.
    expect(screen.getByText("Dlaczego ten kandydat")).toBeInTheDocument();
    // Pola karty wpisuje się w formularzu screeningu — tu nie ma edycji.
    expect(screen.queryByRole("button", { name: /Dopisz|Zmień/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("„Edytuj w screeningu” i „Otwórz całą kartę” wołają przekazane akcje", () => {
    const onEditInScreening = vi.fn();
    const onOpenFull = vi.fn();
    render(<RecommendationCardView card={CARD} onEditInScreening={onEditInScreening} onOpenFull={onOpenFull} />);

    fireEvent.click(screen.getByRole("button", { name: /Edytuj w screeningu/ }));
    expect(onEditInScreening).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Otwórz całą kartę" }));
    expect(onOpenFull).toHaveBeenCalledTimes(1);
  });

  it("bez akcji (tylko do odczytu) nie ma przycisków", () => {
    render(<RecommendationCardView card={CARD} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("RecommendationCardFullView", () => {
  it("pokazuje pytania, braki i tekst w starym formacie", () => {
    const onCopy = vi.fn();
    render(<RecommendationCardFullView card={CARD} onCopy={onCopy} />);

    expect(screen.getByText("1. Java 17+?")).toBeInTheDocument();
    expect(screen.getByText("odpowiedź z notatki")).toBeInTheDocument();
    expect(screen.getByText("brak odpowiedzi")).toBeInTheDocument();
    expect(screen.getByText(/Brakuje: Dostępność, Motywacja\./)).toBeInTheDocument();
    expect(screen.getByText(/Imię i nazwisko: Tomasz Wzorcowy/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
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
