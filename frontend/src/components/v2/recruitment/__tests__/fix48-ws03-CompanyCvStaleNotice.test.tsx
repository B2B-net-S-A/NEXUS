/**
 * Audyt 48 h (13.10.2026), pkt 9: ramka „CV firmowe powstało z poprzedniego
 * CV” znikała po ruchu karty. Ruch zakłada nowy wiersz etapu bez CV, a szkic
 * CV firmowego zostaje na wierszu, na którym powstał — ramka patrzyła tylko na
 * bieżący wiersz. CV ze starego pliku szło do klienta bez ostrzeżenia.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.fn();
const brandedGet = vi.fn();
const originalGet = vi.fn();
const selectGenerated = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => apiGet(...a) },
  candidateStageCvApi: {
    original: { get: (...a: unknown[]) => originalGet(...a) },
    branded: {
      get: (...a: unknown[]) => brandedGet(...a),
      selectGenerated: (...a: unknown[]) => selectGenerated(...a),
    },
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/components/v2/cv-generator/CvGeneratorDialog", () => ({
  CvGeneratorDialog: () => null,
}));

import { CompanyCvStaleNotice, replacedCopy } from "@/components/v2/recruitment/CompanyCvStaleNotice";
import type { CVBrandedState } from "@/lib/api";
import { dockOriginalCv, type DockOriginalCv } from "@/lib/dock-cv-summary";

/** Wiersz etapu ze szkicem (np. „Zweryfikowany”) i bieżący wiersz po ruchu karty. */
const DRAFT_ROW = 900;
const CURRENT_ROW = 901;

function copy(source: string | null, at: string, filename = "Anna_CV.pdf"): DockOriginalCv {
  return dockOriginalCv({
    snapshot: {
      has_snapshot: true,
      original_snapshot_at: at,
      original_cv_filename: filename,
      original_snapshot_source: source,
    },
    snapshotLoading: false,
    profileDocs: undefined,
    profileDocsFailed: false,
  });
}

function snapshotResponse(stageId: number, source: string | null, at: string) {
  return {
    data: {
      candidate_stage_id: stageId,
      candidate_id: 41,
      job_id: 7,
      has_snapshot: true,
      original_cv_filename: "Anna_CV_2026.pdf",
      original_cv_language: "pl",
      original_snapshot_at: at,
      original_snapshot_source: source,
      download_url: null,
    },
  };
}

const draft = {
  candidate_stage_id: DRAFT_ROW,
  status: "draft",
  from_generator: true,
  generated_document_id: 20,
  edit_revision: 3,
  updated_at: "2026-10-13T11:20:00Z",
} as unknown as CVBrandedState;

const emptyCurrentRow = {
  candidate_stage_id: CURRENT_ROW,
  status: "none",
  pair_source_stage_id: DRAFT_ROW,
  edit_revision: 0,
} as unknown as CVBrandedState;

function renderAfterMove(original: DockOriginalCv) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CompanyCvStaleNotice
        stageId={CURRENT_ROW}
        cvStageId={DRAFT_ROW}
        candidateId={41}
        candidateName="Anna Nowak"
        jobId={7}
        branded={emptyCurrentRow}
        original={original}
      />
    </QueryClientProvider>,
  );
  return client;
}

describe("replacedCopy — która kopia CV mówi o podmianie", () => {
  it("bierze najpóźniej podmienioną ręcznie kopię z obu wierszy", () => {
    const upload = copy("manual_upload", "2026-10-13T13:10:00Z");
    const atMove = copy("auto_create", "2026-10-13T14:00:00Z");
    const refreshed = copy("manual_refresh", "2026-10-13T15:00:00Z");

    expect(replacedCopy(atMove, upload)).toBe(upload);
    expect(replacedCopy(upload, refreshed)).toBe(refreshed);
  });

  it("bez ręcznej podmiany zostaje kopia bieżącego wiersza", () => {
    const atMove = copy("auto_create", "2026-10-13T14:00:00Z");
    const atAdd = copy(null, "2026-10-01T09:00:00Z");

    expect(replacedCopy(atMove, atAdd)).toBe(atMove);
  });
});

