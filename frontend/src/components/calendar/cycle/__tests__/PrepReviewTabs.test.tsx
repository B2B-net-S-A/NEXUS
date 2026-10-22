import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PrepReviewDialog } from "@/components/calendar/cycle/PrepReviewDialog";
import { Prep2FollowupFromPrep1, PrepStepReview } from "@/components/calendar/cycle/PrepStepReview";
import {
  cueIndexForQuote,
  formatCueTime,
  prepQueryKey,
  prepTranscriptQueryKey,
  type Prep,
  type PrepTranscript,
} from "@/lib/api/prepMeetings";

const FRESH = { updatedAt: Date.now() + 86_400_000 };

function v2Prep(partial: Partial<Prep> = {}): Prep {
  return {
    event_id: 603,
    prep_no: 1,
    candidate_id: 2,
    job_id: 3,
    organizer: { id: 8, name: "Kasia DL" },
    start: "2031-06-10T10:00:00Z",
    end: "2031-06-10T10:45:00Z",
    online_meeting_url: null,
    transcription_setup: "enabled",
    transcript_status: "fetched",
    talk_share: null,
    duration_seconds: 37 * 60,
    review: {
      status: "ok",
      level: "ok",
      coverage: 0.72,
      config_version: 2,
      summary: "Dobre projekty, Kafka ogólnie.",
      remaining: ["Kafka"],
      criteria: {
        version: 2,
        total: 72,
        caps: ["required_topic_missing"],
        scores: { topics: 50, must_answers: 50, client_questions: null, talk_share: null },
        weights_used: { topics: 25, must_answers: 40 },
        topics: [
          { key: "topic:0", label: "Klient i projekt", required: true, status: "covered", quote: "zespół płatności" },
          { key: "topic:1", label: "Przebieg rozmowy", required: true, status: "missing", quote: null },
        ],
        answers: [
          { key: "must:Java", label: "Java", kind: "must", grade: "strong", quote: "migrowałam na Javę 21", note: null },
          { key: "must:Kafka", label: "Kafka", kind: "must", grade: "weak", quote: "głównie konsumowanie zdarzeń", note: "Jeden przypadek z liczbami." },
        ],
        went_well: ["Projekt z liczbami"],
        went_wrong: ["Kafka bez przykładu"],
        improve: ["Omów przebieg rozmowy"],
        followup: [
          { key: "must:Kafka", label: "Kafka", kind: "must", reason: "weak", quote: "głównie konsumowanie zdarzeń", note: "Jeden przypadek z liczbami." },
          { key: "topic:1", label: "Przebieg rozmowy", kind: "topic", reason: "missing_topic", quote: null, note: null },
        ],
        comparison: [],
        items: [],
      },
    },
    ...partial,
  };
}

const TRANSCRIPT: PrepTranscript = {
  event_id: 603,
  speakers: [],
  text: "",
  fetched_at: "2031-06-10T11:00:00Z",
  cues: [
    { start: 10, speaker: null, role: null, text: "Klient to zespół płatności." },
    { start: 845, speaker: null, role: null, text: "Z Kafką pracowałam, głównie konsumowanie zdarzeń, resztą inny zespół." },
  ],
};

function withQueries(prep: Prep, transcript?: PrepTranscript) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(prepQueryKey(prep.event_id), prep, FRESH);
  if (transcript) client.setQueryData(prepTranscriptQueryKey(prep.event_id), transcript, FRESH);
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

describe("helpers", () => {
  it("formatCueTime", () => {
    expect(formatCueTime(845)).toBe("14:05");
    expect(formatCueTime(3725)).toBe("1:02:05");
  });

  it("cueIndexForQuote znajduje cytat, także dłuższy niż jedna wypowiedź", () => {
    expect(cueIndexForQuote(TRANSCRIPT.cues!, "głównie konsumowanie zdarzeń")).toBe(1);
    expect(cueIndexForQuote(TRANSCRIPT.cues!, "Klient to zespół płatności. Pracujemy w Scrumie od lat, sprinty po dwa tygodnie")).toBe(0);
    expect(cueIndexForQuote(TRANSCRIPT.cues!, null)).toBe(-1);
  });
});

