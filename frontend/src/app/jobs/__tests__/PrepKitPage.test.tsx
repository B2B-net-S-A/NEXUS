/**
 * Prep kit przed rozmową (`/jobs/[id]/prep/[candidateId]`): dwa źródła mówią
 * o niepełnej liście pytań (#408) — wystarczy jedno, żeby baner się pokazał.
 */

import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const params: { id: string; candidateId: string } = { id: "7", candidateId: "3" };
const push = vi.fn();
const generate = vi.fn();
const suggestedForJob = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => params,
  useRouter: () => ({ push }),
}));
vi.mock("@/lib/api", () => ({
  prepKitApi: { generate: (...a: unknown[]) => generate(...a) },
  interviewQuestionsApi: { suggestedForJob: (...a: unknown[]) => suggestedForJob(...a) },
}));
// Karta pytania ma własne testy — tu liczy się, w której sekcji ląduje.
vi.mock("@/components/prep/QuestionCard", () => ({
  QuestionCard: (p: { question: { text: string }; onPin?: () => void; onRated?: () => void }) => (
    <div data-testid="question" data-pinnable={p.onPin ? "yes" : "no"}>
      {p.question.text}
      <button type="button" onClick={p.onRated}>
        oceń {p.question.text}
      </button>
    </div>
  ),
}));

import PrepPage from "@/app/jobs/[id]/prep/[candidateId]/page";

const kit = (over: Record<string, unknown> = {}) => ({
  data: {
    client_overview: "Fikcyjny bank testowy, zespół płatności.",
    likely_questions: [],
    likely_questions_meta: [],
    candidate_strengths: ["Długi staż w Javie"],
    candidate_gaps: ["Brak Kafki"],
    selling_points: ["Praca zdalna"],
    recommended_strategy: "Zacznij od architektury.",
    ...over,
  },
});

const question = (text: string, source_tier: string) => ({
  text,
  source_tier,
  question_id: null,
  source_job_id: null,
  ideal_answer: null,
  deal_breaker: false,
  seniority: null,
  question_type: null,
  skill_tags: [],
  cosine_score: null,
});

const suggestions = (
  items: ReturnType<typeof question>[],
  meta: { degraded?: boolean; reason?: string | null } = {},
) => ({ data: { items, meta: { returned: items.length, degraded: false, reason: null, ...meta } } });

beforeEach(() => {
  params.id = "7";
  params.candidateId = "3";
  push.mockReset();
  generate.mockReset();
  suggestedForJob.mockReset();
});

