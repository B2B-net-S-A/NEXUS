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

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));
vi.mock("@/lib/docx-preview-safe", () => ({
  renderDocxSafely: (...a: unknown[]) => renderDocxSafely(...a),
}));
vi.mock("@/lib/cv-docx-preview", () => ({ alignB2bLetterheadPreview: () => undefined }));
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
vi.mock("@/components/v2/recruitment/PanelSavedViews", () => ({
  SavedScreeningView: ({ item }: { item: { id: number } }) => (
    <div data-testid="saved-screening">arkusz z wiersza {item.id}</div>
  ),
}));

import { DlReviewPanel } from "@/components/v2/recruitment/DlReviewPanel";
import type { BoardTaskRow } from "@/lib/api/boardTasks";
import { useAuthStore } from "@/store/auth";

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
    ...over,
  };
}

function mockApi({
  cvs = [{ id: 77, status: "ready", filename: "cv.docx", origin: "auto", needs_review: true }],
}: { cvs?: Array<Record<string, unknown>> } = {}) {
  get.mockImplementation((url: string) => {
    if (url === "/api/candidates/21/quick-view") {
      return Promise.resolve({
        data: {
          candidate: { city: "Kraków", expected_rate_hourly: null },
          current_position: { title: "Senior Java Developer" },
          availability: { status: "open_to_offers", available_from: null, notice_period: 1, notice_period_unit: "months" },
        },
      });
    }
    if (url === "/api/cv-generator/generated") return Promise.resolve({ data: cvs });
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
    await waitFor(() => expect(renderDocxSafely).toHaveBeenCalledTimes(1));
    expect(get).toHaveBeenCalledWith("/api/cv-generator/generated", {
      params: { candidate_id: 21, job_id: 31, limit: 10 },
    });
    expect(screen.getByText("Do przeglądu")).toBeTruthy();
  });

  it("„Wyślij do klienta” wymaga stawki i wysyła ruch na „CV wysłane” ze stawką i wersją", async () => {
    mockApi();
    const { onOpenChange } = renderPanel();
    const send = screen.getByRole("button", { name: /Wyślij do klienta/ });
    expect(send).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Stawka do klienta"), "180");
    // Decyzja 23.09.2026: przegląd DL nie pokazuje marży.
    expect(screen.queryByText(/Marża/)).toBeNull();
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
    await userEvent.click(screen.getByRole("button", { name: /Odrzuć \(DL\)/ }));
    const group = screen.getByRole("group", { name: "Odrzucenie przez DL" });
    const confirm = within(group).getByRole("button", { name: /Potwierdź odrzucenie/ });
    const select = await within(group).findByRole("combobox");
    expect(within(select).queryByRole("option", { name: "Kandydat zrezygnował" })).toBeNull();
    expect(confirm).toBeDisabled();
    await userEvent.selectOptions(select, "5");
    await userEvent.type(within(group).getByRole("textbox"), "Za drogo dla klienta");
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
        notes: "Za drogo dla klienta",
      }),
    );
    expect(showSuccess).toHaveBeenCalledWith("Anna Nowak — odrzucony przez DL.");
  });

  it("konflikt wersji → komunikat i zamknięcie, bez ponowienia", async () => {
    mockApi();
    post.mockRejectedValue({
      response: { status: 409, data: { detail: { code: "PIPELINE_VERSION_CONFLICT" } } },
    });
    const { onOpenChange } = renderPanel();
    await userEvent.type(screen.getByLabelText("Stawka do klienta"), "180");
    await userEvent.click(screen.getByRole("button", { name: /Wyślij do klienta/ }));
    await waitFor(() => expect(showError).toHaveBeenCalledWith(expect.stringMatching(/przesunięty przez kogoś innego/)));
    expect(post).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("odmowa serwera (403) pokazuje jego komunikat po polsku", async () => {
    mockApi();
    post.mockRejectedValue({
      response: { status: 403, data: { detail: "Do klienta wysyła Delivery Lead." } },
    });
    renderPanel();
    await userEvent.type(screen.getByLabelText("Stawka do klienta"), "180");
    await userEvent.click(screen.getByRole("button", { name: /Wyślij do klienta/ }));
    await waitFor(() => expect(showError).toHaveBeenCalledWith("Do klienta wysyła Delivery Lead."));
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
    expect(screen.getByRole("button", { name: /Wyślij do klienta/ })).toBeEnabled();
  });

  it("rekruter tylko przegląda — bez wysyłki i bez odrzucenia DL", async () => {
    useAuthStore.setState({ user: { id: 2, role: "recruiter" } } as never);
    mockApi({ cvs: [] });
    renderPanel();
    expect(screen.getByRole("button", { name: /Wyślij do klienta/ })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Odrzuć \(DL\)/ })).toBeNull();
    expect(screen.getByText(/Do klienta wysyła Delivery Lead/)).toBeTruthy();
    expect(await screen.findByText(/nie ma jeszcze wygenerowanego CV/)).toBeTruthy();
  });
});
