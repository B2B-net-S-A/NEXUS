/**
 * „Wypełnij formularz” / „Wypełnij tabelę” w ramce „Następny etap” (zgłoszenie
 * DL z 26.11.2026: „nie działają te przyciski”). Okno formularza rysuje się
 * tylko przy wypełnionym dokumencie, więc klik przy niewypełnionym nic nie
 * robił, a karta tabeli punktowej w ogóle nie dostawała sygnału „otwórz”.
 * Teraz klik wypełnia dokument (to samo co „Wypełnij z CV i screeningu” na
 * karcie) i otwiera okno braków. Mocki jak w `PipelineCandidateDock.test.tsx`.
 */
import type { ComponentProps } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientFormView } from "@/lib/api/clientForms";

const formGet = vi.fn();
const originalGet = vi.fn();
const brandedGet = vi.fn();
const candidatesGet = vi.fn();
const apiGet = vi.fn();
const apiPost = vi.fn();

vi.mock("next/dynamic", () => ({ default: () => () => null }));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (url: string, ...rest: unknown[]) =>
      url === "/api/screening-form" ? formGet(url, ...rest) : apiGet(url, ...rest),
    post: (...a: unknown[]) => apiPost(...a),
  },
  candidatesApi: { get: (...a: unknown[]) => candidatesGet(...a) },
  candidateStageCvApi: {
    original: { get: (...a: unknown[]) => originalGet(...a) },
    branded: { get: (...a: unknown[]) => brandedGet(...a) },
  },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
}));

const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: (...a: unknown[]) => toastSuccess(...a),
    showError: (...a: unknown[]) => toastError(...a),
  }),
}));

vi.mock("@/components/v2/jobs/DockCallCheatsheet", () => ({ DockCallCheatsheet: () => null }));
vi.mock("@/components/v2/modals/QuickAssignV2", () => ({ QuickAssignV2: () => null }));
vi.mock("@/components/v2/modals/CVOriginalPreviewModal", () => ({ CVOriginalPreviewModal: () => null }));
vi.mock("@/components/v2/modals/CVShareLinkModal", () => ({ CVShareLinkModal: () => null }));
vi.mock("@/components/emails/EmailCompose", () => ({ default: () => null }));
vi.mock("@/components/v2/cv-generator/CvGeneratorDialog", () => ({ CvGeneratorDialog: () => null }));
vi.mock("@/components/v2/pages/DopasowanieTab", () => ({ DopasowanieTab: () => null }));
vi.mock("@/components/v2/recruitment/CvQcDialog", () => ({ CvQcDialog: () => null }));
vi.mock("@/components/v2/recruitment/DebriefRequiredDialog", () => ({ DebriefRequiredDialog: () => null }));

import { PipelineCandidateDock } from "@/components/v2/jobs/PipelineCandidateDock";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";

const STAGE_ID = 501;

function item(): KanbanItem {
  return {
    id: STAGE_ID,
    candidate_id: 42,
    stage: "verified",
    name: "Anna",
    lastname: "Fikcyjna",
    days_in_stage: 1,
    verification_status: "active",
    client_form: { template: true, missing: null, score_template: true, score_missing: null },
  };
}

const QC_TARGET: KanbanColumn = {
  stage: "interview",
  name: "QC CV",
  category: "internal",
  count: 0,
  items: [],
  stage_def_id: 9,
};

const REQUIREMENTS = {
  from_column: "verified",
  to_column: "cv_qc",
  skipped_columns: [],
  items: [
    {
      key: "client_form",
      column: "cv_qc",
      label: "Formularz CV klienta",
      status: "missing",
      blocking: false,
      detail: "jeszcze nie wypełniony",
      action: { kind: "open_client_form", label: "Wypełnij formularz", stage_id: STAGE_ID },
    },
    {
      key: "client_score",
      column: "cv_qc",
      label: "Tabela punktowa klienta",
      status: "missing",
      blocking: false,
      detail: "jeszcze nie wypełniona",
      action: { kind: "open_client_form", label: "Wypełnij tabelę", stage_id: STAGE_ID },
    },
  ],
  primary: { kind: "move", label: "Przenieś" },
  owner_note: null,
};

function clientView(kind: "form" | "score", over: Partial<ClientFormView> = {}): ClientFormView {
  return {
    kind,
    client_document: "client_form",
    status: "not_filled",
    message: null,
    template: {
      file_id: kind === "score" ? 8 : 7,
      filename: kind === "score" ? "Opis oceny.xlsx" : "Formularz CV.docx",
      summary: "2 pola",
    },
    template_changed: false,
    fields: [
      { id: "p1", kind: "line", label: "Imię i nazwisko", section: null, row_label: null, table: null, value: null, source: null, quote: null },
      { id: "p2", kind: "line", label: "Wykształcenie", section: null, row_label: null, table: null, value: null, source: null, quote: null },
    ],
    extra_rows: [],
    missing: [],
    filled_at: null,
    updated_at: null,
    model: null,
    ...over,
  };
}

const FILLED_WITH_GAP = (kind: "form" | "score") =>
  clientView(kind, {
    status: "filled",
    missing: ["p2"],
    filled_at: "2026-11-26T11:00:00Z",
    fields: clientView(kind).fields.map((f) =>
      f.id === "p1" ? { ...f, value: "Anna Fikcyjna", source: "profile" } : f,
    ),
  });

const formUrl = `/api/candidates/stages/${STAGE_ID}/client-form`;

