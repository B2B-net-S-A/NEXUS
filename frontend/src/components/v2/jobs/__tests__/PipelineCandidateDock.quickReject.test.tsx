/**
 * Wiersz „Odrzuć:” pod rzędem akcji panelu osoby (decyzja Artura 23.11.2026):
 * trzy najczęstsze powody osoby, klik = odrzucenie z tym powodem. Dok tylko
 * renderuje chipy i oddaje wybór — ruch, „Cofnij” i przejście dalej liczy
 * Tablica (`KanbanBoardV2`, `usePipelineMove.deferReject`).
 * Mocki jak w `PipelineCandidateDock.test.tsx`.
 */
import { useContext, type ComponentProps, type ReactNode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// 09.10.2026: sekcja „Screening” czyta stan formularza pary
// (`GET /api/screening-form`), nie arkusz etapu.
const formGet = vi.fn();
const originalGet = vi.fn();
const brandedGet = vi.fn();
const candidatesGet = vi.fn();
const apiGet = vi.fn();
const apiPost = vi.fn();

// `next/dynamic` (`CVBrandedEditModal`) — precedens z `app/settings/page.test.tsx`:
// mockujemy sam `next/dynamic`, żeby dynamicznie importowany moduł nigdy nie
// próbował się realnie rozwiązać w jsdom.
vi.mock("next/dynamic", () => ({ default: () => () => null }));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (url: string, ...rest: unknown[]) =>
      url === "/api/screening-form" ? formGet(url, ...rest) : apiGet(url, ...rest),
    post: (...a: unknown[]) => apiPost(...a),
  },
  candidatesApi: {
    get: (...a: unknown[]) => candidatesGet(...a),
  },
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

// Modale CV/email mają WŁASNE zapytania (inne endpointy) — dok tylko je
// otwiera/zamyka, więc dla testów doku wystarczy pusty stub.
// „Ściąga do rozmowy” ma własne zapytanie (wyjaśnienie „po ludzku”) i testy.
vi.mock("@/components/v2/jobs/DockCallCheatsheet", () => ({
  DockCallCheatsheet: () => null,
}));
vi.mock("@/components/v2/modals/QuickAssignV2", () => ({
  QuickAssignV2: ({ candidateName }: { candidateName: string }) => (
    <h2>Przypisz do rekrutacji — {candidateName}</h2>
  ),
}));
vi.mock("@/components/v2/modals/CVOriginalPreviewModal", () => ({
  CVOriginalPreviewModal: () => null,
}));
vi.mock("@/components/v2/modals/CVShareLinkModal", () => ({
  CVShareLinkModal: () => null,
}));
const composeDialog = vi.fn();
vi.mock("@/components/emails/EmailCompose", () => ({
  default: (props: Record<string, unknown>) => {
    composeDialog(props);
    return <div data-testid="m365-compose-dialog" />;
  },
}));
// Okno generatora CV (v3) — dok tylko je otwiera z osobą i rekrutacją.
const generatorDialog = vi.fn();
vi.mock("@/components/v2/cv-generator/CvGeneratorDialog", () => ({
  CvGeneratorDialog: (props: Record<string, unknown>) => {
    generatorDialog(props);
    return <div data-testid="cv-generator-dialog" />;
  },
}));
// `DopasowanieTab` woła `matchScoringApi` — niepowiązane z tym, co testujemy;
// stub żeby nie trzeba było mockować jeszcze jednego modułu API.
vi.mock("@/components/v2/pages/DopasowanieTab", () => ({
  DopasowanieTab: () => <div data-testid="dopasowanie-tab-stub" />,
}));

// Okna akcji z ramki „Następny etap” — dok tylko je otwiera ze stageId.
const qcDialog = vi.fn();
vi.mock("@/components/v2/recruitment/CvQcDialog", () => ({
  CvQcDialog: (props: Record<string, unknown>) => {
    qcDialog(props);
    return <div data-testid="cv-qc-dialog" />;
  },
}));
vi.mock("@/components/v2/recruitment/DebriefRequiredDialog", () => ({
  DebriefRequiredDialog: () => <div data-testid="debrief-dialog" />,
}));

// „Pobierz Word / PDF” w sekcji CV (D1, 14.10.2026) — plik CV etapu i zapis na dysk.
const stageCvFile = vi.fn();
const stageCvPdf = vi.fn();
vi.mock("@/lib/stage-cv-file", () => ({
  fetchStageCvFile: (...a: unknown[]) => stageCvFile(...a),
  fetchStageCvPdf: (...a: unknown[]) => stageCvPdf(...a),
}));
const savedFiles = vi.fn();
vi.mock("@/lib/authenticated-files", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/authenticated-files")>()),
  downloadBlob: (...a: unknown[]) => savedFiles(...a),
}));

import type { QcStateView } from "@/lib/cv-qc";
import { PipelineCandidateDock, nowSectionForStage, earlyQcSentence } from "@/components/v2/jobs/PipelineCandidateDock";
import { PersonPanelColumn, PersonPanelSideProvider } from "@/components/v2/person/PersonPanelSide";
import { TooltipProvider } from "@/components/ui/tooltip";
import { WorkbenchBelowTabsContext } from "@/components/v2/person/WorkbenchBelowTabs";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";
import type { ScreeningFormState } from "@/lib/api/screeningForm";
import { createNoteFillChannel, type NoteFillReceiver } from "@/lib/note-fill-channel";
import { useAuthStore } from "@/store/auth";
import type { QuickRejectChip } from "@/lib/quick-reject";

