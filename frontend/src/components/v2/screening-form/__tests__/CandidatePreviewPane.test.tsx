/**
 * Podgląd obok formularza screeningu (0424, D3): zakładki CV / Wymagania /
 * Po ludzku, przełącznik „CV oryginalne / CV firmowe / Inne pliki”, klik
 * w technologię szuka jej w CV (CV firmowe → oryginał, bo tam jest szukanie).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  original: vi.fn(),
  branded: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => mocks.get(...a) },
  candidateStageCvApi: {
    original: { get: (...a: unknown[]) => mocks.original(...a) },
    branded: { get: (...a: unknown[]) => mocks.branded(...a) },
  },
}));

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: vi.fn() }) }));

vi.mock("@/components/v2/files/FilePreviewModal", () => ({
  FilePreviewContent: ({
    doc,
    searchRequest,
  }: {
    doc: { filename: string };
    searchRequest?: { text: string } | null;
  }) => (
    <div data-testid="file-preview">
      {doc.filename}
      {searchRequest ? ` · szukam: ${searchRequest.text}` : ""}
    </div>
  ),
  downloadDocumentBlob: vi.fn(),
  fetchDocumentBlob: vi.fn(),
}));

vi.mock("@/components/v2/person/StageCvPreview", () => ({
  StageCvPreview: ({ cvStageId }: { cvStageId: number }) => (
    <div data-testid="stage-cv-preview">CV firmowe etapu {cvStageId}</div>
  ),
}));

vi.mock("@/components/champion/JobRequirementsSummary", () => ({
  JobRequirementsSummary: ({ onPickRequirement }: { onPickRequirement?: (name: string) => void }) => (
    <button type="button" onClick={() => onPickRequirement?.("Kafka")}>
      Kafka
    </button>
  ),
}));

vi.mock("@/components/champion/plain/PlainBriefBlock", () => ({
  PlainBriefBlock: () => <p>Jednym zdaniem o roli</p>,
}));
vi.mock("@/components/v2/jobs/DockCallCheatsheet", () => ({
  DockCallCheatsheet: () => <p>Ściąga do rozmowy</p>,
}));

import { CandidatePreviewPane, type PreviewTab } from "../CandidatePreviewPane";

const PROFILE_DOCS = [
  {
    id: 1,
    filename: "Tomasz_Wzorcowy_CV.pdf",
    content_type: "application/pdf",
    size_bytes: 1000,
    document_kind: "cv",
    is_primary: true,
    uploaded_at: "2026-09-01T10:00:00Z",
    external_source: null,
    created_at: "2026-09-01T10:00:00Z",
  },
  {
    id: 2,
    filename: "Tomasz_CV_EN.docx",
    content_type: null,
    size_bytes: 900,
    document_kind: "cv",
    is_primary: false,
    uploaded_at: "2026-08-01T10:00:00Z",
    external_source: null,
    created_at: "2026-08-01T10:00:00Z",
  },
];

function Host({ stageId = 901 }: { stageId?: number | null }) {
  const [tab, setTab] = useState<PreviewTab>("cv");
  return (
    <CandidatePreviewPane candidateId={101} jobId={201} stageId={stageId} tab={tab} onTabChange={setTab} />
  );
}

function mount(stageId: number | null = 901) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <Host stageId={stageId} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.original.mockReset();
  mocks.branded.mockReset();
  mocks.get.mockResolvedValue({ data: PROFILE_DOCS });
  mocks.original.mockResolvedValue({
    data: { has_snapshot: true, original_cv_filename: "CV_ze_zgloszenia.pdf", original_snapshot_at: "2026-10-01T08:00:00Z" },
  });
  mocks.branded.mockResolvedValue({ data: { status: "draft", from_generator: true } });
});

describe("CandidatePreviewPane", () => {
  it("domyślnie pokazuje oryginał CV ze zgłoszenia", async () => {
    mount();
    expect(await screen.findByTestId("file-preview")).toHaveTextContent("CV_ze_zgloszenia.pdf");
    expect(screen.getByRole("button", { name: "CV oryginalne" })).toHaveAttribute("aria-pressed", "true");
  });

  it("bez kopii ze zgłoszenia oryginałem jest główne CV z profilu", async () => {
    mocks.original.mockResolvedValue({ data: { has_snapshot: false } });
    mount();
    expect(await screen.findByTestId("file-preview")).toHaveTextContent("Tomasz_Wzorcowy_CV.pdf");
  });

  it("przełącznik: CV firmowe i inne pliki", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByTestId("file-preview");

    await user.click(screen.getByRole("button", { name: "CV firmowe" }));
    expect(await screen.findByTestId("stage-cv-preview")).toHaveTextContent("CV firmowe etapu 901");
    expect(screen.getByRole("button", { name: "CV firmowe" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "Inne pliki (2)" }));
    const list = screen.getByRole("list", { name: "Pliki CV kandydata" });
    expect(within(list).getAllByRole("button")).toHaveLength(2);
    expect(screen.getByTestId("file-preview")).toHaveTextContent("Tomasz_Wzorcowy_CV.pdf");
    await user.click(within(list).getByRole("button", { name: /Tomasz_CV_EN\.docx/ }));
    expect(screen.getByTestId("file-preview")).toHaveTextContent("Tomasz_CV_EN.docx");
  });

  it("CV firmowe, którego jeszcze nie ma, mówi kiedy powstanie", async () => {
    mocks.branded.mockResolvedValue({ data: { status: "none" } });
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: "CV firmowe" }));
    expect(await screen.findByText(/CV firmowe jeszcze nie powstało/)).toBeInTheDocument();
  });

  it("klik w technologię w „Wymaganiach” wraca do CV i szuka jej w oryginale", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByTestId("file-preview");
    await user.click(screen.getByRole("button", { name: "CV firmowe" }));
    await screen.findByTestId("stage-cv-preview");

    await user.click(screen.getByRole("tab", { name: "Wymagania" }));
    await user.click(screen.getByRole("button", { name: "Kafka" }));

    expect(screen.getByRole("tab", { name: "CV" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "CV oryginalne" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("file-preview")).toHaveTextContent("szukam: Kafka");
  });

  it("„Po ludzku” pokazuje skrót roli i ściągę; odwiedzone CV zostaje zamontowane", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByTestId("file-preview");
    await user.click(screen.getByRole("tab", { name: "Po ludzku" }));
    expect(screen.getByText("Jednym zdaniem o roli")).toBeVisible();
    expect(screen.getByText("Ściąga do rozmowy")).toBeVisible();
    // Podgląd CV nie pobiera pliku drugi raz po powrocie.
    expect(screen.getByTestId("file-preview")).not.toBeVisible();
    expect(mocks.original).toHaveBeenCalledTimes(1);
  });

  it("brak CV w zgłoszeniu i w profilu prowadzi do profilu", async () => {
    mocks.original.mockResolvedValue({ data: { has_snapshot: false } });
    mocks.get.mockResolvedValue({ data: [] });
    mount();
    expect(await screen.findByText("Kandydat nie ma CV ani w zgłoszeniu, ani w profilu.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Dodaj CV w profilu kandydata/ })).toHaveAttribute(
      "href",
      "/candidates/101?tab=documents",
    );
  });
});
