/**
 * Audyt 48 h (13.10.2026), pkt 9: dok pokazywał ramkę „CV firmowe powstało
 * z poprzedniego CV” tylko przy CV firmowym na BIEŻĄCYM wierszu etapu. Ruch
 * karty zakłada nowy wiersz bez CV, szkic zostaje na poprzednim — ramka
 * znikała, a CV ze starego pliku mogło pójść do klienta bez ostrzeżenia.
 * Sama ramka ma własne testy (`fix48-ws03-CompanyCvStaleNotice.test.tsx`);
 * tu tylko to, czy dok ją pokazuje i na który wiersz ją kieruje.
 */

import type { ComponentProps } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const formGet = vi.fn();
const originalGet = vi.fn();
const brandedGet = vi.fn();
const candidatesGet = vi.fn();
const apiGet = vi.fn();

vi.mock("next/dynamic", () => ({ default: () => () => null }));
vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (url: string, ...rest: unknown[]) =>
      url === "/api/screening-form" ? formGet(url, ...rest) : apiGet(url, ...rest),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
  candidatesApi: { get: (...a: unknown[]) => candidatesGet(...a) },
  candidateStageCvApi: {
    original: { get: (...a: unknown[]) => originalGet(...a) },
    branded: { get: (...a: unknown[]) => brandedGet(...a) },
  },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/components/v2/jobs/DockCallCheatsheet", () => ({ DockCallCheatsheet: () => null }));
vi.mock("@/components/v2/modals/CVOriginalPreviewModal", () => ({ CVOriginalPreviewModal: () => null }));
vi.mock("@/components/v2/modals/CVShareLinkModal", () => ({ CVShareLinkModal: () => null }));
vi.mock("@/components/emails/EmailCompose", () => ({ default: () => null }));
vi.mock("@/components/v2/cv-generator/CvGeneratorDialog", () => ({ CvGeneratorDialog: () => null }));
vi.mock("@/components/v2/pages/DopasowanieTab", () => ({ DopasowanieTab: () => null }));
vi.mock("@/components/v2/recruitment/CvQcDialog", () => ({ CvQcDialog: () => null }));
vi.mock("@/components/v2/recruitment/DebriefRequiredDialog", () => ({ DebriefRequiredDialog: () => null }));

const staleNotice = vi.fn();
vi.mock("@/components/v2/recruitment/CompanyCvStaleNotice", () => ({
  CompanyCvStaleNotice: (props: Record<string, unknown>) => {
    staleNotice(props);
    return <div data-testid="company-cv-stale-stub" />;
  },
}));

import { PipelineCandidateDock } from "@/components/v2/jobs/PipelineCandidateDock";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import { formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";
import { useAuthStore } from "@/store/auth";

/** Bieżący wiersz etapu po ruchu karty; szkic CV firmowego leży na wierszu 500. */
const CURRENT_ROW = 501;
const DRAFT_ROW = 500;

function item(overrides: Partial<KanbanItem> = {}): KanbanItem {
  return {
    id: CURRENT_ROW,
    candidate_id: 42,
    stage: "client_interview",
    name: "Anna",
    lastname: "Kowalska",
    days_in_stage: 1,
    verification_status: "active",
    ...overrides,
  };
}

function renderDock(overrides: Partial<ComponentProps<typeof PipelineCandidateDock>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <PipelineCandidateDock
          item={item()}
          jobId={10}
          currentStageLabel="Rozmowa u klienta"
          moveTargets={[]}
          readOnly={false}
          contactFeatureEnabled={false}
          canReject
          onClose={vi.fn()}
          onMoveTo={vi.fn()}
          onOpenScreening={vi.fn()}
          onReject={vi.fn()}
          {...overrides}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

/**
 * CV firmowe pary na wierszu `stageId`. Od 14.10.2026 dok czyta je tak jak
 * karta „CV do klienta”: bieżący wiersz bez CV wskazuje wiersz pary
 * (`pair_source_stage_id`), a dok czyta stan CV tamtego wiersza.
 */
function pairCv(status: "none" | "draft" | "finalized", stageId: number | null) {
  if (status === "none" || stageId == null || stageId === CURRENT_ROW) return;
  brandedGet.mockImplementation((id: number) =>
    Promise.resolve({
      data:
        id === stageId
          ? { candidate_stage_id: stageId, status, from_generator: true, edit_revision: 2, version: 1 }
          : { candidate_stage_id: CURRENT_ROW, status: "none", pair_source_stage_id: stageId, pair_source_status: status },
    }),
  );
}

async function openCvSection() {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /^CV/ }));
}