/** Stan formularza screeningu pary z doku (kandydat 42, rekrutacja 10, wiersz etapu 501). */
function dockForm(overrides: Partial<ScreeningFormState> = {}): ScreeningFormState {
  return formState({ candidate_id: 42, job_id: 10, stage_id: 501, ...overrides });
}

function baseItem(overrides: Partial<KanbanItem> = {}): KanbanItem {
  return {
    id: 501,
    candidate_id: 42,
    // Etap u klienta → sekcja „Teraz" to „W procesie" (oś czasu i warunki).
    stage: "cv_sent",
    name: "Anna",
    lastname: "Kowalska",
    days_in_stage: 3,
    verification_status: "active",
    ...overrides,
  };
}

function stageCol(
  stage: string,
  name: string,
  overrides: Partial<KanbanColumn> = {}
): KanbanColumn {
  return {
    stage,
    name,
    category: "internal",
    count: 0,
    items: [],
    stage_def_id: null,
    ...overrides,
  };
}

type DockProps = ComponentProps<typeof PipelineCandidateDock>;

let lastQueryClient: QueryClient | null = null;

function renderDock(overrides: Partial<DockProps> = {}, wrap: (dock: ReactNode) => ReactNode = (dock) => dock) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  lastQueryClient = qc;
  const props: DockProps = {
    item: baseItem(),
    jobId: 10,
    currentStageLabel: "Nowi / Analiza CV",
    moveTargets: [],
    readOnly: false,
    contactFeatureEnabled: false,
    canReject: true,
    onClose: vi.fn(),
    onMoveTo: vi.fn(),
    onOpenScreening: vi.fn(),
    onReject: vi.fn(),
    ...overrides,
  };
  render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>{wrap(<PipelineCandidateDock {...props} />)}</TooltipProvider>
    </QueryClientProvider>
  );
  return props;
}

describe("PipelineCandidateDock — „Odrzuć:” jednym kliknięciem (23.11.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    formGet.mockResolvedValue({ data: dockForm() });
    originalGet.mockResolvedValue({
      data: {
        candidate_stage_id: 501,
        candidate_id: 42,
        job_id: 10,
        has_snapshot: false,
        original_cv_filename: null,
        original_cv_language: null,
        original_snapshot_at: null,
        original_snapshot_source: null,
        download_url: null,
      },
    });
    brandedGet.mockResolvedValue({
      data: {
        candidate_stage_id: 501,
        status: "none",
        content_html: null,
        template: null,
        language: null,
        updated_at: null,
        updated_by: null,
        updated_by_name: null,
        finalized_at: null,
        finalized_by: null,
        finalized_by_name: null,
        snapshot_filename: null,
        rendered_from_default: false,
      },
    });
    candidatesGet.mockResolvedValue({ data: { email: "anna@example.com" } });
    apiGet.mockResolvedValue({ data: { items: [] } });
    apiPost.mockResolvedValue({ data: {} });
  });

  const chips: QuickRejectChip[] = [
    { key: "missing_skill", label: "Brak kluczowej umiejętności", opensWindow: false, source: "mine" },
    { key: "too_junior", label: "Za mało doświadczenia", opensWindow: false, source: "mine" },
    { key: "too_expensive", label: "Za droga", opensWindow: true, source: "team" },
  ];

  it("stoi pod rzędem akcji i oddaje kliknięty powód", async () => {
    const onPick = vi.fn();
    renderDock({ item: baseItem({ stage: "new" }), quickReject: { chips, onPick } });
    const row = screen.getByRole("group", { name: "Odrzuć jednym kliknięciem" });
    expect(within(row).getByText("Odrzuć:")).toBeTruthy();
    await userEvent.click(within(row).getByRole("button", { name: "Za mało doświadczenia" }));
    expect(onPick).toHaveBeenCalledWith(chips[1]);
  });

  it("dwuklik odrzuca jedną osobę — drugie kliknięcie (już na chipie następnej) jest pomijane", () => {
    const onPick = vi.fn();
    renderDock({ item: baseItem({ stage: "new" }), quickReject: { chips, onPick } });
    const chip = screen.getByRole("button", { name: "Brak kluczowej umiejętności" });
    fireEvent.click(chip, { detail: 1 });
    fireEvent.click(chip, { detail: 2 });
    expect(onPick).toHaveBeenCalledTimes(1);
  });

  it("„Za droga” ma wielokropek, bo otwiera okno z pytaniem o stawkę", () => {
    renderDock({ item: baseItem({ stage: "new" }), quickReject: { chips, onPick: vi.fn() } });
    const button = screen.getByRole("button", { name: "Za droga…" });
    expect(button.getAttribute("title")).toMatch(/otworzy okno/);
  });

  it("bez prawa odrzucania, przy bramce i tylko do odczytu wiersza nie ma", () => {
    renderDock({ canReject: false, quickReject: { chips, onPick: vi.fn() } });
    expect(screen.queryByTestId("dock-quick-reject")).toBeNull();
    cleanup();
    renderDock({ rejectBlockedReason: "Tablica tylko do odczytu", quickReject: { chips, onPick: vi.fn() } });
    expect(screen.queryByTestId("dock-quick-reject")).toBeNull();
    cleanup();
    renderDock({ readOnly: true, quickReject: { chips, onPick: vi.fn() } });
    expect(screen.queryByTestId("dock-quick-reject")).toBeNull();
  });

  it("bez powodów (awaria albo brak danych) wiersza nie ma, „Odrzuć z powodem” zostaje", () => {
    renderDock({ quickReject: { chips: [], onPick: vi.fn() } });
    expect(screen.queryByTestId("dock-quick-reject")).toBeNull();
    expect(screen.getByRole("button", { name: /Odrzuć z powodem/ })).toBeTruthy();
  });
});
