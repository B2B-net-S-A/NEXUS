/**
 * „Ściąga do rozmowy” w doku osoby: tekst na start z kopiowaniem, pytania
 * kandydata (brak w profilu → zdanie zastępcze + dopisanie do „Do dopytania”)
 * i trzy pytania z profilu. Pusta ściąga się nie renderuje.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  DockCallCheatsheet,
  MISSING_ANSWER_TEXT,
} from "@/components/v2/jobs/DockCallCheatsheet";
import { plainBriefQueryKey, type PlainBrief } from "@/lib/api/plainKnowledge";

const championGet = vi.fn();
const championPut = vi.fn();
const apiPost = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: vi.fn(() => Promise.reject(new Error("bez sieci w teście"))),
    post: (...a: unknown[]) => apiPost(...a),
    put: vi.fn(),
  },
  championApi: {
    get: (...a: unknown[]) => championGet(...a),
    put: (...a: unknown[]) => championPut(...a),
  },
}));

const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: (...a: unknown[]) => toastSuccess(...a),
    showError: (...a: unknown[]) => toastError(...a),
    showInfo: vi.fn(),
  }),
}));

const JOB_ID = 12;

function brief(patch: Partial<PlainBrief> = {}): PlainBrief {
  return {
    job_id: JOB_ID,
    status: "ready",
    stale: false,
    is_open: true,
    can_refresh: true,
    can_change_role: false,
    generated_at: "2026-09-29T08:00:00Z",
    message: null,
    one_liner: null,
    example: null,
    day_to_day: [],
    pitch: "Dzwonię w sprawie projektu w Banku Przykładowym.",
    candidate_qa: [
      { key: "rate", question: "Jaka stawka?", answer: "Do 150 zł/h netto.", source: "sekcja 1" },
      { key: "team", question: "Jak duży jest zespół?", answer: null, source: null },
    ],
    screening_plain: [
      { question_id: "q1", question: "Pytanie 1", why: null, good: "Dobra 1", reject: "Zła 1", original: null },
      { question_id: "q2", question: "Pytanie 2", why: null, good: "Dobra 2", reject: null, original: null },
      { question_id: "q3", question: "Pytanie 3", why: null, good: null, reject: null, original: null },
      { question_id: "q4", question: "Pytanie 4", why: null, good: null, reject: null, original: null },
    ],
    glossary: [],
    role: null,
    client: null,
    ...patch,
  };
}

function renderWith(data: PlainBrief) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } },
  });
  qc.setQueryData(plainBriefQueryKey(JOB_ID), data);
  return render(
    <QueryClientProvider client={qc}>
      <DockCallCheatsheet jobId={JOB_ID} />
    </QueryClientProvider>,
  );
}

describe("DockCallCheatsheet", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("brak odpowiedzi w profilu = zdanie zastępcze, nie pustka", async () => {
    const user = userEvent.setup();
    renderWith(brief());
    await user.click(screen.getByText("Jak duży jest zespół?"));
    expect(screen.getByText(MISSING_ANSWER_TEXT)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Dopisz do „Do dopytania”/ })).toBeInTheDocument();
  });

  it("dopisanie dokłada notatkę „ask_client” do świeżej listy notatek", async () => {
    const user = userEvent.setup();
    championGet.mockResolvedValue({
      data: {
        job_id: JOB_ID,
        champion_profile: {
          insights: [
            { id: "n-1", source: "client", topic: "needs", audience: "team", text: "Stara", origin: "manual", editable: true },
          ],
        },
      },
    });
    championPut.mockResolvedValue({ data: { job_id: JOB_ID, champion_profile: {} } });
    renderWith(brief());
    await user.click(screen.getByText("Jak duży jest zespół?"));
    await user.click(screen.getByRole("button", { name: /Dopisz do „Do dopytania”/ }));
    await waitFor(() => expect(championPut).toHaveBeenCalledTimes(1));
    const [jobId, payload] = championPut.mock.calls[0] as [number, { insights: { id: string; topic: string; text: string }[] }];
    expect(jobId).toBe(JOB_ID);
    expect(Object.keys(payload)).toEqual(["insights"]);
    expect(payload.insights.map((n) => n.id)[0]).toBe("n-1");
    expect(payload.insights[1]).toMatchObject({ topic: "ask_client", text: "Jak duży jest zespół?" });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(screen.getByText(/Dopisano do „Do dopytania”/)).toBeInTheDocument();
  });

  it("„Kopiuj” kopiuje tekst na start i mówi „Skopiowano”", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderWith(brief());
    await user.click(screen.getByTestId("cheatsheet-copy"));
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Skopiowano"));
    expect(writeText).toHaveBeenCalledWith("Dzwonię w sprawie projektu w Banku Przykładowym.");
  });

  it("pokazuje najwyżej trzy pytania z profilu, „Odpada” tylko przy powodzie", () => {
    renderWith(brief());
    const cards = screen.getAllByTestId("cheatsheet-question");
    expect(cards).toHaveLength(3);
    expect(cards[0]).toHaveTextContent("Odpada: Zła 1");
    expect(cards[1]).not.toHaveTextContent("Odpada");
  });

  it("pusta ściąga się nie renderuje", () => {
    const { container } = renderWith(
      brief({ pitch: null, candidate_qa: [], screening_plain: [] }),
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("aktualne wyjaśnienie nie odpala odświeżenia", () => {
    renderWith(brief());
    expect(apiPost).not.toHaveBeenCalled();
  });
});