describe("PrepReviewDialog v2", () => {
  it("pokazuje wynik z wagami, regułę „najwyżej OK” i link do ustawień", () => {
    render(<PrepReviewDialog open onOpenChange={() => {}} eventId={603} pair={null} />, {
      wrapper: withQueries(v2Prep(), TRANSCRIPT),
    });
    expect(screen.getByText("OK · 72%")).toBeInTheDocument();
    expect(screen.getByText(/pominięty temat obowiązkowy/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Jak liczona jest ocena" })).toHaveAttribute("href", "/settings/prep-review");
    expect(screen.getByText("bez mówców — nie liczone")).toBeInTheDocument();
    expect(screen.getByText("Słaba")).toBeInTheDocument();
    expect(screen.getByText("Przećwicz: Jeden przypadek z liczbami.")).toBeInTheDocument();
  });

  it("prep za krótki: „Słaby, bo…”, nie „Najwyżej OK” (audyt 22.10, F40)", () => {
    const base = v2Prep();
    const prep = v2Prep({
      review: {
        ...base.review!,
        level: "weak",
        criteria: { ...base.review!.criteria, total: 85, caps: ["too_short"] },
      },
    });
    render(<PrepReviewDialog open onOpenChange={() => {}} eventId={603} pair={null} />, {
      wrapper: withQueries(prep, TRANSCRIPT),
    });
    expect(screen.getByText("Słaby · 85%")).toBeInTheDocument();
    expect(screen.queryByText(/Najwyżej „OK”/)).toBeNull();
    expect(screen.getByText(/Słaby, bo: prep krótszy niż minimum z ustawień/)).toBeInTheDocument();
  });

  it("udział kandydata wyłączony w ustawieniach nie udaje braku mówców (audyt 22.10, F43)", () => {
    render(<PrepReviewDialog open onOpenChange={() => {}} eventId={603} pair={null} />, {
      wrapper: withQueries(v2Prep({ talk_share: 0.6 }), TRANSCRIPT),
    });
    expect(screen.queryByText("bez mówców — nie liczone")).toBeNull();
    expect(screen.getByText("wyłączone w ustawieniach")).toBeInTheDocument();
  });

  it("cytat przenosi do transkryptu i podświetla wypowiedź", () => {
    render(<PrepReviewDialog open onOpenChange={() => {}} eventId={603} pair={null} />, {
      wrapper: withQueries(v2Prep(), TRANSCRIPT),
    });
    fireEvent.click(screen.getByRole("button", { name: /„głównie konsumowanie zdarzeń”/ }));
    expect(screen.getByRole("tab", { name: "Transkrypt" })).toHaveAttribute("aria-selected", "true");
    const focused = document.querySelector('[data-focused="true"]');
    expect(focused?.textContent).toContain("14:05");
    expect(screen.getByText(/Bez podziału na mówców/)).toBeInTheDocument();
  });

  it("zakładka podsumowania ma wnioski i notatkę na Prep 2", () => {
    render(
      <PrepReviewDialog open onOpenChange={() => {}} eventId={603} pair={null} initialTab="summary" />,
      { wrapper: withQueries(v2Prep(), TRANSCRIPT) },
    );
    expect(screen.getByText("Kafka bez przykładu")).toBeInTheDocument();
    const note = screen.getByText("Do powtórzenia na Prepie 2").parentElement!;
    expect(within(note).getByText("Słaba odp.")).toBeInTheDocument();
    expect(within(note).getByText("Temat pominięty")).toBeInTheDocument();
  });

  it("Prep 2 pokazuje, co się poprawiło od Prepu 1", () => {
    const prep2 = v2Prep({ prep_no: 2 });
    prep2.review!.criteria.comparison = [
      { key: "must:Kafka", label: "Kafka", before: "weak", after: "strong", quote: null },
    ];
    render(
      <PrepReviewDialog open onOpenChange={() => {}} eventId={603} pair={null} initialTab="summary" />,
      { wrapper: withQueries(prep2) },
    );
    expect(screen.getByText("Na rozmowę u klienta nie zostało nic z Prepu 1.")).toBeInTheDocument();
  });

  it("ocena sprzed v2 nie ma zakładki podsumowania", () => {
    const old = v2Prep();
    old.review = { ...old.review!, criteria: { items: [], own_projects: { told: false, quote: null } } };
    render(<PrepReviewDialog open onOpenChange={() => {}} eventId={603} pair={null} />, {
      wrapper: withQueries(old),
    });
    expect(screen.queryByRole("tab", { name: "Podsumowanie i follow-up" })).not.toBeInTheDocument();
    expect(screen.getByText("Ocena: OK")).toBeInTheDocument();
  });
});

describe("Karta osoby", () => {
  it("krok Prep pokazuje wynik prowadzącego i kandydata oraz wejścia do oceny", () => {
    const opened: string[] = [];
    render(<PrepStepReview eventId={603} onOpen={(tab) => opened.push(tab)} />, {
      wrapper: withQueries(v2Prep()),
    });
    expect(screen.getByText(/1 z 2 tematów/)).toBeInTheDocument();
    expect(screen.getByText(/1 mocne · 0 ogólne · 1 słabe/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Transkrypt" }));
    expect(opened).toEqual(["transcript"]);
  });

  it("krok Prep 2 pokazuje listę do powtórzenia z oceny Prepu 1", () => {
    render(<Prep2FollowupFromPrep1 prep1EventId={603} />, { wrapper: withQueries(v2Prep()) });
    expect(screen.getByText("Do powtórzenia na Prepie 2")).toBeInTheDocument();
    expect(screen.getByText("Przebieg rozmowy")).toBeInTheDocument();
  });
});
