import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();
const renderDocxSafely = vi.fn();
const loadJobRejectionReasons = vi.fn();
const fetchStageCvFile = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
  pipelineApi: {
    move: (data: unknown) => post("/api/pipeline/move", data),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));
vi.mock("@/lib/docx-preview-safe", () => ({
  renderDocxSafely: (...a: unknown[]) => renderDocxSafely(...a),
}));
vi.mock("@/lib/cv-docx-preview", () => ({ alignB2bLetterheadPreview: () => undefined }));
vi.mock("@/lib/stage-cv-file", () => ({
  fetchStageCvFile: (...a: unknown[]) => fetchStageCvFile(...a),
}));
vi.mock("@/lib/rejection-reasons", () => ({
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
vi.mock("@/components/v2/recruitment/PanelSavedViews", () => ({
  SavedScreeningView: ({ item }: { item: { id: number } }) => (
    <div data-testid="saved-screening">arkusz z wiersza {item.id}</div>
  ),
}));

import { DlReviewPanel } from "@/components/v2/recruitment/DlReviewPanel";
import type { BoardTaskRow } from "@/lib/api/boardTasks";
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

const CARD = {
  candidate_id: 21,
  job_id: 31,
  exists: true,
  fields: {
    rate: { raw: "140 zł/h B2B", source: "note", note_id: 3, at: since },
    availability: { raw: "od zaraz", source: "manual", by_name: "Marta Rekruterka", at: since },
  },
  previous: {},
  suggestions: {},
  questions: [
    { number: 1, question: "Doświadczenie z Kafką?", answer: "3 lata, produkcyjnie", source: "note" },
  ],
  completeness: { status: "partial", filled: 2, total: 10, missing: ["work_mode"] },
  labels: {},
  editable_fields: ["rate", "availability"],
  legacy_text: "",
};

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
}: {
  cvs?: Array<Record<string, unknown>>;
  availability?: Record<string, unknown> | null;
  context?: Record<string, unknown> | null;
} = {}) {
  get.mockImplementation((url: string) => {
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
    if (url === "/api/cv-generator/generated") return Promise.resolve({ data: cvs });
    if (url === "/api/recommendation-cards") return Promise.resolve({ data: CARD });
    if (url === "/api/cv-generator/generated/77/docx") return Promise.resolve({ data: new Blob(["docx"]) });
    return Promise.reject(new Error(`unexpected ${url}`));
  });
}

function renderPanel(row: BoardTaskRow = task(), onOpenChange = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <DlReviewPanel task={row} open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  );
  return { onOpenChange, qc };
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

  it("pokazuje kto zweryfikował, stawkę, dostępność, podgląd CV i arkusz screeningu", async () => {
    mockApi();
    renderPanel();
    expect(screen.getByText(/Zweryfikował\(a\) Marta Rekruterka/)).toBeTruthy();
    expect(screen.getByText("140 zł/h")).toBeTruthy();
    expect(await screen.findByText("Otwarty na oferty · wypowiedzenie 1 mies.")).toBeTruthy();
    expect(screen.getByText("Kraków")).toBeTruthy();
    expect(screen.getByTestId("saved-screening")).toHaveTextContent("arkusz z wiersza 9");
    // Karta rekomendacji z odpowiedziami na pytania Championa — także z notatki.
    const cardSection = screen.getByRole("region", { name: "Karta rekomendacji" });
    expect(await within(cardSection).findByText("140 zł/h B2B")).toBeTruthy();
    expect(within(cardSection).getByText("3 lata, produkcyjnie")).toBeTruthy();
    expect(within(cardSection).getByText("odpowiedź z notatki")).toBeTruthy();
    await waitFor(() => expect(renderDocxSafely).toHaveBeenCalledTimes(1));
    expect(get).toHaveBeenCalledWith("/api/cv-generator/generated", {
      params: { candidate_id: 21, job_id: 31, limit: 10 },
    });
    expect(screen.getByText("Do przeglądu")).toBeTruthy();
  });

  it("naruszone „Odpada, gdy…” z karty: ostrzeżenie w stopce i warunek pod pytaniem", async () => {
    mockApi();
    const base = get.getMockImplementation() as (url: string) => Promise<unknown>;
    get.mockImplementation((url: string) =>
      url === "/api/recommendation-cards"
        ? Promise.resolve({
            data: {
              ...CARD,
              questions: [
                {
                  ...CARD.questions[0],
                  // Trafienie żyje w arkuszu screeningu — odpowiedź też z arkusza.
                  source: "sheet",
                  question_id: "q1",
                  deal_breaker: "mniej niż rok z Kafką",
                  deal_breaker_hit: true,
                },
              ],
            },
          })
        : base(url),
    );
    renderPanel();
    expect(await screen.findByTestId("dl-review-deal-breaker")).toHaveTextContent(
      "Odpowiedź na pytanie 1 narusza „Odpada, gdy…”.",
    );
    expect(screen.getByText("Odpada, gdy: mniej niż rok z Kafką")).toBeTruthy();
    // 0424: trafienie zaznacza rekruter w formularzu screeningu — przegląd
    // pokazuje je tylko do odczytu.
    expect(screen.queryByRole("checkbox", { name: "Odpowiedź narusza deal-breaker" })).toBeNull();
    expect(screen.getAllByText("Odpowiedź narusza deal-breaker").length).toBeGreaterThan(0);
  });

  // Test na produkcji 03.10.2026: karta niżej mówiła „2 tygodnie”, a kafel
  // „Dostępność” nad nią „—”, bo czytał wyłącznie profil.
  it("dostępność bierze z karty rekomendacji, gdy profil jej nie zna", async () => {
    mockApi({ availability: null });
    renderPanel();
    const hint = await screen.findByText("z karty");
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
        recruiter_remark: "Za drogo dla klienta",
      }),
    );
    expect(showSuccess).toHaveBeenCalledWith("Anna Nowak — odrzucony przez DL.");
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
});
