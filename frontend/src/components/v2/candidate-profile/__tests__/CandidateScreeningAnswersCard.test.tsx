/**
 * „Odpowiedzi z rozmów screeningowych” w zakładce Profil (02.10.2026).
 *
 * Zgłoszenie: po screeningu w profilu nie było widać, co kandydat odpowiedział,
 * więc to samo pytanie padało w kolejnej rekrutacji. Karta ma pokazać pytania
 * i odpowiedzi, dać je przeszukać, a awarii nie pokazywać jako pustki.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => apiGet(...a) },
}));

import { CandidateScreeningAnswersCard } from "@/components/v2/candidate-profile/CandidateScreeningAnswersCard";
import type { ScreeningConversation } from "@/lib/api/screeningAnswers";
import { useAuthStore } from "@/store/auth";

const NEWEST: ScreeningConversation = {
  stage_id: 501,
  job_id: 10,
  job_title: "Senior Java Developer",
  client_name: "Bank Przykładowy",
  answered_at: "2026-09-30T10:00:00Z",
  answered_by_name: "Rekruter Testowy",
  overall_fit: "fit",
  match_percent: 80,
  answers: [
    {
      question_id: "q1",
      question_text: "Czy pracowałeś na mikroserwisach?",
      response: "Tak, 3 lata. Kafka i Spring Boot.",
      deal_breaker_hit: false,
      skipped: false,
    },
    { question_id: "q2", question_text: "Od kiedy dostępny?", response: "", deal_breaker_hit: false, skipped: true },
  ],
  experience_checks: [],
  notes: "",
  internal_note: null,
};

const OLDER: ScreeningConversation = {
  stage_id: 400,
  job_id: 7,
  job_title: "Java Developer",
  client_name: "Telekom Przykładowy",
  answered_at: "2026-08-14T09:00:00Z",
  answered_by_name: null,
  overall_fit: "uncertain",
  match_percent: 50,
  answers: [
    { question_id: "q1", question_text: "Jaka forma umowy?", response: "Tylko B2B", deal_breaker_hit: false, skipped: false },
  ],
  experience_checks: [],
  notes: "",
  internal_note: null,
};

function renderCard(variant: "card" | "tab" = "card") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CandidateScreeningAnswersCard candidateId={42} variant={variant} />
    </QueryClientProvider>,
  );
}

const answersOf = (conversations: ScreeningConversation[]) => ({ data: { candidate_id: 42, conversations } });

const CARD_CONVERSATION = {
  job_id: 21,
  job_title: "Java Developer",
  client_name: "Bank Pocztowy Testowy",
  answered_at: "2025-02-03T10:00:00Z",
  author_name: null,
  note_id: 900,
  from_traffit: true,
  question_count: 3,
  answers: [
    { number: 1, question: "Doświadczenie z Javą 17+?", answer: "Java 17 od dwóch lat." },
    { number: 2, question: "", answer: "Kafka w projekcie płatności." },
  ],
};

/** Arkusze i karty przychodzą z dwóch tras — odpowiadamy po adresie. */
function respond(conversations: ScreeningConversation[], cardConversations: unknown[] = []) {
  apiGet.mockImplementation((url: string) =>
    Promise.resolve(
      url.endsWith("/recommendation-cards")
        ? { data: { candidate_id: 42, facts: [], note_links: [], conversations: cardConversations } }
        : answersOf(conversations),
    ),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: { id: 7, role: "recruiter" } } as never);
});