describe("CompanyCvStaleNotice — szkic na innym wierszu etapu pary", () => {
  beforeEach(() => {
    apiGet.mockReset();
    brandedGet.mockReset();
    originalGet.mockReset();
    selectGenerated.mockReset();
    window.localStorage.clear();
    brandedGet.mockImplementation((stageId: number) =>
      Promise.resolve({ data: stageId === DRAFT_ROW ? draft : emptyCurrentRow }),
    );
  });

  it("CV wgrane przed ruchem karty: ramka zostaje po ruchu (kopia na wierszu szkicu)", async () => {
    apiGet.mockResolvedValue({ data: [{ id: 20, status: "ready", created_at: "2026-10-13T11:00:00Z" }] });
    originalGet.mockResolvedValue(snapshotResponse(DRAFT_ROW, "manual_upload", "2026-10-13T13:10:00Z"));

    // Bieżący wiersz ma kopię z chwili ruchu — sama w sobie o podmianie nie mówi.
    renderAfterMove(copy("auto_create", "2026-10-13T14:00:00Z"));

    expect(await screen.findByText("CV firmowe powstało z poprzedniego CV.")).toBeInTheDocument();
    expect(brandedGet).toHaveBeenCalledWith(DRAFT_ROW);
    expect(originalGet).toHaveBeenCalledWith(DRAFT_ROW);
  });

  it("CV wgrane po ruchu karty: ramka mimo szkicu na poprzednim wierszu", async () => {
    apiGet.mockResolvedValue({ data: [{ id: 20, status: "ready", created_at: "2026-10-13T11:00:00Z" }] });
    originalGet.mockResolvedValue(snapshotResponse(DRAFT_ROW, null, "2026-10-01T09:00:00Z"));

    renderAfterMove(copy("manual_upload", "2026-10-13T15:00:00Z"));

    expect(await screen.findByText("CV firmowe powstało z poprzedniego CV.")).toBeInTheDocument();
  });

  it("„Użyj nowej wersji” podpina CV na wierszu ze szkicem, z jego rewizją", async () => {
    apiGet.mockResolvedValue({
      data: [
        { id: 31, status: "ready", created_at: "2026-10-13T13:20:00Z" },
        { id: 20, status: "ready", created_at: "2026-10-13T11:00:00Z" },
      ],
    });
    originalGet.mockResolvedValue(snapshotResponse(DRAFT_ROW, "manual_upload", "2026-10-13T13:10:00Z"));
    selectGenerated.mockResolvedValue({ data: { ...draft, generated_document_id: 31 } });
    const user = userEvent.setup();
    renderAfterMove(copy("auto_create", "2026-10-13T14:00:00Z"));

    await user.click(await screen.findByRole("button", { name: "Użyj nowej wersji" }));

    await waitFor(() => expect(selectGenerated).toHaveBeenCalledWith(DRAFT_ROW, 31, 3));
  });

  it("„Zostaw obecne” pamięta wybór przy wierszu ze szkicem — kolejny ruch karty go nie gubi", async () => {
    apiGet.mockResolvedValue({ data: [{ id: 20, status: "ready", created_at: "2026-10-13T11:00:00Z" }] });
    originalGet.mockResolvedValue(snapshotResponse(DRAFT_ROW, "manual_upload", "2026-10-13T13:10:00Z"));
    const user = userEvent.setup();
    renderAfterMove(copy("auto_create", "2026-10-13T14:00:00Z"));

    await user.click(await screen.findByRole("button", { name: "Zostaw obecne" }));

    expect(screen.queryByTestId("company-cv-stale")).toBeNull();
    expect(window.localStorage.getItem(`nexus:company-cv-stale-dismissed:${DRAFT_ROW}`)).toBe(
      "2026-10-13T13:10:00Z",
    );
  });

  it("zwykły ruch karty bez nowego CV — bez ramki", async () => {
    apiGet.mockResolvedValue({ data: [{ id: 20, status: "ready", created_at: "2026-10-13T11:00:00Z" }] });
    originalGet.mockResolvedValue(snapshotResponse(DRAFT_ROW, null, "2026-10-01T09:00:00Z"));

    renderAfterMove(copy("auto_create", "2026-10-13T14:00:00Z"));

    await waitFor(() => expect(originalGet).toHaveBeenCalledWith(DRAFT_ROW));
    await waitFor(() => expect(brandedGet).toHaveBeenCalledWith(DRAFT_ROW));
    expect(screen.queryByTestId("company-cv-stale")).toBeNull();
  });
});
