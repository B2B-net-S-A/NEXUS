/**
 * Debrief i pytania klienta w „Notatki → Rozmowy” (zgłoszenie 04.11.2026):
 * po odrzuceniu para wypada z kalendarza, a pytania są potrzebne dalej.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listFeedback = vi.fn();
const apiGet = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: (...a: unknown[]) => apiGet(...a) },
  interviewFeedbackApi: { list: (...a: unknown[]) => listFeedback(...a) },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError, showSuccess }),
}));

import { ClientInterviewNotes } from "@/components/feedback/ClientInterviewNotes";
import type { NoteRecruitmentFilter } from "@/lib/candidate-notes-view";

const DEBRIEF = {
  id: 116,
  candidate_id: 42,
  job_id: 10,
  calendar_event_id: 7,
  feedback_source: "candidate_side",
  overall_impression: 5,
  offer_acceptance: "yes",
  acceptance_condition: null,
  concerns: "Rozmowa krótka",
  client_questions: "Co to piramida testów?\nWzorce projektowe",
  no_client_questions: false,
  author_name: "Marta Testowa",
  calendar_event_start: "2026-10-26T10:30:00Z",
};

const RECRUITMENTS = [
  {
    job_id: 10,
    job_title: "Tester automatyzujący",
    latest_stage: "rejected",
    last_seen: "2026-11-02T10:00:00Z",
  },
];

function renderNotes(jobFilter: NoteRecruitmentFilter = "all") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientInterviewNotes candidateId={42} recruitments={RECRUITMENTS} jobFilter={jobFilter} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  listFeedback.mockResolvedValue({ data: [DEBRIEF] });
  apiGet.mockResolvedValue({ data: [] });
});

describe("ClientInterviewNotes", () => {
  it("pokazuje pytania i notatkę po rozmowie także przy odrzuconej osobie", async () => {
    renderNotes();
    const card = await screen.findByRole("article", { name: /Po rozmowie u klienta/ });
    expect(card).toHaveTextContent("Co to piramida testów?");
    expect(card).toHaveTextContent("Wzorce projektowe");
    expect(card).toHaveTextContent("Pytania klienta (2)");
    expect(card).toHaveTextContent("Rozmowa krótka");
    expect(card).toHaveTextContent("Odrzucony");
    expect(card).toHaveTextContent("zapisał(a) Marta Testowa");
    expect(listFeedback).toHaveBeenCalledWith({ candidate_id: 42 });
  });

  it("nie rysuje niczego, gdy kandydat nie ma debriefu ani pytań", async () => {
    listFeedback.mockResolvedValue({
      data: [{ ...DEBRIEF, feedback_source: "client_side", offer_acceptance: null, client_questions: null }],
    });
    const { container } = renderNotes();
    await waitFor(() => expect(listFeedback).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("awaria pobrania mówi o awarii, nie udaje braku debriefu", async () => {
    listFeedback.mockRejectedValue(new Error("500"));
    renderNotes();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Nie udało się wczytać/);
  });

  it("słucha filtra rekrutacji z listy notatek", async () => {
    const { unmount } = renderNotes(10);
    expect(await screen.findByRole("article", { name: /Po rozmowie u klienta/ })).toBeInTheDocument();
    unmount();

    renderNotes(99);
    await waitFor(() => expect(listFeedback).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("article")).not.toBeInTheDocument());
  });

  it("rozmowa bez rekrutacji widoczna przy filtrze „bez rekrutacji”", async () => {
    listFeedback.mockResolvedValue({ data: [{ ...DEBRIEF, job_id: null }] });
    renderNotes("none");
    expect(await screen.findByRole("article", { name: /Po rozmowie u klienta/ })).toBeInTheDocument();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("„Kopiuj pytania” kopiuje same pytania, po jednym w wierszu", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    renderNotes();
    await user.click(await screen.findByRole("button", { name: "Kopiuj pytania" }));
    expect(writeText).toHaveBeenCalledWith("Co to piramida testów?\nWzorce projektowe");
    await waitFor(() => expect(showSuccess).toHaveBeenCalled());
  });

  it("nieudane kopiowanie mówi o tym wprost", async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("odmowa"));
    renderNotes();
    await user.click(await screen.findByRole("button", { name: "Kopiuj pytania" }));
    await waitFor(() => expect(showError).toHaveBeenCalled());
  });

  it("inne pytania z rekrutacji rozwijają się bez powtórek z tego debriefu", async () => {
    const user = userEvent.setup();
    apiGet.mockResolvedValue({
      data: [
        { id: 1, text: "  co to PIRAMIDA   testów? " },
        { id: 2, text: "Jak działa Playwright?" },
      ],
    });
    renderNotes();
    const toggle = await screen.findByRole("button", { name: /Inne pytania z rozmów w tej rekrutacji \(1\)/ });
    expect(screen.queryByText("Jak działa Playwright?")).not.toBeInTheDocument();
    await user.click(toggle);
    expect(screen.getByText("Jak działa Playwright?")).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith(
      "/api/interview-cycle/client-questions",
      expect.objectContaining({ params: expect.objectContaining({ job_id: 10 }) }),
    );
  });

  it("awaria innych pytań nie chowa debriefu", async () => {
    apiGet.mockRejectedValue(new Error("500"));
    renderNotes();
    expect(await screen.findByRole("alert")).toHaveTextContent(/innych pytań/);
    expect(screen.getByText("Co to piramida testów?")).toBeInTheDocument();
  });

  it("klient bez pytań: mówi to wprost i nie ma przycisku kopiowania", async () => {
    listFeedback.mockResolvedValue({
      data: [{ ...DEBRIEF, client_questions: null, no_client_questions: true }],
    });
    renderNotes();
    expect(await screen.findByText("Klient nie zadawał pytań.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Kopiuj pytania" })).not.toBeInTheDocument();
  });
});