function routeApi() {
  apiGet.mockImplementation((url: string) => {
    if (url.startsWith("/api/pipeline/move-requirements")) return Promise.resolve({ data: REQUIREMENTS });
    if (url === formUrl) return Promise.resolve({ data: clientView("form") });
    if (url === `${formUrl}?kind=score`) return Promise.resolve({ data: clientView("score") });
    return Promise.resolve({ data: { items: [] } });
  });
  apiPost.mockImplementation((url: string) => {
    if (url === `${formUrl}/fill`) return Promise.resolve({ data: FILLED_WITH_GAP("form") });
    if (url === `${formUrl}/fill?kind=score`) return Promise.resolve({ data: FILLED_WITH_GAP("score") });
    return Promise.resolve({ data: {} });
  });
}

function renderDock() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const props: ComponentProps<typeof PipelineCandidateDock> = {
    item: item(),
    jobId: 10,
    currentStageLabel: "Zweryfikowany",
    moveTargets: [],
    primaryTarget: QC_TARGET,
    readOnly: false,
    contactFeatureEnabled: false,
    canReject: true,
    onClose: vi.fn(),
    onMoveTo: vi.fn(),
    onOpenScreening: vi.fn(),
    onReject: vi.fn(),
  };
  render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <PipelineCandidateDock {...props} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

function requirementRow(key: string): HTMLElement {
  const row = document.querySelector<HTMLElement>(`li[data-requirement="${key}"]`);
  if (!row) throw new Error(`brak wiersza ${key}`);
  return row;
}

describe("PipelineCandidateDock — formularz CV klienta z ramki „Następny etap”", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    formGet.mockResolvedValue({ data: formState({ candidate_id: 42, job_id: 10, stage_id: STAGE_ID }) });
    originalGet.mockResolvedValue({ data: { has_snapshot: false } });
    brandedGet.mockResolvedValue({ data: { status: "none" } });
    candidatesGet.mockResolvedValue({ data: {} });
    routeApi();
  });

  it("„Wypełnij formularz” przy niewypełnionym wypełnia go i otwiera okno braków", async () => {
    const user = userEvent.setup();
    renderDock();
    await screen.findByRole("button", { name: "Wypełnij formularz" });

    await user.click(screen.getByRole("button", { name: "Wypełnij formularz" }));

    await waitFor(() => expect(apiPost).toHaveBeenCalledWith(`${formUrl}/fill`, null, expect.anything()));
    expect(apiPost).not.toHaveBeenCalledWith(`${formUrl}/fill?kind=score`, null, expect.anything());
    expect(await screen.findByRole("dialog")).toHaveTextContent("Formularz CV klienta · Anna Fikcyjna");
  });

  it("„Wypełnij tabelę” wypełnia tabelę punktową, nie formularz, i otwiera jej okno", async () => {
    const user = userEvent.setup();
    renderDock();
    await screen.findByRole("button", { name: "Wypełnij tabelę" });

    await user.click(screen.getByRole("button", { name: "Wypełnij tabelę" }));

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith(`${formUrl}/fill?kind=score`, null, expect.anything()),
    );
    expect(apiPost).not.toHaveBeenCalledWith(`${formUrl}/fill`, null, expect.anything());
    expect(await screen.findByRole("dialog")).toHaveTextContent("Tabela punktowa · Anna Fikcyjna");
  });

  it("w trakcie wypełniania przycisk mówi „Wypełniam…” i jest wyłączony", async () => {
    let resolveFill: (value: { data: ClientFormView }) => void = () => {};
    apiPost.mockImplementation(
      () => new Promise<{ data: ClientFormView }>((resolve) => (resolveFill = resolve)),
    );
    const user = userEvent.setup();
    renderDock();
    await user.click(await screen.findByRole("button", { name: "Wypełnij formularz" }));

    const row = requirementRow("client_form");
    const busy = await within(row).findByRole("button", { name: /Wypełniam/ });
    expect(busy).toBeDisabled();
    expect(row).toHaveTextContent("zwykle do minuty");
    // Tabela ma własne wypełnienie — jej przycisk zostaje czynny.
    expect(within(requirementRow("client_score")).getByRole("button", { name: "Wypełnij tabelę" })).toBeEnabled();

    resolveFill({ data: FILLED_WITH_GAP("form") });
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("formularz już wypełniony: klik otwiera okno bez ponownego wypełniania", async () => {
    apiGet.mockImplementation((url: string) => {
      if (url.startsWith("/api/pipeline/move-requirements")) return Promise.resolve({ data: REQUIREMENTS });
      if (url === formUrl) return Promise.resolve({ data: FILLED_WITH_GAP("form") });
      if (url === `${formUrl}?kind=score`) return Promise.resolve({ data: clientView("score") });
      return Promise.resolve({ data: { items: [] } });
    });
    const user = userEvent.setup();
    renderDock();
    await user.click(await screen.findByRole("button", { name: "Wypełnij formularz" }));

    expect(await screen.findByRole("dialog")).toHaveTextContent("Formularz CV klienta · Anna Fikcyjna");
    expect(apiPost).not.toHaveBeenCalledWith(expect.stringContaining("/fill"), null, expect.anything());
  });

  it("błąd wypełniania: komunikat, okno się nie otwiera", async () => {
    apiPost.mockRejectedValue(new Error("Model niedostępny"));
    const user = userEvent.setup();
    renderDock();
    await user.click(await screen.findByRole("button", { name: "Wypełnij formularz" }));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(within(requirementRow("client_form")).getByRole("button", { name: "Wypełnij formularz" })).toBeEnabled();
  });
});
