/**
 * Pusta kolejka nie znaczy „porcja przejrzana”, a screeningi bez wyniku muszą
 * być pod ręką: po 2 dniach roboczych znów blokują wyszukiwanie.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewBatchScreen } from "@/components/v2/review-batch/ReviewBatchScreen";
import type { ReviewBatchStatus } from "@/lib/api/reviewBatch";

const api = vi.hoisted(() => ({
  status: {} as Record<string, unknown>,
  queue: {} as Record<string, unknown>,
  setFocus: vi.fn(),
}));

vi.mock("@tanstack/react-query", async (original) => ({
  ...(await original<typeof import("@tanstack/react-query")>()),
  useQueryClient: () => ({}),
}));
const noAnswer = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useNoAnswerNote", () => ({
  useNoAnswerNote: () => ({ mutate: noAnswer, isPending: false }),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }),
}));
// Podgląd CV ładuje się przez `dynamic()`: przy obciążonym CI chunk zdążał się
// wczytać w trakcie testu i panel wołał prawdziwe `useQuery` („No QueryClient
// set”, 25.11.2026). Ekran Porcji testujemy bez niego.
vi.mock("@/components/v2/screening-form/CandidatePreviewPane", () => ({
  CandidatePreviewPane: () => <div data-testid="candidate-preview" />,
}));
vi.mock("@/components/v2/review-batch/ReviewBatchCard", () => ({
  ReviewBatchCard: () => <div data-testid="review-batch-card" />,
}));
const poligon = vi.hoisted(() => ({ lesson: false }));
vi.mock("@/lib/poligon/mode", () => ({ isNoveltyPractice: () => poligon.lesson }));
vi.mock("@/lib/api/plainKnowledge", () => ({
  usePlainBrief: () => ({ data: null }),
}));
vi.mock("@/lib/api/reviewBatch", () => ({
  addMoreFromNexus: vi.fn(),
  invalidateReviewBatch: vi.fn(),
  setReviewBatchFocus: api.setFocus,
  useReviewBatchStatus: () => api.status,
  useReviewBatchQueue: () => api.queue,
  useReviewBatchFocusOptions: () => ({
    isSuccess: true,
    isError: false,
    data: {
      seats: 10,
      focus: null,
      items: [{ job_id: 11, title: "Java Developer", pending: 0, p0: false, group: "p1", team_size: 2, picked_by: [] }],
    },
  }),
  useReviewBatchFocusPreview: () => ({ isSuccess: false, isError: false }),
}));

const blocked: ReviewBatchStatus = {
  enabled: true,
  applies: true,
  minimum: 10,
  done_today: 0,
  pending: 0,
  required: 10,
  remaining: 10,
  met: false,
  blocks: true,
  open_screenings: 2,
  open_today_screenings: [
    { job_id: 11, job_title: "Java Developer", candidate_id: 101, name: "Jan Testowy" },
    { job_id: 12, job_title: "Analityk", candidate_id: 102, name: "Ewa Próbna" },
  ],
  jobs: [],
  team_jobs: [{ job_id: 11, title: "Java Developer", pending: 0, p0: false }],
};

function given(status: Partial<ReviewBatchStatus>, queue: Record<string, unknown> = {}) {
  api.status = { isPending: false, isError: false, data: { ...blocked, ...status } };
  api.queue = { data: { items: [] }, isLoading: false, isError: false, isSuccess: true, ...queue };
}

describe("ReviewBatchScreen przy pustej kolejce", () => {
  beforeEach(() => given({}));

  it("zakładka „Do domknięcia” prowadzi do screeningu na Tablicy", () => {
    render(<ReviewBatchScreen />);
    fireEvent.click(screen.getByRole("tab", { name: /Do domknięcia/ }));
    expect(screen.getByRole("link", { name: "Otwórz screening" }).getAttribute("href")).toBe(
      "/jobs/11?candidate=101",
    );
    expect(screen.getByTestId("review-batch-open-today").textContent).toMatch(/Ewa Próbna/);
  });

  it("zakładka „Rekrutacje” pozwala dobrać osoby w przejrzanej rekrutacji", () => {
    render(<ReviewBatchScreen />);
    fireEvent.click(screen.getByRole("tab", { name: /Rekrutacje/ }));
    expect(screen.getByRole("button", { name: /Dodaj 20 kolejnych/ })).toBeTruthy();
  });

  it("screening po terminie otwiera „Do domknięcia” i mówi, co odblokuje wyszukiwanie", () => {
    given({
      met: false,
      done_today: 10,
      remaining: 0,
      overdue_screenings: 1,
      open_today_screenings: [
        { job_id: 11, job_title: "Java Developer", candidate_id: 101, name: "Jan Testowy", overdue: true },
      ],
    });
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-batch-open-today").textContent).toMatch(/po terminie/);
    expect(screen.getByText(/Wyszukiwanie wróci po domknięciu 1 screeningu/)).toBeTruthy();
    expect(screen.getByText("Wyszukiwanie zablokowane")).toBeTruthy();
  });

  it("lekcja nowości na Poligonie startuje od „Do decyzji”, choć screening jest po terminie (25.11.2026)", () => {
    // Lekcje „Porcja” każą kliknąć coś na karcie osoby, a ta stoi tylko w „Do decyzji”.
    // Rano z zaległym screeningiem ekran otwierał się na „Do domknięcia”, pokaz
    // (same „Rozumiem”) tego nie mówił i ludzie kończyli furtką po 45 s.
    poligon.lesson = true;
    try {
      given(
        {
          overdue_screenings: 1,
          pending: 1,
          open_today_screenings: [
            { job_id: 11, job_title: "Java Developer", candidate_id: 101, name: "Jan Testowy", overdue: true },
          ],
        },
        { data: { items: [{ process_id: 1, stage_id: 2, job_id: 11, job_title: "Java Developer", candidate_id: 7, name: "Ola" }] } },
      );
      render(<ReviewBatchScreen />);
      expect(screen.getByRole("tab", { name: /Do decyzji/ }).getAttribute("aria-selected")).toBe("true");
      expect(screen.getByTestId("review-batch-card")).toBeTruthy();
    } finally {
      poligon.lesson = false;
    }
  });

  it("„Nie odebrał” przy screeningu do domknięcia zapisuje próbę, a próba zdejmuje „po terminie” (23.11.2026)", () => {
    given({
      met: true,
      done_today: 10,
      remaining: 0,
      overdue_screenings: 0,
      open_today_screenings: [
        {
          job_id: 11,
          job_title: "Java Developer",
          candidate_id: 101,
          name: "Jan Testowy",
          attempts: 2,
          last_attempt_at: new Date().toISOString(),
        },
      ],
    });
    render(<ReviewBatchScreen />);
    fireEvent.click(screen.getByRole("tab", { name: /Do domknięcia/ }));
    const list = screen.getByTestId("review-batch-open-today");
    expect(list.textContent).toMatch(/nie odebrał ×2/);
    expect(list.textContent).toMatch(/Ostatnia próba dziś/);
    expect(list.textContent).not.toMatch(/po terminie/);
    fireEvent.click(screen.getByRole("button", { name: /Nie odebrał/ }));
    expect(noAnswer).toHaveBeenCalledTimes(1);
  });

  it("po 3 próbach bez odpowiedzi karta jest po terminie i mówi, co dalej (23.11.2026)", () => {
    given({
      met: false,
      done_today: 10,
      remaining: 0,
      overdue_screenings: 1,
      open_today_screenings: [
        { job_id: 11, job_title: "Java Developer", candidate_id: 101, name: "Jan Testowy", overdue: true, attempts: 3 },
      ],
    });
    render(<ReviewBatchScreen />);
    const list = screen.getByTestId("review-batch-open-today");
    expect(list.textContent).toMatch(/po terminie/);
    expect(screen.getByTestId("review-batch-attempts-used").textContent).toMatch(/3 prób bez odpowiedzi/);
  });

  it("screening z rekrutacji, z której zdjęto osobę, stoi na końcu bez terminu i poza licznikiem (13.11.2026)", () => {
    given({
      met: true,
      done_today: 10,
      remaining: 0,
      overdue_screenings: 0,
      open_today_screenings: [
        { job_id: 12, job_title: "Analityk", candidate_id: 102, name: "Ewa Próbna", parked: true },
        { job_id: 11, job_title: "Java Developer", candidate_id: 101, name: "Jan Testowy" },
      ],
    });
    render(<ReviewBatchScreen />);
    const tab = screen.getByRole("tab", { name: /Do domknięcia/ });
    expect(tab.textContent).toMatch(/1$/);
    fireEvent.click(tab);
    const list = screen.getByTestId("review-batch-open-today");
    expect(list.textContent).toMatch(/Jan Testowy.*Zdjęto Cię z tych rekrutacji: 1.*Ewa Próbna.*bez terminu/);
    expect(list.textContent).not.toMatch(/po terminie/);
    expect(screen.getByText("Wyszukiwanie działa")).toBeTruthy();
  });

  it("po minimum przypomina o terminie niedomkniętych screeningów", () => {
    given({ met: true, done_today: 10, remaining: 0 });
    render(<ReviewBatchScreen />);
    expect(screen.getByText(/bez wyniku w 2 dni robocze/)).toBeTruthy();
    expect(screen.getByText("Wyszukiwanie działa")).toBeTruthy();
  });

  it("bez listy i bez minimum nie twierdzi, że porcja jest przejrzana", () => {
    given({ open_today_screenings: [], team_jobs: [] });
    render(<ReviewBatchScreen />);
    expect(screen.queryByText(/Porcja przejrzana/)).toBeNull();
    expect(screen.getByTestId("review-batch-empty").textContent).toMatch(/minimum/i);
  });

  it("bez przypisanych rekrutacji mówi to wprost, a nie „Porcja przejrzana” (audyt 12.11.2026, R4)", () => {
    // Serwer: brak kart → `required = min(minimum, done + 0) = 0`, więc `met = true`.
    given({
      required: 0,
      remaining: 0,
      met: true,
      blocks: false,
      open_screenings: 0,
      open_today_screenings: [],
      team_jobs: [],
    });
    render(<ReviewBatchScreen />);
    expect(screen.queryByText(/Porcja przejrzana/)).toBeNull();
    const empty = screen.getByTestId("review-batch-no-jobs");
    expect(empty.textContent).toMatch(/Nie masz przypisanych rekrutacji/);
    expect(empty.textContent).toMatch(/Poproś Delivery Leada o przypisanie/);
    expect(screen.queryByText(/0 z 0/)).toBeNull();
  });

  it("screening do domknięcia zostaje pod ręką także bez przypisanych rekrutacji", () => {
    given({ required: 0, remaining: 0, met: true, team_jobs: [] });
    render(<ReviewBatchScreen />);
    expect(screen.queryByTestId("review-batch-no-jobs")).toBeNull();
  });

  it("po zrobionym minimum zostaje „Porcja przejrzana”", () => {
    given({ met: true, done_today: 10, remaining: 0, open_today_screenings: [], open_screenings: 0 });
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-batch-empty").textContent).toMatch(/Porcja przejrzana/);
  });

  it("w przerwie między ponowieniami zapytania nie pokazuje pustego stanu", () => {
    given({}, { data: undefined, isLoading: false, isError: false, isSuccess: false });
    render(<ReviewBatchScreen />);
    expect(screen.queryByTestId("review-batch-open-today")).toBeNull();
    expect(screen.queryByTestId("review-batch-empty")).toBeNull();
    expect(screen.getByText("Ładowanie osób…")).toBeTruthy();
  });

  it("awaria kolejki nie wygląda jak pusta porcja", () => {
    given({}, { data: undefined, isError: true, isSuccess: false, error: new Error("x") });
    render(<ReviewBatchScreen />);
    expect(screen.getByRole("alert").textContent).toMatch(/Nie udało się/);
    expect(screen.queryByTestId("review-batch-open-today")).toBeNull();
  });
});

describe("ReviewBatchScreen: porcja na osobę, P0 najpierw (10.11.2026)", () => {
  const p0Until = "2026-11-11T09:16:00Z";

  it("Rekrutacje w grupach priorytetu; niższe czekają „po P0”, nie dają „Dodaj”", () => {
    given({
      pending: 10,
      sources: { p0: 10, rest: 0, level_next: 20, level_cap: 50 },
      team_jobs: [
        { job_id: 1, title: "Commercial Cards", pending: 10, p0: true, group: "p0", via: "collaborator", p0_until: p0Until },
        { job_id: 2, title: "Pega Developer", pending: 0, p0: false, group: "p1", via: "owner" },
        { job_id: 3, title: "Muzeum", pending: 0, p0: false, group: "accepting", via: "collaborator" },
      ],
    });
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-batch-sources").textContent).toMatch(/10 z P0.*0 z P1 i niżej.*jutro 20/);
    fireEvent.click(screen.getByRole("tab", { name: /Rekrutacje/ }));
    const grouped = screen.getByTestId("review-batch-jobs-grouped");
    expect(grouped.textContent).toMatch(/P0.*Commercial Cards.*P1 Pilne.*Pega Developer.*Przyjmujemy kandydatów.*Muzeum/);
    expect(screen.getAllByText("po P0")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /Dodaj 20 kolejnych/ })).toBeNull();
  });

  it("bez osób w porcji „Dodaj” wraca w najwyższej grupie", () => {
    given({
      sources: { p0: 0, rest: 0, level_next: 20, level_cap: 50 },
      team_jobs: [{ job_id: 2, title: "Pega Developer", pending: 0, p0: false, group: "p1", via: "owner" }],
    });
    render(<ReviewBatchScreen />);
    fireEvent.click(screen.getByRole("tab", { name: /Rekrutacje/ }));
    expect(screen.getByRole("button", { name: /Dodaj 20 kolejnych/ })).toBeTruthy();
  });

  it("nad osobą mówi, dlaczego jest w Twojej porcji", () => {
    given(
      { pending: 1, sources: { p0: 1, rest: 0, level_next: 20, level_cap: 50 } },
      {
        data: {
          items: [
            {
              process_id: 1,
              stage_id: 1,
              job_id: 1,
              job_title: "Commercial Cards",
              candidate_id: 5,
              name: "Adam",
              city: null,
              years: null,
              position: null,
              score: 77,
              matched_must: [],
              missing_must: [],
              rate_from_hourly: null,
              rate_currency: null,
              availability_status: null,
              cautions: [],
              budget_hourly: null,
              why: { source: "p0", via: "collaborator", p0_until: p0Until },
            },
          ],
        },
      },
    );
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-why").textContent).toMatch(/Masz tę osobę, bo:.*Twoja rekrutacja \(współpraca\).*P0 do/);
  });
});

describe("ReviewBatchScreen: kolejka rekrutacja po rekrutacji (17.11.2026)", () => {
  function item(processId: number, jobId: number, jobTitle: string) {
    return {
      process_id: processId,
      stage_id: processId,
      job_id: jobId,
      job_title: jobTitle,
      candidate_id: processId,
      name: `Osoba ${processId}`,
      city: null,
      years: null,
      position: null,
      score: 70,
      matched_must: [],
      missing_must: [],
      rate_from_hourly: null,
      rate_currency: null,
      availability_status: null,
      cautions: [],
      budget_hourly: null,
    };
  }

  it("nad kartą mówi, ile zostało w tej rekrutacji i która następna", () => {
    given(
      {
        pending: 7,
        team_jobs: [
          { job_id: 1, title: "DevOps Lead", pending: 2, p0: true },
          { job_id: 2, title: "Senior IT developer GCOP", pending: 4, p0: true },
          { job_id: 3, title: "Analityk", pending: 1, p0: false },
        ],
      },
      {
        data: {
          items: [item(1, 1, "DevOps Lead"), item(2, 1, "DevOps Lead"), item(3, 2, "Senior IT developer GCOP")],
          runs: [
            { job_id: 1, count: 2 },
            { job_id: 2, count: 4 },
            { job_id: 3, count: 1 },
          ],
        },
      },
    );
    render(<ReviewBatchScreen />);
    const line = screen.getByTestId("review-queue-run").textContent;
    expect(line).toMatch(/Ta rekrutacja: jeszcze 2 osoby/);
    expect(line).toMatch(/Potem: Senior IT developer GCOP \(4\) i 1 kolejna/);
  });

  it("dwie rekrutacje: bez dopisku o kolejnych", () => {
    given(
      { pending: 5 },
      {
        data: {
          items: [item(1, 1, "DevOps Lead")],
          runs: [
            { job_id: 1, count: 1 },
            { job_id: 2, count: 4 },
          ],
        },
      },
    );
    render(<ReviewBatchScreen />);
    const line = screen.getByTestId("review-queue-run").textContent;
    expect(line).toMatch(/jeszcze 1 osoba/);
    expect(line).toMatch(/Potem: kolejna rekrutacja \(4\)$/);
  });

  it("ostatnia albo jedyna rekrutacja w kolejce: bez linii", () => {
    given(
      { pending: 2 },
      { data: { items: [item(1, 1, "DevOps Lead")], runs: [{ job_id: 1, count: 2 }] } },
    );
    render(<ReviewBatchScreen />);
    expect(screen.queryByTestId("review-queue-run")).toBeNull();
  });

  it("karty bez decyzji od 2 dni roboczych: linia „Na końcu porcji” z dniami (R5)", () => {
    given(
      { pending: 3 },
      {
        data: {
          items: [
            item(1, 1, "DevOps Lead"),
            { ...item(2, 2, "Analityk"), stale: true, opened_on: "2026-11-18" },
            { ...item(3, 2, "Analityk"), stale: true, opened_on: "2026-11-19" },
          ],
          runs: [
            { job_id: 1, count: 1 },
            { job_id: 2, count: 2 },
          ],
        },
      },
    );
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-queue-stale").textContent).toMatch(
      /Na końcu porcji: 2 karty z 18\.11–19\.11 bez decyzji od 2 dni roboczych/,
    );
  });

  it("bez odłożonych kart: bez linii", () => {
    given({ pending: 1 }, { data: { items: [item(1, 1, "DevOps Lead")], runs: [] } });
    render(<ReviewBatchScreen />);
    expect(screen.queryByTestId("review-queue-stale")).toBeNull();
  });

  it("linia liczy odłożone z całej kolejki, nie ze strony 20 kart (24.11.2026)", () => {
    // Konto z 22 odłożonymi po 10 decyzjach: na stronie widać tylko 2 z nich.
    given(
      { pending: 32 },
      {
        data: {
          items: [
            item(1, 1, "DevOps Lead"),
            { ...item(2, 2, "Analityk"), stale: true, opened_on: "2026-11-18" },
            { ...item(3, 2, "Analityk"), stale: true, opened_on: "2026-11-18" },
          ],
          runs: [
            { job_id: 1, count: 10 },
            { job_id: 2, count: 22 },
          ],
          stale: { count: 22, first: "2026-11-18", last: "2026-11-20" },
        },
      },
    );
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-queue-stale").textContent).toMatch(
      /Na końcu porcji: 22 karty z 18\.11–20\.11 bez decyzji od 2 dni roboczych/,
    );
  });
});

describe("ReviewBatchScreen: 12 pilnych + 8 pozostałych (R2, 22.11.2026)", () => {
  it("skład porcji: pilne, pozostałe i miejsca czekające na niepilne", () => {
    given({
      pending: 20,
      required: 20,
      sources: { p0: 4, rest: 16, level_next: 20, level_cap: 20, urgent: 12, other: 8, other_seats: 8, stale: 0 },
    });
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-batch-sources").textContent).toMatch(
      /12 z pilnych.*8 z pozostałych.*8 miejsc czeka na rekrutacje bez pilnego priorytetu/,
    );
  });

  it("bez rekrutacji niepilnych: bez dopisku o miejscach", () => {
    given({
      pending: 20,
      required: 20,
      sources: { p0: 20, rest: 0, level_next: 20, level_cap: 20, urgent: 20, other: 0, other_seats: 0, stale: 0 },
    });
    render(<ReviewBatchScreen />);
    const text = screen.getByTestId("review-batch-sources").textContent;
    expect(text).toMatch(/20 z pilnych/);
    expect(text).not.toMatch(/miejsc/);
    expect(screen.queryByTestId("review-batch-stale")).toBeNull();
  });

  it("odłożone osobno: podział sumuje się do porcji, obok „+14 odłożonych” (24.11.2026)", () => {
    // Konto 119 na kopii z 24.11: porcja 20, w kolejce 20 świeżych i 14 odłożonych.
    given({
      pending: 34,
      required: 20,
      sources: { p0: 0, rest: 34, level_next: 20, level_cap: 20, urgent: 12, other: 8, other_seats: 8, stale: 14 },
    });
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-batch-sources").textContent).toMatch(
      /Twoja porcja dziś: 20 ·\s*12 z pilnych\s*8 z pozostałych\s*\+14 odłożonych/,
    );
    expect(screen.getByTestId("review-batch-stale").getAttribute("title")).toMatch(
      /nie zajmują miejsca w porcji/,
    );
  });

  it("jedna odłożona: „+1 odłożona”", () => {
    given({
      pending: 21,
      required: 20,
      sources: { p0: 0, rest: 21, level_next: 20, level_cap: 20, urgent: 12, other: 8, other_seats: 8, stale: 1 },
    });
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-batch-stale").textContent).toBe("+1 odłożona");
  });
});

describe("ReviewBatchScreen: rekrutacja wybrana na dziś (zgłoszenie rekruterów 16.11.2026)", () => {
  const sources = { p0: 0, rest: 3, level_next: 10, level_cap: 20, urgent: 3, other: 0, other_seats: 0, stale: 0 };

  beforeEach(() => api.setFocus.mockReset());

  it("bez wyboru pasek ma „Wybierz rekrutację na dziś”, a klik daje listę zamiast zakładek", () => {
    given({ pending: 3, sources });
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-batch-sources").textContent).toMatch(/najpierw pilne/);
    fireEvent.click(screen.getByTestId("review-focus-open"));
    expect(screen.getByTestId("review-focus-picker").textContent).toMatch(/Java Developer/);
    expect(screen.getByRole("tablist").className).toMatch(/hidden/);
    fireEvent.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(screen.queryByTestId("review-focus-picker")).toBeNull();
  });

  it("z wyborem pasek mówi, skąd najpierw, a „Wróć do zwykłej kolejności” kasuje wybór", async () => {
    api.setFocus.mockResolvedValue({ focus: null, released: 0, added: 0 });
    given({ pending: 3, sources, focus: { job_id: 11, at: "2026-11-24T08:00:00Z" } });
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-focus-line").textContent).toMatch(
      /Najpierw z wybranej na dziś:Java Developer/,
    );
    expect(screen.getByTestId("review-batch-sources").textContent).not.toMatch(/najpierw pilne/);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Wróć do zwykłej kolejności" }));
    });
    expect(api.setFocus).toHaveBeenCalledWith(null);
  });

  it("nad osobą z wybranej rekrutacji: „Twój wybór na dziś”", () => {
    given(
      {
        pending: 1,
        sources,
        focus: { job_id: 11, at: "2026-11-24T08:00:00Z" },
        team_jobs: [
          { job_id: 11, title: "Java Developer", pending: 1, p0: false, group: "p1", via: "assignment" },
        ],
      },
      {
        data: {
          items: [
            {
              process_id: 1,
              stage_id: 1,
              job_id: 11,
              job_title: "Java Developer",
              candidate_id: 5,
              name: "Adam",
              city: null,
              years: null,
              position: null,
              score: 77,
              matched_must: [],
              missing_must: [],
              rate_from_hourly: null,
              rate_currency: null,
              availability_status: null,
              cautions: [],
              budget_hourly: null,
              why: { source: "p1", via: "assignment", chosen: true },
            },
          ],
        },
      },
    );
    render(<ReviewBatchScreen />);
    expect(screen.getByTestId("review-why").textContent).toMatch(/Twój wybór na dziś \(przypisanie\)/);
    fireEvent.click(screen.getByRole("tab", { name: /Rekrutacje/ }));
    expect(screen.getByText("wybrana na dziś")).toBeTruthy();
  });
});