describe("PipelineCandidateDock — ramka „CV firmowe z poprzedniego CV” po ruchu karty", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: { id: 7, role: "recruiter", roles: ["recruiter"] } } as never);
    formGet.mockResolvedValue({ data: formState({ candidate_id: 42, job_id: 10, stage_id: CURRENT_ROW }) });
    originalGet.mockResolvedValue({
      data: {
        has_snapshot: true,
        original_snapshot_at: "2026-10-13T14:00:00Z",
        original_cv_filename: "Anna_CV.pdf",
        original_snapshot_source: "auto_create",
      },
    });
    brandedGet.mockResolvedValue({ data: { candidate_stage_id: CURRENT_ROW, status: "none" } });
    candidatesGet.mockResolvedValue({ data: { email: "anna@example.com" } });
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({ data: url.includes("/documents?kind=cv") ? [] : { items: [] } }),
    );
  });

  afterEach(() => {
    useAuthStore.setState({ user: null } as never);
  });

  it("szkic na poprzednim wierszu etapu: ramka dostaje ten wiersz", async () => {
    pairCv("draft", DRAFT_ROW);
    renderDock();
    await openCvSection();

    await screen.findByTestId("company-cv-stale-stub");
    expect(staleNotice).toHaveBeenLastCalledWith(
      expect.objectContaining({ stageId: CURRENT_ROW, cvStageId: DRAFT_ROW, candidateId: 42, jobId: 10 }),
    );
  });

  it("CV firmowe na bieżącym wierszu: ramka dostaje bieżący wiersz", async () => {
    brandedGet.mockResolvedValue({
      data: { candidate_stage_id: CURRENT_ROW, status: "draft", from_generator: true, edit_revision: 1 },
    });
    pairCv("draft", CURRENT_ROW);
    renderDock();
    await openCvSection();

    await screen.findByTestId("company-cv-stale-stub");
    expect(staleNotice).toHaveBeenLastCalledWith(
      expect.objectContaining({ stageId: CURRENT_ROW, cvStageId: CURRENT_ROW }),
    );
  });

  // Pkt 8: plik z kwarantanny tożsamości (CV innej osoby) nie jest „Oryginałem
  // CV z profilu” — kopia etapu jest po kwarantannie pusta, a dok sięgał wtedy
  // po najnowszy plik z profilu, czyli właśnie ten cudzy.
  it("CV z kwarantanny tożsamości nie jest pokazywane jako oryginał z profilu", async () => {
    pairCv("none", null);
    originalGet.mockResolvedValue({ data: { has_snapshot: false } });
    candidatesGet.mockResolvedValue({
      data: {
        email: "anna@example.com",
        cv_filename: null,
        cv_extracted_data: { _identity_quarantine_source: { kind: "document", id: 9 } },
      },
    });
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({
        data: url.includes("/documents?kind=cv")
          ? [
              {
                id: 9,
                filename: "Zofia_Przykladowa_CV.pdf",
                is_primary: false,
                uploaded_at: "2026-10-13T09:00:00Z",
                created_at: "2026-10-13T09:00:00Z",
                document_kind: "cv",
              },
            ]
          : { items: [] },
      }),
    );
    renderDock();
    await openCvSection();

    expect(
      await screen.findByText("Oryginał CV: brak pliku — ani w zgłoszeniu, ani w profilu kandydata"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pokaż CV z profilu/ })).toBeNull();
  });

  it("zatwierdzone CV firmowe na poprzednim wierszu: bez ramki (zatwierdzonego nowe CV nie zmienia)", async () => {
    pairCv("finalized", DRAFT_ROW);
    renderDock();
    await openCvSection();

    await waitFor(() => expect(brandedGet).toHaveBeenCalledWith(DRAFT_ROW));
    await screen.findByText(/CV firmowe: zatwierdzone/);
    expect(screen.queryByTestId("company-cv-stale-stub")).toBeNull();
  });
});
