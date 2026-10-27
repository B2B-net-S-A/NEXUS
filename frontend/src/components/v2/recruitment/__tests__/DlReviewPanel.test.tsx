import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Układ przeglądu zależy od zmierzonej szerokości, której jsdom nie liczy:
// 0 = jedna kolumna (wszystkie testy poza blokiem „układ D4”).
const layout = vi.hoisted(() => ({ width: 0 }));
vi.mock("@/lib/use-element-width", () => ({
  useElementWidth: () => layout.width,
}));

const get = vi.fn();
const post = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();
const showActionToast = vi.fn();
const renderDocxSafely = vi.fn();
const loadJobRejectionReasons = vi.fn();
const fetchStageCvFile = vi.fn();
const championGet = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
  // Lista osób do „@” (`useMentionableUsers`) czyta nazwany eksport.
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
  pipelineApi: {
    move: (data: unknown) => post("/api/pipeline/move", data),
  },
  candidatesApi: {
    get: (id: number) => get(`/api/candidates/${id}`),
  },
  // Słowa lupy „Szukaj w CV” dla wymagań (`requirement_find_words`).
  championApi: {
    get: (...a: unknown[]) => championGet(...a),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError, showActionToast }),
}));
vi.mock("@/lib/docx-preview-safe", () => ({
  renderDocxSafely: (...a: unknown[]) => renderDocxSafely(...a),
}));
vi.mock("@/lib/cv-docx-preview", () => ({ alignB2bLetterheadPreview: () => undefined }));
vi.mock("@/lib/stage-cv-file", () => ({
  fetchStageCvFile: (...a: unknown[]) => fetchStageCvFile(...a),
}));
vi.mock("@/lib/rejection-reasons", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/rejection-reasons")>()),
  loadJobRejectionReasons: (...a: unknown[]) => loadJobRejectionReasons(...a),
}));
const consentProps = vi.fn();
vi.mock("@/components/v2/cv-generator/ConsentAttachButton", () => ({
  ConsentAttachButton: (props: Record<string, unknown>) => {
    consentProps(props);
    return <button type="button">Wgraj zrzut zgody</button>;
  },
}));
vi.mock("@/components/v2/recruitment/CvQcDialog", () => ({
  CvQcDialog: ({ stageId, open }: { stageId: number | null; open: boolean }) =>
    open ? <div role="dialog" aria-label="QC CV">QC etapu {stageId}</div> : null,
}));

import { DlReviewPanel, dlReviewMode } from "@/components/v2/recruitment/DlReviewPanel";
import { formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";
import type { BoardTaskRow } from "@/lib/api/boardTasks";
import type { ScreeningFormState } from "@/lib/api/screeningForm";
import { formatDate } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";
import { permissionSnapshot } from "@/__tests__/fixtures/permission-snapshot";

const since = new Date(Date.now() - 2 * 86_400_000).toISOString();

function task(over: Partial<BoardTaskRow> = {}): BoardTaskRow {
  return {
    kind: "dl_review",
    stage_id: 11,
    candidate_id: 21,
    candidate_name: "Anna Nowak",
    job_id: 31,
    job_title: "Java Developer",
    client_id: 5,
    client_name: "PKO BP",
    since,
    process_state_version: 4,
    target_stage_def_id: 305,
    assignee_id: null,
    assignee_name: null,
    rejected_stage_def_id: 399,
    verified_by_id: 7,
    verified_by_name: "Marta Rekruterka",
    verified_at: since,
    expected_rate_value: 140,
    expected_rate_unit: "hourly",
    expected_rate_currency: "PLN",
    screening_stage_id: 9,
    qc_status: "passed",
    qc_blocking_failed: 0,
    ...over,
  };
}

// 09.10.2026: przegląd czyta stan formularza screeningu pary (jeden blok
// „Screening”), nie kartę rekomendacji i osobno arkusz etapu.
const FORM: ScreeningFormState = formState({
  candidate_id: 21,
  job_id: 31,
  stage_id: 11,
  board_column: "cv_qc",
  sheet: {
    answers: [],
    overall_fit: "fit",
    notes: "",
    answered_at: since,
  },
  questions: [
    {
      number: 1,
      question: "Doświadczenie z Kafką?",
      answer: "3 lata, produkcyjnie",
      source: "note",
      question_id: "q1",
      deal_breaker: null,
      deal_breaker_hit: false,
    },
  ],
  card: {
    fields: {
      availability: { raw: "od zaraz", source: "manual", by_name: "Marta Rekruterka", at: since },
    },
    previous: {},
    suggestions: {},
    completeness: { status: "partial", filled: 2, total: 10, missing: ["work_mode"] },
    labels: { availability: "Dostępność", work_mode: "Tryb pracy", recommendation: "Notatka" },
    editable_fields: ["availability", "work_mode", "rate", "recommendation"],
  },
  rate: { amount: 140, unit: "hourly", currency: "PLN", source: "card", at: since },
  rate_hints: { card: { amount: 140, unit: "hourly", currency: "PLN" }, rate_from: null },
});

const CONTEXT = {
  candidate_id: 21,
  candidate_name: "Anna Nowak",
  job_id: 31,
  stage_id: 11,
  client_id: 5,
  client_name: "PKO BP",
  category_name: "Rozwój oprogramowania",
  qc_status: "passed",
  qc_blocking_failed: 0,
  can_see_amounts: true,
  can_see_client_rates: true,
  candidate_rate: { amount: 140, unit: "hourly", currency: "PLN", hourly_pln: 140 },
  rate_from_hourly: 120,
  budget: { min_hourly: 120, max_hourly: 160 },
  client_rate_hint: null as Record<string, unknown> | null,
  client_rates: {
    consultants: 9,
    client_margin_median_hourly: 40,
    category_name: "Rozwój oprogramowania",
    category_count: 3,
    category_cost_min: 120,
    category_cost_max: 150,
    category_revenue_min: 160,
    category_revenue_max: 195,
    category_margin_median_hourly: 42,
  },
  requirements: [
    { key: "must:0", label: "Java", level: "critical", status: "met", sources: ["CV"], candidate_value: "…Java 17 w banku…" },
    { key: "must:1", label: "Oracle", level: "must", status: "missing", sources: [], candidate_value: null },
    { key: "must:2", label: "Angular", level: "must", status: "unknown", sources: ["profil", "CV"], candidate_value: null, last_used_year: 2021 },
    { key: "nice:0", label: "komunikatywność", level: "nice", status: "unknown", sources: [], candidate_value: null },
  ],
  requirements_met: 1,
  requirements_total: 2,
  assessment: {
    overall_fit: "fit",
    overall_fit_label: "Pasuje",
    fields: { recommendation: "Mocny backend, bankowość." },
    answers: [{ question: "Kafka?", question_id: "q1", answer: "3 lata", deal_breaker_hit: false }],
  },
  risks: [{ code: "sent_to_client_before", label: "Już u tego klienta: „Java” (2026-05-01, Odrzucony)", severity: "medium" }],
  start: "od zaraz",
  fix_rounds: 0,
  previous_sends: [],
  job_sends: [],
  last_contract: null,
  fix_options: [
    { key: "question:q1", label: "Pytanie 1: Kafka?", group: "answers" },
    { key: "field:availability", label: "Dostępność", group: "terms" },
    { key: "candidate_rate", label: "Stawka kandydata", group: "rate" },
    { key: "cv", label: "CV firmowe", group: "cv" },
  ],
};

function mockApi({
  cvs = [{ id: 77, status: "ready", filename: "cv.docx", origin: "auto", needs_review: true }],
  availability = { status: "open_to_offers", available_from: null, notice_period: 1, notice_period_unit: "months" },
  context = CONTEXT,
  form = FORM,
  match = null,
}: {
  cvs?: Array<Record<string, unknown>>;
  availability?: Record<string, unknown> | null;
  context?: Record<string, unknown> | null;
  form?: ScreeningFormState;
  match?: Record<string, unknown> | null;
} = {}) {
  get.mockImplementation((url: string) => {
    if (url === "/api/dl-match/candidates/21" && match) return Promise.resolve({ data: match });
    if (url === "/api/dl-review/context") {
      return context ? Promise.resolve({ data: context }) : Promise.reject(new Error("boom"));
    }
    if (url === "/api/candidates/21/quick-view") {
      return Promise.resolve({
        data: {
          candidate: { city: "Kraków", expected_rate_hourly: null },
          current_position: { title: "Senior Java Developer" },
          availability,
        },
      });
    }
    if (url === "/api/users/mentionable") {
      return Promise.resolve({
        data: [{ id: 5, name: "Jan Rekruter", email: "jan.rekruter@example.com", role: "recruiter" }],
      });
    }
    if (url === "/api/cv-generator/generated") return Promise.resolve({ data: cvs });
    if (url === "/api/screening-form") return Promise.resolve({ data: form });
    if (url === "/api/cv-generator/generated/77/docx") return Promise.resolve({ data: new Blob(["docx"]) });
    // Pytanie o dni w biurze przy „Nie akceptuje trybu pracy” (14.10.2026).
    if (url === "/api/jobs/31") {
      return Promise.resolve({ data: { remote_policy: "hybrid", onsite_days_per_week: 2 } });
    }
    if (url === "/api/candidates/21") {
      return Promise.resolve({
        data: { preferences: { remote_modes: ["remote", "hybrid"] }, max_onsite_days_per_week: 3 },
      });
    }
    return Promise.reject(new Error(`unexpected ${url}`));
  });
}

function renderPanel(row: BoardTaskRow = task(), onOpenChange = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={qc}>
      <DlReviewPanel task={row} open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  );
  return { onOpenChange, qc, view };
}