describe("CandidateScreeningAnswersCard", () => {
  it("pyta o odpowiedzi tego kandydata i pokazuje pytania z odpowiedziami najnowszej rozmowy", async () => {
    apiGet.mockResolvedValue(answersOf([NEWEST, OLDER]));
    renderCard();

    const card = await screen.findByRole("region", { name: "Odpowiedzi z rozmów screeningowych" });
    expect(apiGet).toHaveBeenCalledWith("/api/candidates/42/screening-answers");

    const newest = within(card).getByRole("button", { name: /Senior Java Developer · Bank Przykładowy/ });
    expect(newest).toHaveAttribute("aria-expanded", "true");
    expect(newest).toHaveTextContent("rozmowa: 30.09.2026 · Rekruter Testowy · 2 odpowiedzi");
    expect(newest).toHaveTextContent("Pasuje");
    expect(within(card).getByText(/Czy pracowałeś na mikroserwisach\?/)).toBeTruthy();
    expect(within(card).getByText("Tak, 3 lata. Kafka i Spring Boot.")).toBeTruthy();
    expect(within(card).getByText("— pominięte —")).toBeTruthy();
    expect(within(card).getByRole("link", { name: "Otwórz rekrutację" })).toHaveAttribute("href", "/jobs/10");

    // Starsza rozmowa jest zwinięta, dopóki ktoś jej nie otworzy.
    const older = within(card).getByRole("button", { name: /Java Developer · Telekom Przykładowy/ });
    expect(older).toHaveAttribute("aria-expanded", "false");
    expect(older).toHaveTextContent("rozmowa: 14.08.2026 · 1 odpowiedź");
    expect(older).toHaveTextContent("Niepewne");
    expect(within(card).queryByText("Tylko B2B")).toBeNull();
  });

  it("starszą rozmowę da się rozwinąć, a najnowszą zwinąć", async () => {
    const user = userEvent.setup();
    apiGet.mockResolvedValue(answersOf([NEWEST, OLDER]));
    renderCard();
    const card = await screen.findByRole("region", { name: "Odpowiedzi z rozmów screeningowych" });

    await user.click(within(card).getByRole("button", { name: /Java Developer · Telekom Przykładowy/ }));
    expect(within(card).getByText("Tylko B2B")).toBeTruthy();

    await user.click(within(card).getByRole("button", { name: /Senior Java Developer · Bank Przykładowy/ }));
    expect(within(card).queryByText("Tak, 3 lata. Kafka i Spring Boot.")).toBeNull();
    expect(within(card).getByText("Tylko B2B")).toBeTruthy();
  });

  it("szukanie zostawia pasujące odpowiedzi ze wszystkich rozmów; brak trafień mówi to wprost", async () => {
    const user = userEvent.setup();
    apiGet.mockResolvedValue(answersOf([NEWEST, OLDER]));
    renderCard();
    const card = await screen.findByRole("region", { name: "Odpowiedzi z rozmów screeningowych" });
    const search = within(card).getByRole("searchbox", { name: "Szukaj w odpowiedziach" });

    await user.type(search, "b2b");
    expect(within(card).getByText(/Jaka forma umowy\?/)).toBeTruthy();
    expect(within(card).queryByText(/Czy pracowałeś na mikroserwisach\?/)).toBeNull();
    expect(card.querySelector("mark")?.textContent).toBe("B2B");

    await user.clear(search);
    await user.type(search, "kubernetes");
    expect(within(card).getByRole("status")).toHaveTextContent("Żadna odpowiedź nie pasuje do „kubernetes”.");
  });

  it("przy jednej rozmowie nie ma pola szukania", async () => {
    apiGet.mockResolvedValue(answersOf([NEWEST]));
    renderCard();
    const card = await screen.findByRole("region", { name: "Odpowiedzi z rozmów screeningowych" });
    expect(within(card).queryByRole("searchbox")).toBeNull();
  });

  it("bez rozmów karty nie ma", async () => {
    apiGet.mockResolvedValue(answersOf([]));
    const { container } = renderCard();
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("awaria odczytu to komunikat z „Ponów”, nie pustka", async () => {
    const user = userEvent.setup();
    apiGet.mockRejectedValueOnce(new Error("500"));
    renderCard();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nie udało się wczytać odpowiedzi z rozmów.");

    apiGet.mockResolvedValue(answersOf([NEWEST]));
    await user.click(within(alert).getByRole("button", { name: "Ponów" }));
    expect(await screen.findByText("Tak, 3 lata. Kafka i Spring Boot.")).toBeTruthy();
  });

  it("bez zalogowanej osoby nie pyta serwera", () => {
    useAuthStore.setState({ user: null } as never);
    const { container } = renderCard();
    expect(apiGet).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it("pod arkuszami pokazuje odpowiedzi z kart rekomendacji w notatkach — zwinięte, z podpisem źródła", async () => {
    const user = userEvent.setup();
    respond([NEWEST], [CARD_CONVERSATION]);
    renderCard();
    const card = await screen.findByRole("region", { name: "Odpowiedzi z rozmów screeningowych" });

    const fromNote = await within(card).findByRole("button", {
      name: /Java Developer · Bank Pocztowy Testowy/,
    });
    expect(within(card).getByText("Z kart rekomendacji w notatkach")).toBeTruthy();
    expect(fromNote).toHaveAttribute("aria-expanded", "false");
    expect(fromNote).toHaveTextContent("03.02.2025 · 2 z 3 pytań · z karty wpisanej w Traffit");

    await user.click(fromNote);
    expect(within(card).getByText("1. Doświadczenie z Javą 17+?")).toBeTruthy();
    expect(within(card).getByText("Java 17 od dwóch lat.")).toBeTruthy();
    expect(within(card).getByText("2. pytanie bez treści w notatce")).toBeTruthy();
  });

  it("rekrutacja z arkuszem nie dubluje się odpowiedziami z notatki", async () => {
    respond([NEWEST], [{ ...CARD_CONVERSATION, job_id: NEWEST.job_id }]);
    renderCard();
    const card = await screen.findByRole("region", { name: "Odpowiedzi z rozmów screeningowych" });

    await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/api/candidates/42/recommendation-cards"));
    expect(within(card).queryByText("Z kart rekomendacji w notatkach")).toBeNull();
  });

  it("bez arkuszy karta żyje z samych notatek: najnowsza rozmowa rozwinięta, szukanie działa", async () => {
    const user = userEvent.setup();
    respond([], [CARD_CONVERSATION, { ...CARD_CONVERSATION, job_id: 22, job_title: "Tester", from_traffit: false }]);
    renderCard();
    const card = await screen.findByRole("region", { name: "Odpowiedzi z rozmów screeningowych" });

    expect(
      within(card).getByRole("button", { name: /Java Developer · Bank Pocztowy Testowy/ }),
    ).toHaveAttribute("aria-expanded", "true");
    await user.type(within(card).getByRole("searchbox", { name: "Szukaj w odpowiedziach" }), "płatności");
    expect(within(card).getAllByText("Kafka w projekcie płatności.").length).toBe(2);
    expect(within(card).queryByText("Java 17 od dwóch lat.")).toBeNull();
  });

  describe("zakładka „Odpowiedzi ze screeningu” (04.10.2026)", () => {
    it("bez rozmów mówi to zdaniem zamiast pustki", async () => {
      respond([]);
      renderCard("tab");
      expect(
        await screen.findByText(/Nikt jeszcze nie zapisał odpowiedzi z rozmowy screeningowej/),
      ).toBeInTheDocument();
    });

    it("czeka na karty rekomendacji, zanim powie, że nikt nic nie zapisał", async () => {
      let releaseCards: (value: unknown) => void = () => {};
      apiGet.mockImplementation((url: string) =>
        url.endsWith("/recommendation-cards")
          ? new Promise((resolve) => {
              releaseCards = resolve;
            })
          : Promise.resolve(answersOf([])),
      );
      renderCard("tab");
      expect(await screen.findByText("Wczytuję odpowiedzi z rozmów…")).toBeInTheDocument();
      expect(screen.queryByText(/Nikt jeszcze nie zapisał/)).toBeNull();
      releaseCards({
        data: { candidate_id: 42, facts: [], note_links: [], conversations: [CARD_CONVERSATION] },
      });
      expect(await screen.findByText("Kafka w projekcie płatności.")).toBeInTheDocument();
    });

    it("awaria kart rekomendacji to komunikat z „Ponów”, nie „nikt nie zapisał”", async () => {
      apiGet.mockImplementation((url: string) =>
        url.endsWith("/recommendation-cards")
          ? Promise.reject(new Error("500"))
          : Promise.resolve(answersOf([])),
      );
      renderCard("tab");
      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("Nie udało się wczytać odpowiedzi z kart rekomendacji.");
      expect(within(alert).getByRole("button", { name: "Ponów" })).toBeInTheDocument();
      expect(screen.queryByText(/Nikt jeszcze nie zapisał/)).toBeNull();
    });

    it("szukanie działa już przy jednej rozmowie", async () => {
      respond([NEWEST]);
      renderCard("tab");
      const tab = await screen.findByRole("region", { name: "Odpowiedzi z rozmów screeningowych" });
      expect(within(tab).getByRole("searchbox", { name: "Szukaj w odpowiedziach" })).toBeInTheDocument();
    });
  });
});
