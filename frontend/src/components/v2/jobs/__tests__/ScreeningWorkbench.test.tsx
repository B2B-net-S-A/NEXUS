/**
 * ScreeningWorkbench — stanowisko screeningu (krok 05, program „flow w języku
 * C2", PR 6/7).
 *
 * Zakres: kolejka (kto się w niej znajduje i co ją opisuje), stany widoku
 * (awaria ≠ pustka), ruch na „Zweryfikowany" bez twardych bramek (stawka
 * opcjonalna od 17.09.2026, ostrzeżenia serwera z „Przenieś mimo to") oraz to,
 * że ruch idzie DOKŁADNIE tym samym `POST /api/pipeline/move` z
 * `expected_rate_*`, którym przenosi karty tablica.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const move = vi.fn();
const getForStage = vi.fn();
const submitScreening = vi.fn();
const listForJob = vi.fn();
const updateCandidate = vi.fn();
const capability = vi.hoisted(() => ({ canWriteCandidate: true }));
vi.mock("@/hooks/useCapability", () => ({
  useCapability: () => capability.canWriteCandidate,
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: vi.fn(), post: vi.fn() },
  pipelineApi: { move: (...a: unknown[]) => move(...a) },
  candidatesApi: { update: (...a: unknown[]) => updateCandidate(...a) },
  screeningApi: {
    getForStage: (...a: unknown[]) => getForStage(...a),
    submit: (...a: unknown[]) => submitScreening(...a),
    // Przepięcie (Pipeline v4): te testy dotyczą osób bez poprzedniej rekrutacji.
    reassignContext: () =>
      Promise.resolve({
        data: { stage_id: 0, available: false, source: null, previous_answers_count: 0 },
      }),
  },
  interviewQuestionsApi: { listForJob: (...a: unknown[]) => listForJob(...a) },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
}));

const showSuccess = vi.fn();
const showError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));

// SLA klienta pochodzi z KARTY KLIENTA — nagłówek kolejki i progi kropek
// liczą się od niego, więc test go podaje zamiast udawać stałą.
vi.mock("@/lib/client-playbooks", () => ({
  useClientPlaybook: () => ({
    data: { sla_business_days: 5, client_name: "PKO BP" },
    isLoading: false,
  }),
}));
// Modal odrzucenia ma własne zapytania i własne reguły maila — zakładka tylko
// go otwiera, więc do jej testów wystarczy stub.
vi.mock("@/components/v2/modals/RejectionV2", () => ({
  RejectionV2: () => <div data-testid="rejection-stub" />,
}));
vi.mock("@/components/v2/modals/CVOriginalPreviewModal", () => ({
  CVOriginalPreviewModal: () => <div data-testid="cv-original-stub" />,
}));

import { ScreeningWorkbench } from "@/components/v2/jobs/ScreeningWorkbench";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";

function item(overrides: Partial<KanbanItem> = {}): KanbanItem {
  return {
    id: 11,
    candidate_id: 111,
    stage: "screening",
    name: "Grzegorz",
    lastname: "Żebrowski",
    days_in_stage: 3,
    ...overrides,
  };
}

function columns(screeningItems: KanbanItem[]): KanbanColumn[] {
  return [
    {
      stage: "screening",
      name: "Screening",
      category: "internal",
      stage_def_id: 3,
      count: screeningItems.length,
      items: screeningItems,
    },
    {
      stage: "verified",
      name: "Zweryfikowany",
      category: "internal",
      stage_def_id: 4,
      count: 0,
      items: [],
    },
  ];
}

function renderWorkbench(
  overrides: Partial<React.ComponentProps<typeof ScreeningWorkbench>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onMoved = vi.fn();
  const onRetry = vi.fn();
  const onTabChange = vi.fn();
  const utils = render(
    <QueryClientProvider client={client}>
      <ScreeningWorkbench
        jobId={7}
        jobBudgetHourly={100}
        columns={columns([item(), item({ id: 12, candidate_id: 112, name: "Marcin", lastname: "Jóźwiak", days_in_stage: 8 })])}
        isLoading={false}
        isError={false}
        error={null}
        isSuccess
        onRetry={onRetry}
        onMoved={onMoved}
        readOnly={false}
        onTabChange={onTabChange}
        {...overrides}
      />
    </QueryClientProvider>,
  );
  return { ...utils, onMoved, onRetry, onTabChange };
}

beforeEach(() => {
  vi.clearAllMocks();
  getForStage.mockResolvedValue({
    data: {
      stage_id: 11,
      candidate_id: 111,
      job_id: 7,
      champion_profile: {
        screening_questions: [
          {
            id: "q1",
            question: "Kafka w produkcji?",
            ideal_answer: "projektował topics",
            deal_breaker: "tylko konsumował",
          },
        ],
      },
      screening_answers: null,
    },
  });
  listForJob.mockResolvedValue({ data: [{ id: 1 }, { id: 2 }, { id: 3 }] });
  move.mockResolvedValue({ data: { id: 99, verification_status: "active" } });
});

describe("ScreeningWorkbench", () => {
  it("kolejka pokazuje osoby z etapu Screening z wiekiem na etapie", async () => {
    renderWorkbench();
    const queue = screen.getByRole("list", { name: "Kolejka screeningu" });
    expect(within(queue).getByText("Grzegorz Żebrowski")).toBeTruthy();
    expect(within(queue).getByText("Marcin Jóźwiak")).toBeTruthy();
    expect(within(queue).getByText("3 d")).toBeTruthy();
    expect(within(queue).getByText("8 d")).toBeTruthy();
  });

  it("pierwsza pozycja kolejki jest wybrana sama — stanowisko nie startuje puste", async () => {
    renderWorkbench();
    expect(
      await screen.findByRole("heading", {
        name: /Screening · Grzegorz Żebrowski/,
      }),
    ).toBeTruthy();
  });

  it("pusta kolejka to pusty stan, a nie awaria", () => {
    renderWorkbench({ columns: columns([]) });
    expect(
      screen.getByText(/Kolejka screeningu jest pusta/),
    ).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("403 na kanbanie renderuje brak uprawnień, nigdy pustej kolejki", () => {
    renderWorkbench({
      columns: [],
      isError: true,
      isSuccess: false,
      error: { response: { status: 403 } },
    });
    expect(screen.getByText("Brak uprawnień")).toBeTruthy();
    expect(screen.queryByText(/Kolejka screeningu jest pusta/)).toBeNull();
  });

  it("awaria kanbana daje przycisk ponowienia, nie pustkę", async () => {
    const { onRetry } = renderWorkbench({
      columns: [],
      isError: true,
      isSuccess: false,
      error: { response: { status: 500 } },
    });
    await userEvent.click(
      screen.getByRole("button", { name: /Spróbuj ponownie/ }),
    );
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("bez stawki ruch NIE jest zablokowany — przesuwa bez `expected_rate_*`", async () => {
    const { onMoved } = renderWorkbench();
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });
    const button = await screen.findByRole("button", {
      name: /Zweryfikowany — zapisz stawkę i przenieś/,
    });
    await waitFor(() => expect(button).not.toBeDisabled());
    expect(button.getAttribute("title")).toBeNull();

    await userEvent.click(button);

    await waitFor(() => expect(move).toHaveBeenCalledOnce());
    const body = move.mock.calls[0][0] as Record<string, unknown>;
    expect(body).toMatchObject({
      candidate_id: 111,
      job_id: 7,
      stage: "verified",
      stage_def_id: 4,
    });
    expect(body).not.toHaveProperty("expected_rate_value");
    expect(body).not.toHaveProperty("expected_rate_unit");
    expect(body).not.toHaveProperty("expected_rate_currency");
    await waitFor(() => expect(onMoved).toHaveBeenCalled());
  });

  it("weto hiring managera NIE blokuje „Zweryfikowany” — to ostrzeżenie serwera, nie bramka", async () => {
    renderWorkbench({
      columns: columns([
        item({
          hm_veto: {
            hiring_manager_contact_id: 5,
            source_job_id: 2,
            rejected_at: "2026-01-01",
            rejection_reason_name: "Brak bankowości",
          },
        }),
      ]),
    });
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });
    await userEvent.type(screen.getByLabelText("Kwota"), "118");
    const button = screen.getByRole("button", {
      name: /Zweryfikowany — zapisz stawkę i przenieś/,
    });
    await waitFor(() => expect(button).not.toBeDisabled());
    expect(button.getAttribute("title") ?? "").not.toContain("Brak bankowości");
  });

  it("409 ELIGIBILITY_WARNING otwiera okno z powodem, a „Przenieś mimo to” powtarza ruch z potwierdzeniem", async () => {
    move
      .mockRejectedValueOnce({
        response: {
          status: 409,
          data: {
            detail: {
              code: "ELIGIBILITY_WARNING",
              reason_code: "blacklist",
              reason: "Kandydat jest na czarnej liście klienta.",
              message: "Kandydat jest na czarnej liście klienta.",
              can_acknowledge: true,
            },
          },
        },
      })
      .mockResolvedValueOnce({ data: { id: 99, verification_status: "active" } });
    const { onMoved } = renderWorkbench();
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });
    const button = screen.getByRole("button", {
      name: /Zweryfikowany — zapisz stawkę i przenieś/,
    });
    await waitFor(() => expect(button).not.toBeDisabled());
    await userEvent.click(button);

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("Ostrzeżenie przed przeniesieniem"),
    ).toBeTruthy();
    expect(
      within(dialog).getByText("Kandydat jest na czarnej liście klienta."),
    ).toBeTruthy();
    expect(move).toHaveBeenCalledOnce();
    expect(move.mock.calls[0][0]).toMatchObject({ acknowledge_eligibility: undefined });
    expect(showError).not.toHaveBeenCalled();

    await userEvent.click(
      within(dialog).getByRole("button", { name: "Przenieś mimo to" }),
    );

    await waitFor(() => expect(move).toHaveBeenCalledTimes(2));
    expect(move.mock.calls[1][0]).toMatchObject({
      candidate_id: 111,
      job_id: 7,
      stage: "verified",
      stage_def_id: 4,
      acknowledge_eligibility: true,
    });
    await waitFor(() => expect(onMoved).toHaveBeenCalled());
  });

  it("karta ponad AKTUALNYM budżetem PLN/h (także zapisana jako `pending`) NIE blokuje ruchu ani odrzucenia", async () => {
    const over = item({
      id: 41,
      candidate_id: 141,
      stage: "verified",
      name: "Anna",
      lastname: "Ponadbudzet",
      verification_status: "pending",
      // 150 PLN/h > budżet 100 PLN/h z `renderWorkbench`.
      expected_rate_value: 150,
      expected_rate_unit: "hourly",
      expected_rate_currency: "PLN",
    });
    const cols = columns([item()]);
    cols[1] = { ...cols[1], count: 1, items: [over] };
    cols.push({
      stage: "rejected",
      name: "Odrzucony",
      category: "terminal",
      terminal_type: "rejected",
      stage_def_id: 9,
      count: 0,
      items: [],
    });
    renderWorkbench({ columns: cols });
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });
    await userEvent.click(
      screen.getAllByRole("button", { name: /Anna Ponadbudzet/ })[0],
    );
    await screen.findByRole("heading", { name: /Screening · Anna Ponadbudzet/ });
    expect(screen.getAllByText("Ponad budżet").length).toBeGreaterThan(0);

    await userEvent.type(screen.getByLabelText("Kwota"), "80");
    const moveButton = screen.getByRole("button", {
      name: /Zweryfikowany — zapisz stawkę i przenieś/,
    });
    await waitFor(() => expect(moveButton).not.toBeDisabled());
    expect(
      screen.getByRole("button", { name: /Odrzuć z powodem/ }),
    ).not.toBeDisabled();
  });

  it("tryb tylko do odczytu chowa zapis screeningu i ruch", async () => {
    renderWorkbench({ readOnly: true });
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });
    expect(
      screen.queryByRole("button", { name: /Zapisz screening/ }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: /Zweryfikowany — zapisz stawkę i przenieś/,
      }),
    ).toBeNull();
  });

  it("wpisana stawka idzie tym samym endpointem co drag&drop", async () => {
    const { onMoved } = renderWorkbench();
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });

    await userEvent.type(screen.getByLabelText("Kwota"), "118");

    const button = screen.getByRole("button", {
      name: /Zweryfikowany — zapisz stawkę i przenieś/,
    });
    await waitFor(() => expect(button).not.toBeDisabled());
    await userEvent.click(button);

    await waitFor(() => expect(move).toHaveBeenCalledOnce());
    expect(move.mock.calls[0][0]).toMatchObject({
      candidate_id: 111,
      job_id: 7,
      stage: "verified",
      stage_def_id: 4,
      expected_rate_value: 118,
      expected_rate_unit: "hourly",
      expected_rate_currency: "PLN",
    });
    await waitFor(() => expect(onMoved).toHaveBeenCalled());
  });

  it("stawka ponad budżet ostrzega „ponad budżet”, ale nie zapowiada akceptacji", async () => {
    renderWorkbench();
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });
    // Budżet godzinowy 100 PLN/h — 130 PLN/h jest ponad.
    await userEvent.type(screen.getByLabelText("Kwota"), "130");
    const message = await screen.findByText(/powyżej budżetu/);
    expect(message.textContent).toContain("ponad budżet");
    expect(message.textContent ?? "").not.toMatch(/akceptac/i);
    expect(screen.queryByText(/Pending/)).toBeNull();
    expect(
      screen.getByRole("button", {
        name: /Zweryfikowany — zapisz stawkę i przenieś/,
      }),
    ).not.toBeDisabled();
  });

  it("linkuje prep-kit, który dotąd nie miał żadnego wejścia w aplikacji", async () => {
    renderWorkbench();
    const link = await screen.findByRole("link", { name: /Prep-kit/ });
    expect(link).toHaveAttribute("href", "/jobs/7/prep/111");
  });

  it("pokazuje liczbę pytań przypiętych do rekrutacji", async () => {
    renderWorkbench();
    await waitFor(() => expect(listForJob).toHaveBeenCalledWith(7));
    expect(await screen.findByText("3")).toBeTruthy();
  });

  it("lewa kolumna ma osobno „Ponad budżet” i „Z ostrzeżeniem” (weto HM)", async () => {
    const veto = item({
      id: 51,
      candidate_id: 151,
      stage: "cv_sent",
      name: "Piotr",
      lastname: "Weto",
      hm_veto: {
        hiring_manager_contact_id: 5,
        source_job_id: 2,
        rejected_at: "2026-01-01",
        rejection_reason_name: "Brak bankowości",
      },
    });
    const cols = columns([item()]);
    cols[1] = { ...cols[1], count: 1, items: [veto] };
    renderWorkbench({ columns: cols });
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });

    expect(screen.getByText("Ponad budżet")).toBeTruthy();
    expect(screen.getByText("Nikt nie jest ponad budżetem.")).toBeTruthy();
    expect(screen.getByText("Z ostrzeżeniem")).toBeTruthy();
    await userEvent.click(
      screen.getAllByRole("button", { name: /Piotr Weto/ })[0],
    );
    expect(
      await screen.findByRole("heading", { name: /Screening · Piotr Weto/ }),
    ).toBeTruthy();
  });

  it("klik w kartę ponad budżetem otwiera JEJ arkusz, zamiast gasić stanowisko", async () => {
    const pending = item({
      id: 41,
      candidate_id: 141,
      stage: "verified",
      name: "Anna",
      lastname: "Ponadbudzet",
      expected_rate_value: 150,
      expected_rate_unit: "hourly",
      expected_rate_currency: "PLN",
    });
    const cols = columns([item()]);
    cols[1] = { ...cols[1], count: 1, items: [pending] };
    renderWorkbench({ columns: cols });
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });

    await userEvent.click(
      screen.getAllByRole("button", { name: /Anna Ponadbudzet/ })[0],
    );
    expect(
      await screen.findByRole("heading", { name: /Screening · Anna Ponadbudzet/ }),
    ).toBeTruthy();
    expect(screen.queryByText(/Wybierz kandydata z kolejki po lewej/)).toBeNull();
  });

  it("po ruchu przepisuje zapisany arkusz na NOWY etap (transition_process go nie kopiuje)", async () => {
    const answers = { answers: [], overall_fit: "fit", answered_at: "2026-09-07" };
    getForStage.mockResolvedValue({
      data: {
        stage_id: 11,
        candidate_id: 111,
        job_id: 7,
        champion_profile: {
          screening_questions: [
            { id: "q1", question: "Kafka?", ideal_answer: "tak", deal_breaker: "" },
          ],
        },
        screening_answers: answers,
      },
    });
    submitScreening.mockResolvedValue({ data: {} });
    renderWorkbench();
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });
    await userEvent.type(screen.getByLabelText("Kwota"), "118");
    const button = screen.getByRole("button", {
      name: /Zweryfikowany — zapisz stawkę i przenieś/,
    });
    await waitFor(() => expect(button).not.toBeDisabled());
    await userEvent.click(button);

    await waitFor(() => expect(move).toHaveBeenCalledOnce());
    // Nowy etap ma id 99 (odpowiedź `move`) — tam trafia kopia arkusza.
    await waitFor(() => expect(submitScreening).toHaveBeenCalledWith(99, answers));
    expect(showSuccess).toHaveBeenCalled();
  });

  // ── Parytet z makietą (fala 3) ─────────────────────────────────────────
  it("nagłówek mówi „Krok · Nazwisko” i liczy dzień wobec SLA klienta", async () => {
    renderWorkbench({ clientId: 3, clientName: "PKO BP" });
    expect(
      await screen.findByRole("heading", {
        name: "Screening · Grzegorz Żebrowski",
      }),
    ).toBeTruthy();
    // Bez SLA byłoby „3 dni na etapie" — z SLA wiadomo, ile zostało.
    expect(screen.getByText(/dzień 3 z 5 SLA/)).toBeTruthy();
    expect(screen.getByText("SLA PKO BP: 5 d")).toBeTruthy();
  });

  it("listwa stanu pokazuje ocenę i policzone odpowiedzi, zanim ktoś przewinie arkusz", async () => {
    renderWorkbench();
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });
    expect(
      await screen.findByText("0 z 1 pytania odpowiedzianych"),
    ).toBeTruthy();
    expect(screen.getByText(/Ogólna ocena dopasowania: —/)).toBeTruthy();
    // Reguła deal-breakera jest wypisana, a nie schowana w wiedzy plemiennej.
    expect(screen.getByText(/zeruje wynik screeningu Championa/)).toBeTruthy();
  });

  it("dok ma zakładki makiety i wypisuje wynik screeningu per pytanie", async () => {
    renderWorkbench();
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });
    expect(screen.getByRole("tab", { name: "Stawka i decyzja" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Notatki" })).toBeTruthy();
    // Pytanie bez odpowiedzi jest w doku oznaczone jako brak, nie pominięte.
    expect(await screen.findByText("Wynik screeningu")).toBeTruthy();
    expect(screen.getByText("brak")).toBeTruthy();
  });

  it("„Odrzuć z powodem” idzie tym samym modalem co decyzja z tablicy", async () => {
    const cols = columns([item()]);
    cols.push({
      stage: "rejected",
      name: "Odrzucony",
      category: "terminal",
      terminal_type: "rejected",
      stage_def_id: 9,
      count: 0,
      items: [],
    });
    renderWorkbench({ columns: cols });
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });
    await userEvent.click(
      screen.getByRole("button", { name: /Odrzuć z powodem/ }),
    );
    expect(await screen.findByTestId("rejection-stub")).toBeTruthy();
    // Odrzucenie NIE idzie ścieżką „Zweryfikowany" — to inny ruch.
    expect(move).not.toHaveBeenCalled();
  });

  it("bez kolumny „Odrzucony” przycisk jest wyłączony z powodem, nie znika", async () => {
    renderWorkbench();
    const button = await screen.findByRole("button", {
      name: /Odrzuć z powodem/,
    });
    expect(button).toBeDisabled();
    expect(button.getAttribute("title")).toContain("nie ma kolumny");
  });

  it("gdy kopia arkusza na nowy etap padnie, ruch zostaje, a komunikat mówi, co zrobić", async () => {
    const answers = { answers: [], overall_fit: "fit", answered_at: "2026-09-07" };
    getForStage.mockResolvedValue({
      data: {
        stage_id: 11,
        candidate_id: 111,
        job_id: 7,
        champion_profile: { screening_questions: [] },
        screening_answers: answers,
      },
    });
    submitScreening.mockRejectedValue(new Error("500"));
    const { onMoved } = renderWorkbench();
    await screen.findByRole("heading", { name: /Screening · Grzegorz/ });
    await userEvent.type(screen.getByLabelText("Kwota"), "118");
    const button = screen.getByRole("button", {
      name: /Zweryfikowany — zapisz stawkę i przenieś/,
    });
    await waitFor(() => expect(button).not.toBeDisabled());
    await userEvent.click(button);

    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(showError.mock.calls[0][0]).toContain("nie udało się przepisać arkusza");
    expect(onMoved).toHaveBeenCalled();
  });
});

describe("ScreeningWorkbench — layout=\"panel\" (rekrutacja v3)", () => {
  it("pokazuje wyłącznie osobę z focusCandidateId — bez kolejki i nagłówka warsztatu", async () => {
    renderWorkbench({ layout: "panel", focusCandidateId: 112 });
    expect(await screen.findByRole("button", { name: /Zapisz screening/ })).toBeTruthy();
    expect(getForStage).toHaveBeenCalledWith(12);
    expect(screen.queryByRole("list", { name: "Kolejka screeningu" })).toBeNull();
    expect(screen.queryByRole("heading", { name: /Screening ·/ })).toBeNull();
    expect(screen.queryByText("Grzegorz Żebrowski")).toBeNull();
    expect(screen.queryByText(/SLA/)).toBeNull();
  });

  it("osoba spoza kolejki dostaje zdanie o etapie, nie pustkę ani błąd", () => {
    renderWorkbench({ layout: "panel", focusCandidateId: 999 });
    expect(
      screen.getByText(/Arkusz screeningu jest dostępny w kolumnie „Nowi”/),
    ).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(getForStage).not.toHaveBeenCalled();
  });

  it("kluczowe akcje zostają: arkusz, stawka, prep-kit, baza pytań, ruch i odrzucenie", async () => {
    const { onTabChange } = renderWorkbench({
      layout: "panel",
      focusCandidateId: 111,
    });
    await screen.findByRole("button", { name: /Zapisz screening/ });
    expect(screen.getByRole("button", { name: /Zapisz screening/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Pokaż CV obok/ })).toBeTruthy();
    expect(
      screen.getByRole("link", { name: /Prep-kit/ }).getAttribute("href"),
    ).toBe("/jobs/7/prep/111");
    expect(screen.getByRole("button", { name: /Odrzuć z powodem/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Wróć później/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Baza pytań/ }));
    expect(onTabChange).toHaveBeenCalledWith("questions");
  });

  it("ruch na „Zweryfikowany” idzie tą samą trasą co w pełnym układzie", async () => {
    const { onMoved } = renderWorkbench({
      layout: "panel",
      focusCandidateId: 112,
    });
    await screen.findByRole("button", { name: /Zapisz screening/ });
    await userEvent.click(
      screen.getByRole("button", { name: /Zweryfikowany — zapisz stawkę/ }),
    );
    await waitFor(() => expect(onMoved).toHaveBeenCalled());
    expect(move.mock.calls[0][0]).toMatchObject({
      candidate_id: 112,
      job_id: 7,
      stage: "verified",
    });
  });
});

describe("ScreeningWorkbench — podpowiedzi z notatek (automaty 21.09.2026)", () => {
  const withSuggestions = (suggestions: unknown) =>
    getForStage.mockImplementation(async () => ({
      data: {
        stage_id: 11,
        candidate_id: 111,
        job_id: 7,
        champion_profile: {
          screening_questions: [
            { id: "q1", question: "Kafka w produkcji?", ideal_answer: "tak", deal_breaker: "nie" },
          ],
        },
        screening_answers: null,
        suggestions,
      },
    }));

  const SUGGESTIONS = {
    rate_redacted: false,
    rate: { value: 175, unit: "hour", currency: "PLN", raw: "175 zł/h", source_note_id: 5, noted_at: "2026-09-12" },
    availability: { raw: "dostępny od razu", notice_period: null, available_from: null, source_note_id: 5, noted_at: "2026-09-12T10:00:00Z" },
  };

  it.each([["full"], ["panel"]] as const)(
    "układ %s: stawka tylko wypełnia pole; dostępność to jawny zapis w PROFILU — notatki (widoczne dla klienta) nietknięte",
    async (layout) => {
      capability.canWriteCandidate = true;
      updateCandidate.mockResolvedValue({ data: {} });
      withSuggestions(SUGGESTIONS);
      renderWorkbench(layout === "panel" ? { layout, focusCandidateId: 111 } : {});
      const chips = await screen.findByTestId("screening-suggestions");
      expect(chips).toHaveTextContent("Z notatek: 175 zł/h · 12.09");
      expect(chips).toHaveTextContent("Z notatek: dostępny od razu · 12.09");

      await userEvent.click(within(chips).getByRole("button", { name: "Użyj stawki z notatek" }));
      expect(screen.getByLabelText("Kwota")).toHaveValue(175);
      expect(updateCandidate).not.toHaveBeenCalled();

      await userEvent.click(
        within(chips).getByRole("button", { name: "Zapisz dostępność z notatek w profilu kandydata" }),
      );
      await waitFor(() => expect(updateCandidate).toHaveBeenCalledOnce());
      expect(updateCandidate.mock.calls[0][0]).toBe(111);
      expect(updateCandidate.mock.calls[0][1]).toEqual({
        availability_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      });
      await waitFor(() =>
        expect(showSuccess).toHaveBeenCalledWith("Zapisano dostępność w profilu kandydata"),
      );
      // Pole widoczne dla klienta w share portalu NIGDY nie dostaje podpowiedzi.
      expect(screen.getByLabelText(/Notatki rekrutera/)).toHaveValue("");
      expect(screen.queryByText(/Niezapisane zmiany/)).not.toBeInTheDocument();
      expect(submitScreening).not.toHaveBeenCalled();
      expect(move).not.toHaveBeenCalled();
    },
  );

  it("dostępność nie do zmapowania: bez „Użyj”, z linkiem „uzupełnij w profilu”", async () => {
    capability.canWriteCandidate = true;
    withSuggestions({
      rate_redacted: false,
      availability: { ...SUGGESTIONS.availability, raw: "za 2 tygodnie od podpisania" },
    });
    renderWorkbench();
    const chips = await screen.findByTestId("screening-suggestions");
    expect(within(chips).queryByRole("button")).not.toBeInTheDocument();
    expect(within(chips).getByRole("link", { name: "uzupełnij w profilu" })).toHaveAttribute(
      "href",
      "/candidates/111",
    );
  });

  it("bez prawa edycji kandydata chip dostępności nie ma „Użyj”", async () => {
    capability.canWriteCandidate = false;
    withSuggestions(SUGGESTIONS);
    renderWorkbench();
    const chips = await screen.findByTestId("screening-suggestions");
    expect(chips).toHaveTextContent("dostępny od razu");
    expect(
      within(chips).queryByRole("button", { name: /Zapisz dostępność/ }),
    ).not.toBeInTheDocument();
    // Stawka zostaje — to pole formularza, nie zapis w profilu.
    expect(within(chips).getByRole("button", { name: "Użyj stawki z notatek" })).toBeInTheDocument();
    capability.canWriteCandidate = true;
  });

  it("nieudany zapis dostępności mówi o błędzie i niczego nie udaje", async () => {
    capability.canWriteCandidate = true;
    updateCandidate.mockRejectedValue({ response: { status: 403, data: { detail: "Brak uprawnień" } } });
    withSuggestions(SUGGESTIONS);
    renderWorkbench();
    const chips = await screen.findByTestId("screening-suggestions");
    await userEvent.click(within(chips).getByRole("button", { name: /Zapisz dostępność/ }));
    await waitFor(() => expect(showError).toHaveBeenCalledWith("Brak uprawnień"));
    expect(showSuccess).not.toHaveBeenCalled();
  });

  it("wypełniona stawka idzie dopiero zwykłym ruchem na „Zweryfikowany”", async () => {
    withSuggestions(SUGGESTIONS);
    renderWorkbench();
    const chips = await screen.findByTestId("screening-suggestions");
    await userEvent.click(within(chips).getByRole("button", { name: "Użyj stawki z notatek" }));
    await userEvent.click(
      screen.getByRole("button", { name: /Zweryfikowany — zapisz stawkę i przenieś/ }),
    );
    await waitFor(() => expect(move).toHaveBeenCalledOnce());
    expect(move.mock.calls[0][0]).toMatchObject({
      expected_rate_value: 175,
      expected_rate_unit: "hourly",
      expected_rate_currency: "PLN",
    });
  });

  it("`rate_redacted`: żadnego chipa stawki — nawet gdyby kwota przyszła", async () => {
    withSuggestions({ ...SUGGESTIONS, rate_redacted: true });
    renderWorkbench();
    const chips = await screen.findByTestId("screening-suggestions");
    expect(chips).not.toHaveTextContent("175");
    expect(within(chips).queryByRole("button", { name: "Użyj stawki z notatek" })).not.toBeInTheDocument();
    expect(chips).toHaveTextContent("dostępny od razu");
  });

  it("stawka w innej walucie jest pokazana, ale bez „Użyj” (formularz liczy w PLN)", async () => {
    withSuggestions({ rate_redacted: false, rate: { ...SUGGESTIONS.rate, currency: "EUR", value: 45 } });
    renderWorkbench();
    const chips = await screen.findByTestId("screening-suggestions");
    expect(chips).toHaveTextContent("45 EUR/h");
    expect(within(chips).queryByRole("button")).not.toBeInTheDocument();
  });

  it("brak podpowiedzi (i starszy backend bez pola) nie rysuje nic; tylko do odczytu chowa „Użyj”", async () => {
    const first = renderWorkbench();
    await screen.findByRole("button", { name: /Zapisz screening/ });
    expect(screen.queryByTestId("screening-suggestions")).not.toBeInTheDocument();
    first.unmount();

    withSuggestions(SUGGESTIONS);
    renderWorkbench({ readOnly: true });
    const chips = await screen.findByTestId("screening-suggestions");
    expect(within(chips).queryByRole("button")).not.toBeInTheDocument();
  });
});