describe("PrepPage", () => {
  it("pyta o prep kit i 15 pytań dla tej pary", async () => {
    generate.mockResolvedValue(kit());
    suggestedForJob.mockResolvedValue(suggestions([]));
    render(<PrepPage />);
    expect(await screen.findByText("Fikcyjny bank testowy, zespół płatności.")).toBeInTheDocument();
    expect(generate).toHaveBeenCalledWith(7, 3);
    expect(suggestedForJob).toHaveBeenCalledWith(7, { candidate_id: 3, target_count: 15 });
  });

  it("przypięte i z Championa idą osobno od podpowiedzi; tylko podpowiedź można przypiąć", async () => {
    generate.mockResolvedValue(kit());
    suggestedForJob.mockResolvedValue(
      suggestions([
        question("Pytanie przypięte", "pinned"),
        question("Pytanie z Championa", "legacy_champion"),
        question("Pytanie z podobnej rekrutacji", "similar_job"),
      ]),
    );
    render(<PrepPage />);
    await screen.findByText("Pytanie przypięte");
    const cards = screen.getAllByTestId("question");
    expect(cards.map((c) => [c.firstChild?.textContent, c.dataset.pinnable])).toEqual([
      ["Pytanie przypięte", "no"],
      ["Pytanie z Championa", "no"],
      ["Pytanie z podobnej rekrutacji", "yes"],
    ]);
    expect(screen.getByText(/Podpowiedzi/)).toBeInTheDocument();
    expect(screen.getByText("3 pytań łącznie")).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("bez pytań odsyła do zakładki Baza pytań tej rekrutacji", async () => {
    generate.mockResolvedValue(kit());
    suggestedForJob.mockResolvedValue(suggestions([]));
    render(<PrepPage />);
    const link = await screen.findByRole("link", { name: "zakładce Baza pytań" });
    expect(link).toHaveAttribute("href", "/jobs/7?tab=questions");
  });

  it("niepełna lista wg koperty pytań: baner z powodem z koperty", async () => {
    generate.mockResolvedValue(kit({ degraded: true, degraded_reason: "Powód z prep-kitu." }));
    suggestedForJob.mockResolvedValue(
      suggestions([question("Auto", "auto_generated")], { degraded: true, reason: "Qdrant milczy." }),
    );
    render(<PrepPage />);
    expect(await screen.findByRole("status")).toHaveTextContent("Qdrant milczy.");
  });

  it("niepełna lista wg samego prep-kitu też daje baner (wystarczy jedno źródło)", async () => {
    generate.mockResolvedValue(kit({ degraded: true, degraded_reason: "Powód z prep-kitu." }));
    suggestedForJob.mockResolvedValue(suggestions([question("Auto", "auto_generated")]));
    render(<PrepPage />);
    expect(await screen.findByRole("status")).toHaveTextContent("Powód z prep-kitu.");
  });

  it("niepełna lista bez podanego powodu: zdanie domyślne", async () => {
    generate.mockResolvedValue(kit({ degraded: true }));
    suggestedForJob.mockResolvedValue(suggestions([]));
    render(<PrepPage />);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Wyszukiwanie podobnych rekrutacji nie odpowiedziało",
    );
  });

  it("awaria wczytania: komunikat i „Spróbuj ponownie” wczytuje od nowa", async () => {
    generate.mockRejectedValueOnce(new Error("Limit czasu generacji.")).mockResolvedValueOnce(kit());
    suggestedForJob.mockResolvedValue(suggestions([]));
    render(<PrepPage />);
    expect(await screen.findByText("Nie udało się wczytać prep-kita")).toBeInTheDocument();
    expect(screen.getByText("Limit czasu generacji.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
    expect(await screen.findByText("Fikcyjny bank testowy, zespół płatności.")).toBeInTheDocument();
    expect(generate).toHaveBeenCalledTimes(2);
  });

  it("awaria bez obiektu Error: zdanie domyślne zamiast surowej wartości", async () => {
    generate.mockRejectedValueOnce("boom");
    suggestedForJob.mockResolvedValue(suggestions([]));
    render(<PrepPage />);
    expect(await screen.findByText("Błąd wczytywania prep-kita")).toBeInTheDocument();
  });

  it("ocena pytania odświeża listę", async () => {
    generate.mockResolvedValue(kit());
    suggestedForJob.mockResolvedValue(suggestions([question("Pytanie przypięte", "pinned")]));
    render(<PrepPage />);
    fireEvent.click(await screen.findByRole("button", { name: "oceń Pytanie przypięte" }));
    await waitFor(() => expect(suggestedForJob).toHaveBeenCalledTimes(2));
  });

  it("„← Projekt” wraca do rekrutacji", async () => {
    generate.mockResolvedValue(kit());
    suggestedForJob.mockResolvedValue(suggestions([]));
    render(<PrepPage />);
    await screen.findByText("Fikcyjny bank testowy, zespół płatności.");
    fireEvent.click(screen.getByRole("button", { name: "← Projekt" }));
    expect(push).toHaveBeenCalledWith("/jobs/7");
  });

  it("zły adres (bez liczby): komunikat i żadnego zapytania", () => {
    params.candidateId = "abc";
    render(<PrepPage />);
    expect(screen.getByText("Nieprawidłowe parametry URL")).toBeInTheDocument();
    expect(generate).not.toHaveBeenCalled();
  });
});