describe("DlReviewPanel — przegląd DL przed wysłaniem CV do klienta", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: { id: 1, role: "delivery_lead" } } as never);
    renderDocxSafely.mockResolvedValue(undefined);
    post.mockResolvedValue({ data: {} });
    loadJobRejectionReasons.mockResolvedValue([
      { id: "5", label: "Za wysoka stawka", applies_to: ["rejected"], disqualifies_person: false },
      { id: "6", label: "Kandydat zrezygnował", applies_to: ["withdrawn"], disqualifies_person: false },
    ]);
  });

  it("pokazuje kto zweryfikował, stawkę, dostępność, podgląd CV i jeden blok „Screening”", async () => {
    mockApi();
    renderPanel();
    expect(screen.getByText(/Zweryfikował\(a\) Marta Rekruterka/)).toBeTruthy();
    expect(await screen.findByText("Otwarty na oferty · wypowiedzenie 1 mies.")).toBeTruthy();
    expect(screen.getByText("Kraków")).toBeTruthy();
    // Warunki, odpowiedzi na pytania Championa (także z notatki) i ocena — razem.
    const screening = screen.getByRole("region", { name: "Screening" });
    const view = await within(screening).findByTestId("screening-form-readonly");
    expect(within(view).getByTestId("screening-form-readonly-terms")).toHaveTextContent("140 zł/h");
    expect(within(view).getByTestId("screening-form-readonly-terms")).toHaveTextContent("od zaraz");
    expect(within(view).getByText("3 lata, produkcyjnie")).toBeTruthy();
    expect(within(view).getByText("odpowiedź z notatki")).toBeTruthy();
    expect(within(view).getByTestId("screening-summary-status")).toHaveTextContent("Pasuje");
    // 09.10.2026: te same dane nie stoją już w trzech blokach pod trzema nazwami.
    expect(screen.queryByRole("region", { name: "Karta rekomendacji" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Ocena rekrutera" })).toBeNull();
    expect(screen.queryByText("Arkusz screeningu Championa")).toBeNull();
    expect(screen.queryByText(/[Kk]art[aęy] rekomendacji/)).toBeNull();
    // Przegląd nie mówi DL-owi o cudzym formularzu „nie masz uprawnień”; edycja to link.
    expect(within(view).getByRole("link", { name: /Edytuj w screeningu/ })).toHaveAttribute(
      "href",
      "/jobs/31?candidate=21&panel=screening",
    );
    await waitFor(() => expect(renderDocxSafely).toHaveBeenCalledTimes(1));
    expect(get).toHaveBeenCalledWith("/api/cv-generator/generated", {
      params: { candidate_id: 21, job_id: 31, limit: 10 },
    });
    expect(screen.getByText("Do przeglądu")).toBeTruthy();
    // Tekst w starym formacie pobiera się dopiero po rozwinięciu.
    expect(get.mock.calls.some(([url]) => url === "/api/recommendation-cards")).toBe(false);
  });

  it("naruszone „Odpada, gdy…”: ostrzeżenie w stopce i warunek pod pytaniem", async () => {
    mockApi({
      form: {
        ...FORM,
        sheet: {
          answers: [
            { question_id: "q1", response: "Pół roku", deal_breaker_hit: true, question_text: "Doświadczenie z Kafką?" },
          ],
          overall_fit: "uncertain",
          notes: "",
        },
        questions: [
          {
            number: 1,
            question: "Doświadczenie z Kafką?",
            answer: "Pół roku",
            // Trafienie żyje w arkuszu screeningu — odpowiedź też z arkusza.
            source: "sheet",
            question_id: "q1",
            deal_breaker: "mniej niż rok z Kafką",
            deal_breaker_hit: true,
          },
        ],
      },
    });
    renderPanel();
    expect(await screen.findByTestId("dl-review-deal-breaker")).toHaveTextContent(
      "Odpowiedź na pytanie 1 narusza „Odpada, gdy…”.",
    );
    expect(screen.getByText("Odpada, gdy: mniej niż rok z Kafką")).toBeTruthy();
    // 0424: trafienie zaznacza rekruter w formularzu screeningu — przegląd
    // pokazuje je tylko do odczytu.
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByTestId("screening-summary-deal-breaker")).toHaveTextContent("narusza „Odpada, gdy…”");
  });

  // Test na produkcji 03.10.2026: screening niżej mówił „2 tygodnie”, a kafel
  // „Dostępność” nad nim „—”, bo czytał wyłącznie profil.
  it("dostępność bierze ze screeningu, gdy profil jej nie zna", async () => {
    mockApi({ availability: null });
    renderPanel();
    const hint = await screen.findByText("ze screeningu");
    expect(hint.parentElement).toHaveTextContent("Dostępność");
    expect(hint.parentElement).toHaveTextContent("od zaraz");
  });

  it("„Wyślij do klienta” wymaga stawki i wysyła ruch na „CV wysłane” ze stawką i wersją", async () => {
    mockApi();
    const { onOpenChange } = renderPanel();
    const send = screen.getByRole("button", { name: /Akceptuj/ });
    expect(send).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Stawka do klienta"), "180");
    // D9 (08.10.2026, odwraca decyzję z 23.09): marża na żywo — 180 − 140.
    const margin = await screen.findByTestId("dl-review-margin");
    expect(margin).toHaveTextContent("Marża: 40 zł/h · 6720 zł/mies. (22,2%)");
    expect(send).toHaveAccessibleName(/Akceptuj — wysyłam za 180 zł\/h/);
    expect(send).toBeEnabled();
    await userEvent.click(send);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/move", {
        candidate_id: 21,
        job_id: 31,
        expected_state_version: 4,
        stage_def_id: 305,
        client_rate_value: 180,
        client_rate_unit: "hourly",
        client_rate_currency: "PLN",
      }),
    );
    expect(showSuccess).toHaveBeenCalledWith("Anna Nowak — CV wysłane do klienta.");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("Match (22.10.2026): połączona rekrutacja jest zaznaczona i idzie razem z tą, ze stawką z decyzji", async () => {
    mockApi({
      match: {
        candidate_id: 21,
        from_job_id: 31,
        status: "ok",
        jobs: [
          { job_id: 41, title: "Java B", client_name: "PKO BP", client_reference: "ZOB-41", score: null,
            matching_must: [], gap_must: [], linked: true, destination: "cv_sent", sendable: true },
          { job_id: 42, title: "Java C", client_name: "PKO BP", client_reference: "ZOB-42", score: 81,
            matching_must: [], gap_must: ["Kafka"], linked: false, destination: "cv_sent", sendable: true },
        ],
        already_in: [],
      },
    });
    post.mockImplementation((url: string) =>
      url === "/api/dl-match/send"
        ? Promise.resolve({
            data: {
              candidate_id: 21,
              from_job_id: 31,
              results: [{ job_id: 41, title: "ZOB-41 Java B", status: "sent", destination: "cv_sent",
                qc: "passed", reason: null, cv_carried: true }],
            },
          })
        : Promise.resolve({ data: {} }),
    );
    renderPanel();
    const section = await screen.findByTestId("dl-match-section");
    expect(await within(section).findByRole("checkbox", { name: /ZOB-41/ })).toBeChecked();
    expect(within(section).getByRole("checkbox", { name: /ZOB-42/ })).not.toBeChecked();
    expect(within(section).getByText(/brak w CV: Kafka/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Stawka do klienta"), "180");
    const send = screen.getByRole("button", { name: "Akceptuj — wysyłam do 2 rekrutacji" });
    await userEvent.click(send);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/dl-match/send", {
        candidate_id: 21,
        from_job_id: 31,
        targets: [{ job_id: 41, client_rate_value: 180, client_rate_unit: "hourly", client_rate_currency: "PLN" }],
      }),
    );
    expect(post.mock.calls[0][0]).toBe("/api/pipeline/move");
    expect(showSuccess).toHaveBeenCalledWith("Match: wysłano też do 1 rekrutacji (do klienta: 1)");
  });

  it("Nordea (13.10.2026): akceptacja do kolejki Cpro — stawka do Cpro, ruch na etap Cpro, uwaga dla osoby od Cpro", async () => {
    mockApi();
    const { onOpenChange } = renderPanel(task({ cpro: true, target_stage_def_id: 404 }));
    const accept = screen.getByRole("button", { name: /Akceptuj — wpisz stawkę do Cpro/ });
    expect(accept).toBeDisabled();
    expect(screen.getByText(/Po akceptacji osoba trafi do kolejki Cpro/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Uwagi dla rekrutera i osoby od Cpro/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Stawka do Cpro"), "165");
    expect(accept).toHaveAccessibleName(/Akceptuj — do Cpro za 165 zł\/h/);
    await userEvent.type(
      screen.getByLabelText(/Uwagi dla rekrutera i osoby od Cpro/),
      "Dostępna od listopada",
    );
    await userEvent.click(accept);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/move", {
        candidate_id: 21,
        job_id: 31,
        expected_state_version: 4,
        stage_def_id: 404,
        client_rate_value: 165,
        client_rate_unit: "hourly",
        client_rate_currency: "PLN",
        recruiter_remark: "Dostępna od listopada",
      }),
    );
    expect(showSuccess).toHaveBeenCalledWith(
      "Anna Nowak — zaakceptowane, osoba czeka w kolejce Cpro.",
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  // 22.10.2026: „@” w uwadze oznacza rekrutera — przy akceptacji do Cpro
  // dzwonek ruchu idzie do osoby od Cpro, więc rekruter dowiaduje się z wzmianki.
  it("Nordea: „@” w uwadze wstawia adres rekrutera do recruiter_remark", async () => {
    mockApi();
    renderPanel(task({ cpro: true, target_stage_def_id: 404 }));
    expect(screen.getByText(/„@” oznacza osobę/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Stawka do Cpro"), "165");
    const remark = screen.getByLabelText(/Uwagi dla rekrutera i osoby od Cpro/);
    await userEvent.type(remark, "@Jan");
    await userEvent.click(await screen.findByRole("option", { name: /Jan Rekruter/ }));
    // Kursor za wzmianką stawia `requestAnimationFrame` — pisz po klatce.
    await new Promise((resolve) => requestAnimationFrame(resolve));
    await userEvent.keyboard("zadzwoń do kandydata");
    await userEvent.click(screen.getByRole("button", { name: /Akceptuj — do Cpro za 165 zł\/h/ }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({
          recruiter_remark: "@jan.rekruter@example.com zadzwoń do kandydata",
        }),
      ),
    );
  });

  it("Nordea bez etapu Cpro w szablonie: akceptacja zablokowana z wyjaśnieniem", () => {
    mockApi();
    renderPanel(task({ cpro: true, target_stage_def_id: null }));
    expect(screen.getByText(/nie ma etapu „Wysłać do Cpro”/)).toBeInTheDocument();
  });

  // 13.10.2026: przegląd „po kolei” — po decyzji okno nie zamyka się samo,
  // wołający pokazuje następną osobę.
  it("po kolei: decyzja woła onDecided zamiast zamykać; nagłówek ma licznik, „Pomiń” i „Zakończ kolejkę”", async () => {
    mockApi();
    const onOpenChange = vi.fn();
    const onDecided = vi.fn();
    const onSkip = vi.fn();
    const onFinish = vi.fn();
    const row = task();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <DlReviewPanel
          task={row}
          open
          onOpenChange={onOpenChange}
          onDecided={onDecided}
          sequence={{ position: 2, total: 5, onSkip, onFinish }}
        />
      </QueryClientProvider>,
    );
    const strip = screen.getByTestId("dl-review-sequence");
    expect(strip).toHaveTextContent("2 z 5");
    await userEvent.click(within(strip).getByRole("button", { name: "Pomiń" }));
    expect(onSkip).toHaveBeenCalledTimes(1);
    await userEvent.click(within(strip).getByRole("button", { name: "Zakończ kolejkę" }));
    expect(onFinish).toHaveBeenCalledTimes(1);

    await userEvent.type(screen.getByLabelText("Stawka do klienta"), "180");
    await userEvent.click(screen.getByRole("button", { name: /Akceptuj/ }));
    await waitFor(() => expect(onDecided).toHaveBeenCalledWith("send", row));
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("po kolei: przy ostatniej osobie nie ma „Pomiń”", () => {
    mockApi();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <DlReviewPanel
          task={task()}
          open
          onOpenChange={vi.fn()}
          sequence={{ position: 3, total: 3, onSkip: vi.fn(), onFinish: vi.fn() }}
        />
      </QueryClientProvider>,
    );
    const strip = screen.getByTestId("dl-review-sequence");
    expect(strip).toHaveTextContent("3 z 3");
    expect(within(strip).queryByRole("button", { name: "Pomiń" })).toBeNull();
    expect(within(strip).getByRole("button", { name: "Zakończ kolejkę" })).toBeTruthy();
  });

  it("„Odrzuć (DL)” wymaga powodu i zapisuje ended_by delivery_lead", async () => {
    mockApi();
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: /^Odrzuć…/ }));
    const group = screen.getByRole("group", { name: "Odrzucenie przez DL" });
    const confirm = within(group).getByRole("button", { name: /Potwierdź odrzucenie/ });
    const select = await within(group).findByRole("combobox");
    expect(within(select).queryByRole("option", { name: "Kandydat zrezygnował" })).toBeNull();
    expect(confirm).toBeDisabled();
    await userEvent.selectOptions(select, "5");
    await userEvent.type(screen.getByLabelText(/Uwagi dla rekrutera/), "Za drogo dla klienta");
    await userEvent.click(confirm);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/move", {
        candidate_id: 21,
        job_id: 31,
        expected_state_version: 4,
        stage_def_id: 399,
        ended_by: "delivery_lead",
        rejection_reason_id: 5,
        rejection_reason: undefined,
        send_rejection_email: false,
        recruiter_remark: "Za drogo dla klienta",
      }),
    );
    expect(showSuccess).toHaveBeenCalledWith("Anna Nowak — odrzucony przez DL.");
    expect(showActionToast).not.toHaveBeenCalled();
  });

  it("odrzucenie z mailem do kandydata: treść „przed klientem”, dopisek i „Cofnij wysyłkę” (17.10.2026)", async () => {
    mockApi();
    post.mockImplementation((url: string) => {
      if (url === "/api/rejection-emails/preview") {
        return Promise.resolve({
          data: {
            subject: "Informacja zwrotna — Senior Java Developer",
            body: "Cześć Anna,\n\nw tym procesie nie przedstawimy Twojej kandydatury.",
            closing: "Życzymy powodzenia!",
            other_processes_text:
              "To dotyczy tylko tej rekrutacji — nadal bierzesz udział w naszym pozostałym procesie:\n• Data Engineer",
            text_kind: "before_client",
            people: [
              {
                candidate_id: 21,
                to_email: "anna@example.com",
                skip_reason: null,
                text_kind: "before_client",
                other_processes: [
                  { job_id: 40, title: "Data Engineer", mail_title: "Data Engineer", column: "verified" },
                ],
              },
            ],
          },
        });
      }
      return Promise.resolve({ data: { scheduled_rejection_email_id: 77 } });
    });
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: /^Odrzuć…/ }));
    const group = screen.getByRole("group", { name: "Odrzucenie przez DL" });
    await userEvent.selectOptions(await within(group).findByRole("combobox"), "5");
    await userEvent.click(
      within(group).getByRole("checkbox", { name: /Wyślij e-mail do kandydata/ }),
    );
    expect(await within(group).findByText("Treść: przed klientem")).toBeTruthy();
    expect(within(group).getByTestId("rejection-email-other-processes")).toBeTruthy();
    await userEvent.click(within(group).getByRole("button", { name: /Potwierdź odrzucenie/ }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({
          ended_by: "delivery_lead",
          send_rejection_email: true,
          rejection_email_subject: undefined,
          rejection_email_other_processes: undefined,
        }),
      ),
    );
    expect(showActionToast).toHaveBeenCalledWith(
      "Email odrzucenia zostanie wysłany za 15 minut.",
      expect.objectContaining({ actionLabel: "Cofnij wysyłkę" }),
    );
  });

  it("„Nie akceptuje trybu pracy” pyta o dni w biurze i wysyła je z ruchem (14.10.2026)", async () => {
    mockApi();
    loadJobRejectionReasons.mockResolvedValue([
      { id: "5", label: "Za wysoka stawka", applies_to: ["rejected"], disqualifies_person: false },
      {
        id: "9",
        name: "work_mode_mismatch",
        label: "Nie akceptuje trybu pracy (biuro / hybryda)",
        applies_to: ["rejected"],
        disqualifies_person: false,
      },
    ]);
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: /^Odrzuć…/ }));
    const group = screen.getByRole("group", { name: "Odrzucenie przez DL" });
    const select = await within(group).findByRole("combobox");
    expect(within(group).queryByTestId("rejection-work-mode")).toBeNull();
    await userEvent.selectOptions(select, "9");
    expect(await within(group).findByText("Ta rekrutacja: hybrydowo · 2 dni w biurze w tygodniu.")).toBeTruthy();
    expect(within(group).queryByText("Do 2 dni")).toBeNull();
    expect(
      await within(group).findByText(
        "Teraz na profilu: Hybrydowo lub zdalnie · do 3 dni w biurze w tygodniu",
      ),
    ).toBeTruthy();
    await userEvent.click(within(group).getByText("Do 1 dnia"));
    await userEvent.click(within(group).getByRole("button", { name: /Potwierdź odrzucenie/ }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({
          ended_by: "delivery_lead",
          rejection_reason_id: 9,
          work_mode_max_onsite_days: 1,
          work_mode_save_to_profile: true,
        }),
      ),
    );
  });

  it("„Wróć do poprawy…” otwiera okno z polami; wysyła listę pól i uwagę", async () => {
    mockApi();
    renderPanel(task({ return_stage_def_id: 302 }));
    await userEvent.click(screen.getByRole("button", { name: /Wróć do poprawy…/ }));
    const dialog = await screen.findByRole("dialog", { name: /Wróć do poprawy — Anna Nowak/ });
    const confirm = within(dialog).getByRole("button", { name: /^Wróć do poprawy/ });
    // Bez pola i bez uwagi nie ma czego wysłać.
    expect(confirm).toBeDisabled();
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "CV firmowe" }));
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Pytanie 1: Kafka?" }));
    await userEvent.type(within(dialog).getByLabelText("Uwaga dla rekrutera"), "  Dopisz Spring Boot  ");
    expect(confirm).toHaveAccessibleName(/Wróć do poprawy \(2\)/);
    await userEvent.click(confirm);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/move", {
        candidate_id: 21,
        job_id: 31,
        expected_state_version: 4,
        stage_def_id: 302,
        // Kolejność formularza, nie kolejność klikania.
        fix_fields: ["question:q1", "cv"],
        recruiter_remark: "Dopisz Spring Boot",
      }),
    );
    expect(showSuccess).toHaveBeenCalledWith("Anna Nowak — wraca do rekrutera do poprawy.");
  });

  it("„Wróć do poprawy…” z samą uwagą (bez pól) też działa", async () => {
    mockApi();
    renderPanel(task({ return_stage_def_id: 302 }));
    await userEvent.click(screen.getByRole("button", { name: /Wróć do poprawy…/ }));
    const dialog = await screen.findByRole("dialog", { name: /Wróć do poprawy — Anna Nowak/ });
    await userEvent.type(within(dialog).getByLabelText("Uwaga dla rekrutera"), "Popraw CV");
    await userEvent.click(within(dialog).getByRole("button", { name: /^Wróć do poprawy/ }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/move", {
        candidate_id: 21,
        job_id: 31,
        expected_state_version: 4,
        stage_def_id: 302,
        recruiter_remark: "Popraw CV",
      }),
    );
  });

  it("podpowiedź stawki do klienta z historii wpisuje się ze źródłem; waluta to wybór", async () => {
    mockApi({
      context: {
        ...CONTEXT,
        client_rate_hint: {
          amount: 185,
          unit: "hourly",
          currency: "PLN",
          hourly_pln: 185,
          at: "2026-06-01T10:00:00Z",
          source: "same_client",
          job_id: 9,
          job_title: "Java — kredyty",
        },
      },
    });
    renderPanel();
    await waitFor(() => expect(screen.getByLabelText("Stawka do klienta")).toHaveValue("185"));
    expect(screen.getByTestId("dl-review-rate-source")).toHaveTextContent(
      "ostatnia wysyłka tej osoby do tego klienta — „Java — kredyty”",
    );
    // 185 − 140 = 45 ≥ mediana 40 — bez ostrzeżenia.
    expect(screen.getByTestId("dl-review-margin")).toHaveTextContent("Marża: 45 zł/h");
    expect(screen.queryByText(/Poniżej mediany marży/)).toBeNull();
    await userEvent.selectOptions(screen.getByLabelText("Waluta stawki do klienta"), "EUR");
    expect(screen.getByTestId("dl-review-margin")).toHaveTextContent("stawki są w różnych walutach");
    await userEvent.click(screen.getByRole("button", { name: /Akceptuj/ }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({ client_rate_value: 185, client_rate_currency: "EUR" }),
      ),
    );
  });

  it("marża poniżej mediany klienta — ostrzeżenie; wymagania z dowodem i ryzyka po lewej", async () => {
    mockApi();
    renderPanel();
    await userEvent.type(screen.getByLabelText("Stawka do klienta"), "165");
    expect(await screen.findByText(/Poniżej mediany marży u tego klienta \(40 zł\/h\)/)).toBeTruthy();
    const requirements = screen.getByTestId("dl-review-requirements");
    expect(within(requirements).getByText("…Java 17 w banku…")).toBeTruthy();
    expect(within(requirements).getByText("1/2 krytycznych i musi mieć")).toBeTruthy();
    expect(within(requirements).getByText("do oceny")).toBeTruthy();
    // Technologia sprzed ponad 3 lat (27.10.2026): „?” z rokiem, nie „do oceny”, lupa zostaje.
    expect(within(requirements).getByText("angular · 2021 — zapytaj, czy używa dziś")).toBeTruthy();
    expect(within(requirements).getByTitle("Ostatnio używane w 2021 — zapytaj, czy używa dziś.")).toBeTruthy();
    expect(within(requirements).getByRole("button", { name: "Szukaj w CV: Angular" })).toBeTruthy();
    expect(within(requirements).getByText(/Już u tego klienta/)).toBeTruthy();
    expect(within(requirements).getByText("Pasuje")).toBeTruthy();
  });

  it("awaria kontekstu nie blokuje decyzji — komunikat z „Ponów”", async () => {
    mockApi({ context: null });
    renderPanel();
    expect(await screen.findByText(/Nie udało się wczytać porównania z wymaganiami/)).toBeTruthy();
    await userEvent.type(screen.getByLabelText("Stawka do klienta"), "180");
    expect(screen.getByRole("button", { name: /Akceptuj/ })).toBeEnabled();
  });

  it("bez etapu powrotu w wierszu nie ma „Wróć do poprawy”", async () => {
    mockApi();
    renderPanel();
    expect(screen.queryByRole("button", { name: /Wróć do poprawy/ })).toBeNull();
  });

  it("uwaga dla rekrutera jedzie także z wysyłką — obok stawki, nie w niej", async () => {
    mockApi();
    renderPanel();
    await userEvent.type(screen.getByLabelText("Stawka do klienta"), "175");
    await userEvent.type(screen.getByLabelText(/Uwagi dla rekrutera/), "Klient odpowie do piątku");
    await userEvent.click(screen.getByRole("button", { name: /Akceptuj/ }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({
          stage_def_id: 305,
          client_rate_value: 175,
          recruiter_remark: "Klient odpowie do piątku",
        }),
      ),
    );
  });

  it("konflikt wersji → komunikat i zamknięcie, bez ponowienia", async () => {
    mockApi();
    post.mockRejectedValue({
      response: { status: 409, data: { detail: { code: "PIPELINE_VERSION_CONFLICT" } } },
    });
    const { onOpenChange } = renderPanel();
    await userEvent.type(screen.getByLabelText("Stawka do klienta"), "180");
    await userEvent.click(screen.getByRole("button", { name: /Akceptuj/ }));
    await waitFor(() => expect(showError).toHaveBeenCalledWith(expect.stringMatching(/przesunięty przez kogoś innego/)));
    expect(post).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("odmowa serwera (403) pokazuje jego komunikat z nazwą brakującego uprawnienia", async () => {
    mockApi();
    const message =
      "Brakuje Ci uprawnienia „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta”. Poproś administratora o dostęp.";
    post.mockRejectedValue({
      response: {
        status: 403,
        data: {
          detail: {
            code: "permission_denied",
            permission: "recruitment_manage",
            label: "Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta",
            message,
          },
        },
      },
    });
    renderPanel();
    await userEvent.type(screen.getByLabelText("Stawka do klienta"), "180");
    await userEvent.click(screen.getByRole("button", { name: /Akceptuj/ }));
    await waitFor(() => expect(showError).toHaveBeenCalledWith(message));
  });

  it("CV bez zgody RODO: zamiast podglądu i pobrania komunikat i dołączenie zrzutu", async () => {
    mockApi({
      cvs: [{ id: 77, status: "ready", filename: "cv.docx", origin: "auto", needs_review: true, consent_missing: true }],
    });
    renderPanel();
    expect(await screen.findByTestId("dl-review-consent-missing")).toHaveTextContent("Brak zgody RODO (PKO BP)");
    expect(consentProps).toHaveBeenCalledWith(
      expect.objectContaining({ generatedId: 77, hasConsent: false, compact: true }),
    );
    // Serwer i tak odmówiłby pobrania (409) — nie próbujemy ani renderu, ani pliku.
    expect(renderDocxSafely).not.toHaveBeenCalled();
    expect(get).not.toHaveBeenCalledWith("/api/cv-generator/generated/77/docx", expect.anything());
    expect(screen.queryByRole("button", { name: /Pobierz DOCX/ })).toBeNull();
    // Wysyłka do klienta nie jest blokowana brakiem zgody.
    await userEvent.type(screen.getByLabelText("Stawka do klienta"), "180");
    expect(screen.getByRole("button", { name: /Akceptuj/ })).toBeEnabled();
  });

  it("rekruter tylko przegląda — bez wysyłki i bez odrzucenia DL", async () => {
    useAuthStore.setState({ user: { id: 2, role: "recruiter" } } as never);
    mockApi({ cvs: [] });
    renderPanel();
    expect(screen.getByRole("button", { name: /Akceptuj/ })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /^Odrzuć…/ })).toBeNull();
    // Zdanie nazywa uprawnienie, o które można poprosić — nie rolę.
    expect(
      screen.getByText(
        /Do klienta wysyła osoba z uprawnieniem „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta”/,
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/Do klienta wysyła Delivery Lead/)).toBeNull();
    expect(await screen.findByText(/nie ma jeszcze wygenerowanego CV/)).toBeTruthy();
  });

  describe("wysyłka do klienta za uprawnieniem, nie rolą", () => {
    const send = () => screen.getByRole("button", { name: /Akceptuj/ });
    const denial = () => screen.queryByText(/Do klienta wysyła osoba z uprawnieniem/);

    async function typeRate() {
      await userEvent.type(screen.getByLabelText("Stawka do klienta"), "180");
    }

    it.each(["delivery_lead", "admin"])(
      "%s ma uprawnienie domyślnie i wysyła",
      async (role) => {
        useAuthStore.setState({ user: { id: 3, role, roles: [role] } } as never);
        mockApi();
        renderPanel();
        await typeRate();
        expect(send()).toBeEnabled();
        expect(denial()).toBeNull();
      },
    );

    it("rekruter z nadanym uprawnieniem wysyła, ale nie odrzuca „przez DL” (to zostaje przy rolach)", async () => {
      useAuthStore.setState({
        user: {
          id: 4,
          role: "recruiter",
          roles: ["recruiter"],
          effective_action_access: permissionSnapshot("recruitment_manage"),
        },
      } as never);
      mockApi();
      renderPanel();
      await typeRate();
      expect(send()).toBeEnabled();
      expect(denial()).toBeNull();
      expect(screen.queryByRole("button", { name: /^Odrzuć…/ })).toBeNull();
    });

    it("Delivery Lead z wyłączonym uprawnieniem nie wysyła, ale nadal odrzuca „przez DL”", async () => {
      useAuthStore.setState({
        user: {
          id: 5,
          role: "delivery_lead",
          roles: ["delivery_lead"],
          effective_action_access: permissionSnapshot("delivery_view", "clients_edit"),
        },
      } as never);
      mockApi();
      renderPanel();
      expect(screen.getByLabelText("Stawka do klienta")).toBeDisabled();
      expect(send()).toBeDisabled();
      expect(denial()).not.toBeNull();
      expect(screen.getByRole("button", { name: /^Odrzuć…/ })).toBeInTheDocument();
    });

    it("flaga z serwera wygrywa z regułą lokalną w obie strony", async () => {
      // Kolejka pulpitu niesie `can_send_to_client` — to ona rozstrzyga.
      useAuthStore.setState({ user: { id: 6, role: "delivery_lead", roles: ["delivery_lead"] } } as never);
      mockApi();
      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      const view = render(
        <QueryClientProvider client={qc}>
          <DlReviewPanel task={task()} open onOpenChange={vi.fn()} canSendToClient={false} />
        </QueryClientProvider>,
      );
      expect(send()).toBeDisabled();
      expect(denial()).not.toBeNull();
      view.unmount();

      useAuthStore.setState({ user: { id: 7, role: "recruiter", roles: ["recruiter"] } } as never);
      render(
        <QueryClientProvider client={qc}>
          <DlReviewPanel task={task()} open onOpenChange={vi.fn()} canSendToClient />
        </QueryClientProvider>,
      );
      await typeRate();
      expect(send()).toBeEnabled();
      expect(denial()).toBeNull();
    });
  });

  it("pokazuje wynik QC CV i „Otwórz QC” otwiera okno QC dla etapu z kolejki", async () => {
    mockApi();
    renderPanel(task({ qc_status: "failed", qc_blocking_failed: 3 }));
    expect(screen.getByText("QC: 3 do poprawy")).toBeTruthy();
    expect(screen.queryByRole("dialog", { name: "QC CV" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Otwórz QC/ }));
    expect(screen.getByRole("dialog", { name: "QC CV" })).toHaveTextContent("QC etapu 11");
  });

  describe("uwaga rekrutera z przekazania (14.10.2026)", () => {
    it("stoi na górze kolumny decyzji, nad „Warunkami”, z autorem", async () => {
      mockApi({
        context: {
          ...CONTEXT,
          recruiter_handoff_remark: {
            text: "Kandydat dostępny od listopada, woli hybrydę.",
            author_name: "Marta Rekruterka",
            created_at: "2026-10-14T09:00:00Z",
          },
        },
      });
      renderPanel();
      const remark = await screen.findByTestId("dl-review-recruiter-remark");
      expect(remark).toHaveTextContent("Od rekrutera (Marta Rekruterka): Kandydat dostępny od listopada, woli hybrydę.");
      const decision = screen.getByTestId("dl-review-decision");
      expect(decision).toContainElement(remark);
      const terms = within(decision).getByText("Warunki wobec rekrutacji");
      // Uwaga przed „Warunkami” w kolejności dokumentu.
      expect(remark.compareDocumentPosition(terms) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("bez autora — samo „Od rekrutera”; bez uwagi (albo pusta) — nic", async () => {
      mockApi({
        context: { ...CONTEXT, recruiter_handoff_remark: { text: "Pilne.", author_name: null, created_at: "2026-10-14T09:00:00Z" } },
      });
      const first = renderPanel();
      expect(await screen.findByTestId("dl-review-recruiter-remark")).toHaveTextContent("Od rekrutera: Pilne.");
      first.view.unmount();

      mockApi({
        context: { ...CONTEXT, recruiter_handoff_remark: { text: "  ", author_name: "X", created_at: "2026-10-14T09:00:00Z" } },
      });
      const second = renderPanel();
      expect(await screen.findByText("…Java 17 w banku…")).toBeTruthy();
      expect(screen.queryByTestId("dl-review-recruiter-remark")).toBeNull();
      second.view.unmount();

      mockApi();
      renderPanel();
      expect(await screen.findByText("…Java 17 w banku…")).toBeTruthy();
      expect(screen.queryByTestId("dl-review-recruiter-remark")).toBeNull();
    });
  });

  describe("karta przesunięta mimo uwag QC (tryb doradczy)", () => {
    const OVERRIDE_AT = "2026-10-12T10:00:00Z";
    const overridden = (qc_override: Record<string, unknown> | null) => ({
      ...CONTEXT,
      qc_status: "overridden",
      qc_blocking_failed: 2,
      qc_override,
    });

    it("baner mówi kto, kiedy, dlaczego i ile zostało do sprawdzenia; „Otwórz QC” otwiera okno QC", async () => {
      mockApi({
        context: overridden({ reason: "Klient prosił o krótsze CV", by_name: "Marta Rekruterka", at: OVERRIDE_AT }),
      });
      renderPanel(task({ qc_status: "overridden", qc_blocking_failed: 2 }));
      const banner = await screen.findByTestId("dl-review-qc-override");
      expect(banner).toHaveTextContent(
        `Przesunięte mimo uwag QC — Marta Rekruterka, ${formatDate(OVERRIDE_AT)}: Klient prosił o krótsze CV. Do sprawdzenia: 2.`,
      );
      expect(screen.queryByRole("dialog", { name: "QC CV" })).toBeNull();
      await userEvent.click(within(banner).getByRole("button", { name: "Otwórz QC" }));
      expect(screen.getByRole("dialog", { name: "QC CV" })).toHaveTextContent("QC etapu 11");
    });

    it("bez nazwiska pisze „rekruter”; kropka z końca powodu się nie dubluje", async () => {
      mockApi({ context: overridden({ reason: "Kandydat potwierdził w rozmowie.", by_name: null, at: OVERRIDE_AT }) });
      renderPanel();
      expect(await screen.findByTestId("dl-review-qc-override")).toHaveTextContent(
        `Przesunięte mimo uwag QC — rekruter, ${formatDate(OVERRIDE_AT)}: Kandydat potwierdził w rozmowie. Do sprawdzenia: 2.`,
      );
    });

    it("banera nie ma, gdy QC przeszło albo kontekst nie niesie obejścia", async () => {
      mockApi({
        context: {
          ...CONTEXT,
          qc_override: { reason: "Klient prosił o krótsze CV", by_name: "Marta Rekruterka", at: OVERRIDE_AT },
        },
      });
      const first = renderPanel();
      // Kontekst jest już wczytany (wymagania na ekranie), a banera nie ma.
      expect(await screen.findByText("…Java 17 w banku…")).toBeTruthy();
      expect(screen.queryByTestId("dl-review-qc-override")).toBeNull();
      first.view.unmount();

      mockApi({ context: overridden(null) });
      renderPanel();
      expect(await screen.findByText("…Java 17 w banku…")).toBeTruthy();
      expect(screen.queryByTestId("dl-review-qc-override")).toBeNull();
    });
  });

  it("409 CV_QC_FAILED przy wysyłce → komunikat i okno QC wskazanego etapu", async () => {
    mockApi();
    post.mockRejectedValue({
      response: {
        status: 409,
        data: {
          detail: {
            code: "CV_QC_FAILED",
            message: "CV nie przeszło QC — do poprawy: 3.",
            blocking_failed: 3,
            stage_id: 12,
          },
        },
      },
    });
    const { onOpenChange } = renderPanel();
    await userEvent.type(screen.getByLabelText("Stawka do klienta"), "180");
    await userEvent.click(screen.getByRole("button", { name: /Akceptuj/ }));
    await waitFor(() => expect(showError).toHaveBeenCalledWith("CV nie przeszło QC — do poprawy: 3."));
    expect(await screen.findByRole("dialog", { name: "QC CV" })).toHaveTextContent("QC etapu 12");
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("runda 7 (R7-X4-2): CV firmowe etapu (po QC) zamiast surowego pliku z generatora", async () => {
    mockApi();
    const stageBlob = new Blob(["po-qc"]);
    fetchStageCvFile.mockResolvedValue({ blob: stageBlob, filename: "CV.docx" });
    renderPanel(task({ cv_stage_id: 55 }));
    await waitFor(() => expect(renderDocxSafely).toHaveBeenCalledTimes(1));
    expect(fetchStageCvFile).toHaveBeenCalledWith(55);
    expect(renderDocxSafely.mock.calls[0][0]).toBe(stageBlob);
    expect(get).not.toHaveBeenCalledWith("/api/cv-generator/generated/77/docx", expect.anything());
  });

  it("runda 7: odmowa pliku etapu (409 zgoda RODO) pokazuje komunikat serwera", async () => {
    mockApi();
    fetchStageCvFile.mockRejectedValue(
      Object.assign(new Error("x"), {
        response: {
          status: 409,
          data: { detail: { code: "consent_required", message: "Dołącz zgodę do tego CV." } },
        },
      }),
    );
    renderPanel(task({ cv_stage_id: 55 }));
    expect(await screen.findByText("Dołącz zgodę do tego CV.")).toBeTruthy();
    expect(renderDocxSafely).not.toHaveBeenCalled();
  });

  // D4 (09.10.2026): CV pierwsze i największe po lewej, decyzja w stałej
  // kolumnie po prawej; „Wymagania i ocena” jako zakładka albo środkowa kolumna.
  describe("układ D4 — z szerokości przeglądu", () => {
    const CELLS = [
      "dl-review-cv-toolbar",
      "dl-review-cv",
      "dl-review-requirements-cell",
      "dl-review-decision",
    ];
    const cells = () =>
      Array.from(screen.getByTestId("dl-review-cv").parentElement!.children).map((cell) =>
        cell.getAttribute("data-testid"),
      );

    afterEach(() => {
      layout.width = 0;
    });

    it("progi: poniżej 1100 px jedna kolumna, do 1639 px zakładki, szerzej trzy kolumny", () => {
      expect(dlReviewMode(0)).toBe("stack");
      expect(dlReviewMode(1099)).toBe("stack");
      expect(dlReviewMode(1100)).toBe("tabs");
      expect(dlReviewMode(1639)).toBe("tabs");
      expect(dlReviewMode(1640)).toBe("columns");
    });

    it("wąsko: CV, wymagania i decyzja jedno pod drugim — bez skrótu i trzeciej pigułki", async () => {
      mockApi();
      renderPanel();
      expect(cells()).toEqual(CELLS);
      expect(screen.getByTestId("dl-review-cv")).not.toHaveAttribute("hidden");
      expect(screen.getByTestId("dl-review-requirements-cell")).not.toHaveAttribute("hidden");
      expect(screen.queryByTestId("dl-review-requirements-summary")).toBeNull();
      expect(screen.queryByRole("button", { name: /Wymagania i ocena/ })).toBeNull();
      expect(screen.getByTestId("dl-review-actions").className).not.toContain("sticky");
      await waitFor(() => expect(renderDocxSafely).toHaveBeenCalledTimes(1));
    });

    it("zakładki: skrót wymagań z liczbami z serwera; „Pokaż” zamienia CV na wymagania", async () => {
      layout.width = 1280;
      mockApi();
      renderPanel(task({ return_stage_def_id: 302 }));
      expect(cells()).toEqual(CELLS);
      const summary = screen.getByTestId("dl-review-requirements-summary");
      // 1/2 liczy serwer; „do oceny” (mile widziane) nie jest brakiem.
      await waitFor(() => expect(summary).toHaveTextContent("Wymagania 1/2 · brak: Oracle"));
      expect(summary).toHaveTextContent("Ocena rekrutera: Pasuje");
      const pill = screen.getByRole("button", { name: /Wymagania i ocena/ });
      expect(pill).toHaveTextContent("1 brak");
      expect(pill).toHaveAttribute("aria-pressed", "false");
      const cv = screen.getByTestId("dl-review-cv");
      const requirements = screen.getByTestId("dl-review-requirements-cell");
      expect(cv).not.toHaveAttribute("hidden");
      expect(requirements).toHaveAttribute("hidden");
      // Trzy decyzje, każda raz, w przyklejonej stopce kolumny.
      const actions = screen.getByTestId("dl-review-actions");
      expect(actions.className).toContain("sticky");
      expect(within(actions).getByRole("button", { name: /Akceptuj/ })).toBe(
        screen.getByRole("button", { name: /Akceptuj/ }),
      );
      expect(within(actions).getByRole("button", { name: /Wróć do poprawy…/ })).toBeInTheDocument();
      expect(within(actions).getByRole("button", { name: /^Odrzuć…/ })).toBeInTheDocument();

      await userEvent.click(within(summary).getByRole("button", { name: "Pokaż wymagania i ocenę" }));
      expect(requirements).not.toHaveAttribute("hidden");
      expect(cv).toHaveAttribute("hidden");
      expect(pill).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByRole("button", { name: "CV firmowe" })).toHaveAttribute("aria-pressed", "false");
      expect(within(requirements).getByText("1/2 krytycznych i musi mieć")).toBeTruthy();

      // Powrót do CV: ta sama komórka, plik nie pobiera się drugi raz.
      await userEvent.click(screen.getByRole("button", { name: "CV firmowe" }));
      expect(screen.getByTestId("dl-review-cv")).toBe(cv);
      expect(cv).not.toHaveAttribute("hidden");
      expect(requirements).toHaveAttribute("hidden");
      await waitFor(() => expect(renderDocxSafely).toHaveBeenCalledTimes(1));
    });

    it("zakładki: klik w wymaganie wraca do CV i szuka jego słów w CV firmowym", async () => {
      layout.width = 1280;
      mockApi();
      championGet.mockResolvedValue({
        data: { champion_profile: {}, job_values: {}, job_title: "Java", requirement_find_words: { Oracle: ["Oracle", "PL/SQL"] } },
      });
      renderDocxSafely.mockImplementation(async (_blob: Blob, host: HTMLElement) => {
        host.innerHTML = "<p>PL/SQL na Oracle 19c, Java 17.</p>";
      });
      renderPanel();
      await waitFor(() => expect(championGet).toHaveBeenCalledWith(31));
      await screen.findByRole("searchbox", { name: "Szukaj w CV" });

      await userEvent.click(screen.getByRole("button", { name: /Wymagania i ocena/ }));
      const requirements = screen.getByTestId("dl-review-requirements-cell");
      // „Do oceny” (zdanie, cecha) nie ma lupy — szukanie zdania zawsze dałoby „Brak wyników”.
      expect(within(requirements).queryByRole("button", { name: "Szukaj w CV: komunikatywność" })).toBeNull();
      await userEvent.click(within(requirements).getByRole("button", { name: "Szukaj w CV: Oracle" }));

      expect(requirements).toHaveAttribute("hidden");
      expect(screen.getByTestId("dl-review-cv")).not.toHaveAttribute("hidden");
      expect(screen.getByRole("button", { name: "CV firmowe" })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByRole("searchbox", { name: "Szukaj w CV" })).toHaveValue("Oracle");
      expect(await screen.findByText("1 z 2")).toBeInTheDocument();
      expect(screen.getByTestId("document-search-terms")).toHaveTextContent("PL/SQL");
    });

    it("zakładki: brak w skrócie decyzji szuka się w CV bez przełączania widoku", async () => {
      layout.width = 1280;
      mockApi();
      championGet.mockResolvedValue({ data: { champion_profile: {}, job_values: {}, job_title: "Java" } });
      renderDocxSafely.mockImplementation(async (_blob: Blob, host: HTMLElement) => {
        host.innerHTML = "<p>Java 17 w banku.</p>";
      });
      renderPanel();
      const summary = screen.getByTestId("dl-review-requirements-summary");
      await screen.findByRole("searchbox", { name: "Szukaj w CV" });

      await userEvent.click(await within(summary).findByRole("button", { name: "Szukaj w CV: Oracle" }));
      expect(screen.getByRole("searchbox", { name: "Szukaj w CV" })).toHaveValue("Oracle");
      // Bez słów z serwera lupa szuka samej nazwy — w tym CV jej nie ma.
      expect(await screen.findByText("Brak wyników")).toBeInTheDocument();
      expect(screen.getByTestId("dl-review-requirements-cell")).toHaveAttribute("hidden");
    });

    it("zakładki: awaria kontekstu — skrót bez liczb, decyzja nadal możliwa", async () => {
      layout.width = 1280;
      mockApi({ context: null });
      renderPanel();
      const summary = screen.getByTestId("dl-review-requirements-summary");
      await waitFor(() => expect(summary).toHaveTextContent("nie udało się wczytać porównania"));
      expect(summary).not.toHaveTextContent(/\d\/\d/);
      expect(screen.getByRole("button", { name: /Wymagania i ocena/ })).not.toHaveTextContent(/brak/);
      await userEvent.type(screen.getByLabelText("Stawka do klienta"), "180");
      expect(screen.getByRole("button", { name: /Akceptuj/ })).toBeEnabled();
    });

    it("zakładki: formularz odrzucenia przewija się w pole widzenia", async () => {
      layout.width = 1280;
      mockApi();
      const scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView");
      try {
        renderPanel();
        await userEvent.click(screen.getByRole("button", { name: /^Odrzuć…/ }));
        const group = screen.getByRole("group", { name: "Odrzucenie przez DL" });
        await waitFor(() => expect(scrollIntoView.mock.instances).toContain(group));
        expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest" });
      } finally {
        scrollIntoView.mockRestore();
      }
    });

    it("trzy kolumny: wymagania obok CV — bez skrótu i bez trzeciej pigułki", async () => {
      layout.width = 1700;
      mockApi();
      renderPanel();
      expect(cells()).toEqual(CELLS);
      const requirements = screen.getByTestId("dl-review-requirements-cell");
      expect(requirements).not.toHaveAttribute("hidden");
      expect(screen.getByTestId("dl-review-cv")).not.toHaveAttribute("hidden");
      expect(within(requirements).getByRole("heading", { name: "Wymagania i ocena" })).toBeInTheDocument();
      expect(await within(requirements).findByText("1/2 krytycznych i musi mieć")).toBeTruthy();
      expect(screen.queryByTestId("dl-review-requirements-summary")).toBeNull();
      expect(screen.queryByRole("button", { name: /Wymagania i ocena/ })).toBeNull();
      expect(screen.getByRole("button", { name: /Akceptuj/ })).toBeInTheDocument();
      expect(screen.getByTestId("dl-review-actions").className).toContain("sticky");
      await waitFor(() => expect(renderDocxSafely).toHaveBeenCalledTimes(1));
    });

    it("zmiana szerokości nie montuje CV od nowa — plik pobiera się raz", async () => {
      layout.width = 1280;
      mockApi();
      const row = task();
      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      const tree = () => (
        <QueryClientProvider client={qc}>
          <DlReviewPanel task={row} open onOpenChange={() => undefined} />
        </QueryClientProvider>
      );
      const view = render(tree());
      await waitFor(() => expect(renderDocxSafely).toHaveBeenCalledTimes(1));
      const cv = screen.getByTestId("dl-review-cv");
      const host = screen.getByTestId("dl-review-cv-host");
      for (const width of [1700, 800, 1280]) {
        layout.width = width;
        view.rerender(tree());
        expect(screen.getByTestId("dl-review-cv")).toBe(cv);
        expect(screen.getByTestId("dl-review-cv-host")).toBe(host);
        expect(cells()).toEqual(CELLS);
      }
      expect(renderDocxSafely).toHaveBeenCalledTimes(1);
      expect(get.mock.calls.filter(([url]) => url === "/api/cv-generator/generated/77/docx")).toHaveLength(1);
    });
  });
});

describe("DlReviewPanel — odrzucenie z uzasadnieniem i rozmowa u tego managera (20.10.2026)", () => {
  const INTERVIEWS = [
    {
      job_id: 501,
      job_title: "PL - Rating & Limit Management Unit",
      interview_at: "2026-08-21T10:00:00Z",
      latest_stage: "Rozmowa u klienta",
      same_hiring_manager: true,
    },
    {
      job_id: 502,
      job_title: "SD Collateral - IT Operations Midrange",
      interview_at: "2026-08-19T10:00:00Z",
      latest_stage: "Odrzucony",
      same_hiring_manager: false,
    },
  ];
  const REASONS = [
    { id: "5", label: "Za wysoka stawka", applies_to: ["rejected"], disqualifies_person: false },
    { id: "8", name: "Inne (rejected)", label: "Inne", applies_to: ["rejected"], disqualifies_person: false },
    {
      id: "12",
      name: "hm_already_interviewed",
      label: "Już po rozmowie u tego hiring managera",
      applies_to: ["rejected"],
      disqualifies_person: false,
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: { id: 1, role: "delivery_lead" } } as never);
    renderDocxSafely.mockResolvedValue(undefined);
    post.mockResolvedValue({ data: {} });
    loadJobRejectionReasons.mockResolvedValue(REASONS);
  });

  it("„Inne” wymaga opisu, a opis jedzie jako notatka ruchu", async () => {
    mockApi();
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: /^Odrzuć…/ }));
    const group = screen.getByRole("group", { name: "Odrzucenie przez DL" });
    const confirm = within(group).getByRole("button", { name: /Potwierdź odrzucenie/ });
    await userEvent.selectOptions(await within(group).findByRole("combobox"), "8");
    expect(confirm).toBeDisabled();
    await userEvent.type(within(group).getByLabelText(/Opisz powód/), "Klient zamknął budżet.");
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({ rejection_reason_id: 8, notes: "Klient zamknął budżet." }),
      ),
    );
  });

  it("zwykły powód: opis opcjonalny, bez opisu nie ma notatki", async () => {
    mockApi();
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: /^Odrzuć…/ }));
    const group = screen.getByRole("group", { name: "Odrzucenie przez DL" });
    await userEvent.selectOptions(await within(group).findByRole("combobox"), "5");
    expect(within(group).getByLabelText(/Opis powodu \(opcjonalnie\)/)).toBeTruthy();
    await userEvent.click(within(group).getByRole("button", { name: /Potwierdź odrzucenie/ }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1].notes).toBeUndefined();
  });

  it("„Już po rozmowie…”: wybór rozmowy z listy, notatka z tytułem i datą", async () => {
    mockApi({ context: { ...CONTEXT, earlier_interviews: INTERVIEWS } });
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: /^Odrzuć…/ }));
    const group = screen.getByRole("group", { name: "Odrzucenie przez DL" });
    const confirm = within(group).getByRole("button", { name: /Potwierdź odrzucenie/ });
    await userEvent.selectOptions(await within(group).findByRole("combobox"), "12");
    const list = within(group).getByTestId("dl-reject-interviews");
    expect(confirm).toBeDisabled();
    await userEvent.click(within(list).getByText("SD Collateral - IT Operations Midrange"));
    await userEvent.type(within(group).getByLabelText(/Dopisek/), "manager pamięta ją z sierpnia");
    await userEvent.click(confirm);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({
          rejection_reason_id: 12,
          notes: "SD Collateral - IT Operations Midrange · rozmowa 19.08.2026 — manager pamięta ją z sierpnia",
        }),
      ),
    );
  });

  it("„Poza NEXUSEM” wymaga opisu rozmowy", async () => {
    mockApi({ context: { ...CONTEXT, earlier_interviews: INTERVIEWS } });
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: /^Odrzuć…/ }));
    const group = screen.getByRole("group", { name: "Odrzucenie przez DL" });
    const confirm = within(group).getByRole("button", { name: /Potwierdź odrzucenie/ });
    await userEvent.selectOptions(await within(group).findByRole("combobox"), "12");
    await userEvent.click(within(group).getByText("Poza NEXUSEM / nie ma na liście"));
    expect(confirm).toBeDisabled();
    await userEvent.type(within(group).getByLabelText(/Na jakiej rozmowie i kiedy/), "Teams 02.10, z Traffita");
    expect(confirm).toBeEnabled();
  });

  it("ostrzeżenie o tym samym managerze: „Odrzuć z tym powodem” wybiera powód i rozmowę", async () => {
    mockApi({
      context: { ...CONTEXT, hiring_manager_name: "Anna Manager", earlier_interviews: INTERVIEWS },
    });
    renderPanel();
    const notice = await screen.findByTestId("dl-review-same-manager");
    expect(notice).toHaveTextContent("hiring managera tej rekrutacji (Anna Manager)");
    expect(notice).toHaveTextContent("PL - Rating & Limit Management Unit");
    // Rozmowa u innego managera tego klienta nie jest powodem do ostrzeżenia.
    expect(notice).not.toHaveTextContent("SD Collateral");
    await userEvent.click(within(notice).getByRole("button", { name: "Odrzuć z tym powodem" }));
    const group = screen.getByRole("group", { name: "Odrzucenie przez DL" });
    await waitFor(() => expect(within(group).getByRole("combobox")).toHaveValue("12"));
    const confirm = within(group).getByRole("button", { name: /Potwierdź odrzucenie/ });
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({
          rejection_reason_id: 12,
          notes: "PL - Rating & Limit Management Unit · rozmowa 21.08.2026",
        }),
      ),
    );
  });

  it("„Wiem — oceniam dalej” chowa ostrzeżenie; bez rozmowy u tego managera go nie ma", async () => {
    mockApi({ context: { ...CONTEXT, earlier_interviews: INTERVIEWS } });
    const { view } = renderPanel();
    const notice = await screen.findByTestId("dl-review-same-manager");
    await userEvent.click(within(notice).getByRole("button", { name: "Wiem — oceniam dalej" }));
    expect(screen.queryByTestId("dl-review-same-manager")).toBeNull();
    view.unmount();

    mockApi({ context: { ...CONTEXT, earlier_interviews: [INTERVIEWS[1]] } });
    renderPanel();
    await screen.findByText("Kraków");
    expect(screen.queryByTestId("dl-review-same-manager")).toBeNull();
  });
});
