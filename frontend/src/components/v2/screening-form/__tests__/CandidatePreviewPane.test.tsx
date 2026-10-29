/**
 * Podgląd obok formularza screeningu (0424, D3): zakładki CV / Wymagania /
 * Po ludzku, przełącznik „CV oryginalne / CV firmowe / Inne pliki”, klik
 * w technologię szuka jej w CV, które jest na ekranie (od 23.10.2026 także
 * w CV firmowym); cytat z edytora CV szuka w oryginale.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  original: vi.fn(),
  branded: vi.fn(),
  selectGenerated: vi.fn(),
  selectDocument: vi.fn(),
  selectStageCv: vi.fn(),
  sources: vi.fn(),
  previewMounted: vi.fn(),
  upload: vi.fn(),
  refresh: vi.fn(),
  candidateGet: vi.fn(),
  downloadOriginal: vi.fn(),
  fetchBlob: vi.fn(),
  previewLoader: { current: null as null | ((candidateId: number, docId: number) => Promise<Blob>) },
  downloadDocument: vi.fn(),
  downloadBlob: vi.fn(),
  stageCvFile: vi.fn(),
  stageCvPdf: vi.fn(),
  showError: vi.fn(),
  showActionToast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => mocks.get(...a) },
  candidatesApi: { get: (...a: unknown[]) => mocks.candidateGet(...a) },
  candidateStageCvApi: {
    original: {
      get: (...a: unknown[]) => mocks.original(...a),
      upload: (...a: unknown[]) => mocks.upload(...a),
      refresh: (...a: unknown[]) => mocks.refresh(...a),
    },
    branded: {
      get: (...a: unknown[]) => mocks.branded(...a),
      selectGenerated: (...a: unknown[]) => mocks.selectGenerated(...a),
      selectDocument: (...a: unknown[]) => mocks.selectDocument(...a),
      selectStageCv: (...a: unknown[]) => mocks.selectStageCv(...a),
      sources: (...a: unknown[]) => mocks.sources(...a),
    },
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showError: mocks.showError,
    showSuccess: vi.fn(),
    showInfo: vi.fn(),
    showActionToast: mocks.showActionToast,
  }),
}));

vi.mock("@/lib/authenticated-files", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/authenticated-files")>()),
  downloadAuthenticatedFile: (...a: unknown[]) => mocks.downloadOriginal(...a),
  downloadBlob: (...a: unknown[]) => mocks.downloadBlob(...a),
  fetchAuthenticatedBlob: (...a: unknown[]) => mocks.fetchBlob(...a),
}));

vi.mock("@/lib/stage-cv-file", () => ({
  fetchStageCvFile: (...a: unknown[]) => mocks.stageCvFile(...a),
  fetchStageCvPdf: (...a: unknown[]) => mocks.stageCvPdf(...a),
}));

vi.mock("@/components/v2/modals/CVBrandedEditModal", () => ({
  CVBrandedEditModal: ({ stageId, candidateName }: { stageId: number; candidateName: string }) => (
    <div data-testid="cv-editor">
      Edytor CV etapu {stageId} — {candidateName}
    </div>
  ),
}));

vi.mock("@/components/v2/files/FilePreviewModal", () => ({
  FilePreviewContent: ({
    doc,
    searchRequest,
    loadDocumentBlob,
  }: {
    doc: { filename: string };
    searchRequest?: { text: string } | null;
    loadDocumentBlob?: (candidateId: number, docId: number) => Promise<Blob>;
  }) => {
    mocks.previewLoader.current = loadDocumentBlob ?? null;
    // Każde zamontowanie podglądu to ponowne pobranie pliku w prawdziwym komponencie.
    useEffect(() => {
      mocks.previewMounted();
    }, []);
    return (
      <div data-testid="file-preview">
        {doc.filename}
        {searchRequest ? ` · szukam: ${searchRequest.text}` : ""}
      </div>
    );
  },
  downloadDocumentBlob: (...a: unknown[]) => mocks.downloadDocument(...a),
  fetchDocumentBlob: vi.fn(),
}));

vi.mock("@/components/v2/person/StageCvPreview", () => ({
  StageCvPreview: ({
    cvStageId,
    revision,
    hideDownload,
    searchable,
    searchRequest,
  }: {
    cvStageId: number;
    revision?: number;
    hideDownload?: boolean;
    searchable?: boolean;
    searchRequest?: { text: string } | null;
  }) => (
    <div
      data-testid="stage-cv-preview"
      data-revision={revision}
      data-hide-download={String(hideDownload === true)}
      data-searchable={String(searchable === true)}
    >
      CV firmowe etapu {cvStageId}
      {searchRequest ? ` · szukam: ${searchRequest.text}` : ""}
    </div>
  ),
}));

vi.mock("@/components/champion/JobRequirementsSummary", () => ({
  JobRequirementsSummary: ({ onPickRequirement }: { onPickRequirement?: (name: string) => void }) => (
    <button type="button" onClick={() => onPickRequirement?.("Kafka")}>
      Kafka
    </button>
  ),
}));

// Czytnik historii ma własne testy — tu liczy się, kiedy podgląd go pokazuje.
vi.mock("@/components/v2/person/PersonNotesHistory", () => ({
  PersonNotesHistory: ({ variant, readOnly, jobId }: { variant?: string; readOnly: boolean; jobId: number }) => (
    <div data-testid="person-history">
      historia: {variant} · tylko odczyt: {String(readOnly)} · rekrutacja {jobId}
    </div>
  ),
}));

vi.mock("@/components/champion/JobRequirementsStrip", () => ({
  JobRequirementsStrip: ({
    onPickRequirement,
    onShowAll,
  }: {
    onPickRequirement: (name: string) => void;
    onShowAll: () => void;
  }) => (
    <div data-testid="requirements-strip">
      <button type="button" onClick={() => onPickRequirement("UML")}>
        UML z paska
      </button>
      <button type="button" onClick={onShowAll}>
        Wszystkie wymagania
      </button>
    </div>
  ),
}));

vi.mock("@/components/champion/plain/PlainBriefBlock", () => ({
  PlainBriefBlock: () => <p>Jednym zdaniem o roli</p>,
}));
vi.mock("@/components/v2/jobs/DockCallCheatsheet", () => ({
  DockCallCheatsheet: () => <p>Ściąga do rozmowy</p>,
}));

import {
  PersonPanelColumn,
  PersonPanelSide,
  PersonPanelSideProvider,
  PersonPanelSideSection,
  PersonPanelSideZone,
} from "@/components/v2/person/PersonPanelSide";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { useAuthStore } from "@/store/auth";

import { CandidatePreviewPane, type CandidatePreviewPaneProps, type PreviewTab } from "../CandidatePreviewPane";

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

function Host({ stageId = 901, initialTab = "cv" }: { stageId?: number | null; initialTab?: PreviewTab }) {
  const [tab, setTab] = useState<PreviewTab>(initialTab);
  return (
    <CandidatePreviewPane candidateId={101} jobId={201} stageId={stageId} tab={tab} onTabChange={setTab} />
  );
}

function mount(stageId: number | null = 901, initialTab: PreviewTab = "cv") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <Host stageId={stageId} initialTab={initialTab} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.original.mockReset();
  mocks.branded.mockReset();
  mocks.selectGenerated.mockReset();
  mocks.selectDocument.mockReset();
  mocks.previewMounted.mockReset();
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

  it("klik w technologię przy CV firmowym wraca do CV i szuka jej w CV firmowym", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByTestId("file-preview");
    await user.click(screen.getByRole("button", { name: "CV firmowe" }));
    expect(await screen.findByTestId("stage-cv-preview")).toHaveAttribute("data-searchable", "true");

    await user.click(screen.getByRole("tab", { name: "Wymagania" }));
    await user.click(screen.getByRole("button", { name: "Kafka" }));

    expect(screen.getByRole("tab", { name: "CV" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "CV firmowe" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("stage-cv-preview")).toHaveTextContent("szukam: Kafka");
  });

  it("klik w technologię przy oryginale szuka jej w oryginale", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByTestId("file-preview");

    await user.click(screen.getByRole("tab", { name: "Wymagania" }));
    await user.click(screen.getByRole("button", { name: "Kafka" }));

    expect(screen.getByRole("button", { name: "CV oryginalne" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("file-preview")).toHaveTextContent("szukam: Kafka");
  });

  it("wyszukanie zlecone z zewnątrz (edytor CV: „Pokaż w oryginale”) przełącza na CV i oryginał", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const pane = (search: { text: string; nonce: number } | null) => (
      <QueryClientProvider client={queryClient}>
        <CandidatePreviewPane candidateId={101} jobId={201} stageId={901} defaultTab="requirements" searchRequest={search} />
      </QueryClientProvider>
    );
    const view = render(pane(null));
    expect(screen.getByRole("tab", { name: "Wymagania" })).toHaveAttribute("aria-selected", "true");

    view.rerender(pane({ text: "przelewy natychmiastowe", nonce: 1 }));
    expect(await screen.findByTestId("file-preview")).toHaveTextContent("szukam: przelewy natychmiastowe");
    expect(screen.getByRole("tab", { name: "CV" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "CV oryginalne" })).toHaveAttribute("aria-pressed", "true");

    // Ten sam cytat jeszcze raz (nowy `nonce`) wraca do CV z innej zakładki.
    await userEvent.setup().click(screen.getByRole("tab", { name: "Wymagania" }));
    view.rerender(pane({ text: "przelewy natychmiastowe", nonce: 2 }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "CV" })).toHaveAttribute("aria-selected", "true"));
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

/**
 * Screening, 09.10.2026: rekruter wybiera gotowe CV z profilu kandydata jako
 * CV firmowe rekrutacji, a potem je edytuje. 34 z 50 osób w screeningu miało
 * takie CV jako plik Word „…B2B…”, a podgląd mówił tylko „jeszcze nie powstało”.
 */
describe("CandidatePreviewPane — wybór i edycja CV firmowego (screening)", () => {
  const B2B_DOC = {
    ...PROFILE_DOCS[1],
    id: 3,
    filename: "CV_B2B_Tomasz_Wzorcowy.docx",
    uploaded_by_name: "Anna Wzorcowa",
  };
  const GENERATED = [
    { id: 41, status: "ready", job_id: 300, client_name: "Bank Fikcyjny", position: "DevOps", language: "en", created_at: "2026-09-20T10:00:00Z" },
  ];

  function mountScreening() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <CandidatePreviewPane
          candidateId={101}
          jobId={201}
          stageId={901}
          cvActions={{ candidateName: "Tomasz Wzorcowy" }}
        />
      </QueryClientProvider>,
    );
  }

  beforeEach(() => {
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/cv-generator/generated") return Promise.resolve({ data: GENERATED });
      if (url === "/api/cv-generator/policy") return Promise.resolve({ data: { managed: false } });
      return Promise.resolve({ data: [...PROFILE_DOCS, B2B_DOC] });
    });
    mocks.branded.mockResolvedValue({ data: { status: "none", edit_revision: 0 } });
    mocks.sources.mockResolvedValue({ data: { items: [] } });
  });

  it("CV etapu z innej rekrutacji stoi pierwsze i wypiera generację tej samej rekrutacji (12.10.2026)", async () => {
    // Kopia z generatora gubi ręczne poprawki — CV etapu je niesie.
    mocks.sources.mockResolvedValue({
      data: {
        items: [
          { job_id: 300, stage_id: 31, job_title: "DevOps Engineer", reference_number: "ZOB-9000", status: "finalized", version: 2 },
        ],
      },
    });
    mocks.selectStageCv.mockResolvedValue({
      data: { status: "draft", source: "generator", from_generator: true, edit_revision: 1 },
    });
    const user = userEvent.setup();
    mountScreening();
    await user.click(await screen.findByRole("button", { name: "CV firmowe · wybierz (2)" }));

    const stages = screen.getByRole("region", { name: "Z innych rekrutacji" });
    expect(within(stages).getByText("zatwierdzone · wersja 2")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Z generatora" })).toBeNull();

    await user.click(within(stages).getByRole("button", { name: "Wybierz: DevOps Engineer" }));
    expect(mocks.selectStageCv).toHaveBeenCalledWith(901, 300, 0);
    expect(mocks.selectGenerated).not.toHaveBeenCalled();
  });

  it("bez CV firmowego pokazuje gotowe CV z profilu, a „Wybierz” podpina plik Word", async () => {
    mocks.selectDocument.mockResolvedValue({
      data: { status: "draft", source: "document", from_generator: false, edit_revision: 1 },
    });
    const user = userEvent.setup();
    mountScreening();
    // Przełącznik mówi, że jest z czego wybrać, zanim ktoś otworzy „CV firmowe”.
    await user.click(await screen.findByRole("button", { name: "CV firmowe · wybierz (2)" }));

    const generated = screen.getByRole("region", { name: "Z generatora" });
    expect(within(generated).getByText("DevOps")).toBeInTheDocument();
    expect(within(generated).getByText("inna rekrutacja")).toBeInTheDocument();
    const files = screen.getByRole("region", { name: "Pliki Word z profilu" });
    // Oryginalne CV kandydata i PDF-y nie są „gotowym CV dla klienta”.
    expect(within(files).getAllByRole("listitem")).toHaveLength(1);

    await user.click(within(files).getByRole("button", { name: "Wybierz: CV_B2B_Tomasz_Wzorcowy.docx" }));
    expect(mocks.selectDocument).toHaveBeenCalledWith(901, 3, 0);
    // Po wyborze od razu podgląd z przyciskami — bez potwierdzania i bez pytań.
    expect(await screen.findByTestId("stage-cv-preview")).toHaveAttribute("data-revision", "1");
    expect(screen.getByRole("button", { name: "Edytuj" })).toBeInTheDocument();
    expect(screen.getByText(/Wczytane z pliku Word/)).toBeInTheDocument();
  });

  it("CV z generatora idzie trasą generatora, także z innej rekrutacji", async () => {
    mocks.selectGenerated.mockResolvedValue({
      data: { status: "draft", source: "generator", from_generator: true, edit_revision: 1 },
    });
    const user = userEvent.setup();
    mountScreening();
    await user.click(await screen.findByRole("button", { name: /CV firmowe · wybierz/ }));
    await user.click(screen.getByRole("button", { name: "Wybierz: DevOps" }));
    expect(mocks.selectGenerated).toHaveBeenCalledWith(901, 41, 0);
    expect(mocks.selectDocument).not.toHaveBeenCalled();
  });

  it("„Podgląd” pliku pokazuje go w „Innych plikach”", async () => {
    const user = userEvent.setup();
    mountScreening();
    await user.click(await screen.findByRole("button", { name: /CV firmowe · wybierz/ }));
    await user.click(screen.getByRole("button", { name: "Podgląd" }));
    expect(screen.getByRole("button", { name: "Inne pliki (3)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("file-preview")).toHaveTextContent("CV_B2B_Tomasz_Wzorcowy.docx");
  });

  it("istniejące CV: „Edytuj” otwiera edytor etapu, na którym leży CV pary", async () => {
    mocks.branded.mockImplementation((stageId: number) =>
      Promise.resolve({
        data:
          stageId === 901
            ? { status: "none", edit_revision: 0, pair_source_stage_id: 880, pair_source_status: "draft" }
            : { status: "draft", from_generator: true, source: "generator", edit_revision: 4 },
      }),
    );
    const user = userEvent.setup();
    mountScreening();
    await user.click(await screen.findByRole("button", { name: "CV firmowe" }));
    expect(await screen.findByTestId("stage-cv-preview")).toHaveTextContent("CV firmowe etapu 880");
    await user.click(screen.getByRole("button", { name: "Edytuj" }));
    expect(await screen.findByTestId("cv-editor")).toHaveTextContent("Edytor CV etapu 880 — Tomasz Wzorcowy");
  });

  it("„Zmień CV” pyta przed zastąpieniem szkicu i wysyła bieżącą rewizję", async () => {
    mocks.branded.mockResolvedValue({
      data: { status: "draft", from_generator: true, source: "generator", edit_revision: 7 },
    });
    mocks.selectDocument.mockResolvedValue({
      data: { status: "draft", source: "document", from_generator: false, edit_revision: 8 },
    });
    const user = userEvent.setup();
    mountScreening();
    await user.click(await screen.findByRole("button", { name: "CV firmowe" }));
    await user.click(await screen.findByRole("button", { name: "Zmień CV" }));
    await user.click(screen.getByRole("button", { name: "Wybierz: CV_B2B_Tomasz_Wzorcowy.docx" }));
    expect(mocks.selectDocument).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Zastąpić CV firmowe?")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Zastąp" }));
    expect(mocks.selectDocument).toHaveBeenCalledWith(901, 3, 7);
    expect(await screen.findByTestId("stage-cv-preview")).toHaveAttribute("data-revision", "8");
  });

  it("etap bez wiersza CV (404) też pozwala wybrać — z rewizją 0", async () => {
    mocks.branded.mockRejectedValue({ response: { status: 404 } });
    mocks.selectGenerated.mockResolvedValue({
      data: { status: "draft", source: "generator", from_generator: true, edit_revision: 1 },
    });
    const user = userEvent.setup();
    mountScreening();
    await user.click(await screen.findByRole("button", { name: /CV firmowe · wybierz/ }));
    await user.click(screen.getByRole("button", { name: "Wybierz: DevOps" }));
    expect(mocks.selectGenerated).toHaveBeenCalledWith(901, 41, 0);
  });

  it("bez gotowych CV w profilu zostaje zdanie o generacji po „Zweryfikowany”", async () => {
    mocks.get.mockImplementation((url: string) =>
      Promise.resolve({ data: url === "/api/cv-generator/generated" ? [] : url === "/api/cv-generator/policy" ? {} : PROFILE_DOCS }),
    );
    const user = userEvent.setup();
    mountScreening();
    await user.click(await screen.findByRole("button", { name: "CV firmowe" }));
    expect(await screen.findByText(/CV firmowe jeszcze nie powstało/)).toBeInTheDocument();
    expect(screen.queryByTestId("stage-cv-picker")).not.toBeInTheDocument();
  });

  it("podgląd bez `cvActions` (przegląd DL, Rozmowy) nie ma listy ani przycisków", async () => {
    mocks.branded.mockResolvedValue({ data: { status: "draft", from_generator: true, edit_revision: 2 } });
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: "CV firmowe" }));
    await screen.findByTestId("stage-cv-preview");
    expect(screen.queryByRole("button", { name: "Edytuj" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zmień CV" })).not.toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalledWith("/api/cv-generator/generated", expect.anything());
  });
});

/**
 * Tryb dwóch podglądów (strefa od 1150 px) liczy się z szerokości elementu.
 * jsdom nie liczy układu, więc szerokość i `ResizeObserver` są tu atrapami.
 */
describe("CandidatePreviewPane — dwa podglądy naraz", () => {
  let width = 0;
  let observers: Array<() => void> = [];

  function resizeTo(next: number) {
    width = next;
    act(() => observers.forEach((notify) => notify()));
  }

  beforeEach(() => {
    width = 1200;
    observers = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          observers.push(callback);
        }
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    vi.spyOn(Element.prototype, "clientWidth", "get").mockImplementation(() => width);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("w szerokiej strefie CV i wymagania stoją obok siebie, bez paska zakładek", async () => {
    mount(901, "requirements");
    expect(await screen.findByTestId("file-preview")).toBeVisible();
    expect(screen.getByTestId("candidate-preview-pane")).toHaveAttribute("data-dual", "true");
    expect(screen.getByRole("region", { name: "Wymagania" })).toBeVisible();
    expect(screen.getByRole("region", { name: "Po ludzku" })).toBeVisible();
    expect(screen.queryByRole("tab", { name: "CV" })).not.toBeInTheDocument();
  });

  it("ukrycie strefy (szerokość 0) nie odmontowuje CV — plik nie pobiera się drugi raz", async () => {
    // Zwinięcie panelu, zakładka „Notatki” albo inna sekcja chowają strefę
    // przez `display: none`; element ma wtedy szerokość 0.
    mount(901, "requirements");
    await screen.findByTestId("file-preview");
    expect(mocks.previewMounted).toHaveBeenCalledTimes(1);

    resizeTo(0);
    expect(screen.getByTestId("file-preview")).toBeInTheDocument();
    expect(screen.getByTestId("candidate-preview-pane")).toHaveAttribute("data-dual", "true");

    resizeTo(1200);
    expect(screen.getByTestId("file-preview")).toBeVisible();
    expect(mocks.previewMounted).toHaveBeenCalledTimes(1);
  });

  it("zwężenie okna wraca do zakładek, a CV zostaje zamontowane w tle", async () => {
    mount(901, "requirements");
    await screen.findByTestId("file-preview");

    resizeTo(900);
    expect(screen.getByTestId("candidate-preview-pane")).not.toHaveAttribute("data-dual");
    expect(screen.getByRole("tab", { name: "Wymagania" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("file-preview")).not.toBeVisible();

    resizeTo(1200);
    expect(mocks.previewMounted).toHaveBeenCalledTimes(1);
  });
});

describe("CandidatePreviewPane — „Historia osoby” obok źródeł CV (12.10.2026)", () => {
  const NOTES = {
    items: [
      { id: 1, job_id: 201, content: "Umówiony telefon.", created_at: "2026-10-12T08:00:00Z", group: "talks" },
      { id: 2, job_id: 7, content: "Feedback klienta.", created_at: "2025-04-02T09:40:00Z", group: "talks" },
      { id: 3, job_id: 7, content: "Auto-match 70/100.", is_system: true, group: "automat", created_at: "2025-03-01T00:00:00Z" },
    ],
  };
  const withNotes = () =>
    mocks.get.mockImplementation((url: string) =>
      Promise.resolve({ data: String(url).startsWith("/api/notes") ? NOTES : PROFILE_DOCS }),
    );
  const notesCalls = () => mocks.get.mock.calls.filter(([url]) => String(url).startsWith("/api/notes")).length;

  it("osoba bez notatek nie dostaje przycisku historii", async () => {
    mocks.get.mockImplementation((url: string) =>
      Promise.resolve({ data: String(url).startsWith("/api/notes") ? { items: [] } : PROFILE_DOCS }),
    );
    mount();
    await screen.findByTestId("file-preview");
    // Odpowiedź o notatkach już przyszła — brak przycisku to decyzja, nie wyścig.
    await waitFor(() => expect(notesCalls()).toBe(1));
    await act(async () => {});
    expect(screen.queryByRole("button", { name: /Historia osoby/ })).toBeNull();
  });

  it("awaria odczytu notatek zostawia przycisk — czytnik pokaże błąd, nie „brak historii”", async () => {
    mocks.get.mockImplementation((url: string) =>
      String(url).startsWith("/api/notes") ? Promise.reject(new Error("500")) : Promise.resolve({ data: PROFILE_DOCS }),
    );
    const user = userEvent.setup();
    mount();
    await screen.findByTestId("file-preview");
    const toggle = await screen.findByRole("button", { name: "Historia osoby" });
    await user.click(toggle);
    expect(screen.getByTestId("person-history")).toBeVisible();
  });

  it("otwarcie historii chowa CV bez odmontowania — powrót nie pobiera pliku drugi raz", async () => {
    withNotes();
    const user = userEvent.setup();
    mount();
    await screen.findByTestId("file-preview");
    // Licznik to notatki ludzi; wpis automatu się nie liczy.
    const toggle = await screen.findByRole("button", { name: "Historia osoby (2)" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    // Treść historii powstaje dopiero przy pierwszym otwarciu.
    expect(screen.queryByTestId("person-history")).toBeNull();

    await user.click(toggle);
    expect(screen.getByRole("region", { name: "Historia osoby" })).toBeVisible();
    expect(screen.getByTestId("person-history")).toHaveTextContent("historia: reader · tylko odczyt: true · rekrutacja 201");
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "CV oryginalne" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("file-preview")).not.toBeVisible();

    await user.click(screen.getByRole("button", { name: "CV oryginalne" }));
    expect(screen.getByTestId("file-preview")).toBeVisible();
    expect(screen.getByTestId("person-history")).not.toBeVisible();
    expect(screen.getByRole("button", { name: "CV oryginalne" })).toHaveAttribute("aria-pressed", "true");
    expect(mocks.previewMounted).toHaveBeenCalledTimes(1);
    expect(mocks.original).toHaveBeenCalledTimes(1);
  });

  it("„Szukaj w CV” przy wymaganiu zamyka historię i wraca do CV", async () => {
    withNotes();
    const user = userEvent.setup();
    mount();
    await screen.findByTestId("file-preview");
    await user.click(await screen.findByRole("button", { name: "Historia osoby (2)" }));
    expect(screen.getByTestId("file-preview")).not.toBeVisible();

    await user.click(screen.getByRole("tab", { name: "Wymagania" }));
    await user.click(screen.getByRole("button", { name: "Kafka" }));

    expect(screen.getByTestId("file-preview")).toBeVisible();
    expect(screen.getByTestId("file-preview")).toHaveTextContent("szukam: Kafka");
    expect(screen.getByRole("button", { name: "Historia osoby (2)" })).toHaveAttribute("aria-pressed", "false");
    expect(mocks.previewMounted).toHaveBeenCalledTimes(1);
  });

  it("`showHistory={false}` (edytor CV): bez przycisku i bez pytania o notatki", async () => {
    withNotes();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <CandidatePreviewPane candidateId={101} jobId={201} stageId={901} showHistory={false} />
      </QueryClientProvider>,
    );
    await screen.findByTestId("file-preview");
    expect(screen.queryByRole("button", { name: /Historia osoby/ })).toBeNull();
    expect(notesCalls()).toBe(0);
  });

  it("historia sterowana z zewnątrz otwiera się bez kliknięcia w podglądzie", async () => {
    withNotes();
    function Controlled() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Pokaż historię
          </button>
          <CandidatePreviewPane
            candidateId={101}
            jobId={201}
            stageId={901}
            historyOpen={open}
            onHistoryOpenChange={setOpen}
          />
        </>
      );
    }
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <Controlled />
      </QueryClientProvider>,
    );
    await screen.findByRole("button", { name: "Historia osoby (2)" });
    await user.click(screen.getByRole("button", { name: "Pokaż historię" }));
    expect(screen.getByRole("region", { name: "Historia osoby" })).toBeVisible();
    // Wybór źródła CV oddaje stan wołającemu.
    await user.click(screen.getByRole("button", { name: "CV oryginalne" }));
    expect(screen.getByTestId("person-history")).not.toBeVisible();
  });
});

/**
 * Zwijanie CV i wymagań w powłoce panelu (13.10.2026, D1–D4). jsdom ma
 * szerokość 0, więc bez atrapy szerokości podgląd jest w zakładkach — jak na
 * laptopie 1280 × 720.
 */
describe("CandidatePreviewPane — zwijanie CV i wymagań", () => {
  const originalMatchMedia = window.matchMedia;

  beforeEach(() => {
    window.localStorage.clear();
    useAuthStore.setState({ user: { id: 7 } as never, hydrated: true });
    window.matchMedia = ((query: string) => ({
      matches: true,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })) as unknown as typeof window.matchMedia;
  });

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
    useAuthStore.setState({ user: null });
  });

  function mountInPanel({ initialTab = "cv", collapsible = true }: { initialTab?: PreviewTab; collapsible?: boolean } = {}) {
    function PanelHost() {
      const [tab, setTab] = useState<PreviewTab>(initialTab);
      return (
        <PersonPanelSideProvider>
          <PersonPanelSideZone />
          <PersonPanelColumn split>
            <p>panel osoby</p>
          </PersonPanelColumn>
          <PersonPanelSide>
            <CandidatePreviewPane
              candidateId={101}
              jobId={201}
              stageId={901}
              tab={tab}
              onTabChange={setTab}
              collapsible={collapsible}
            />
          </PersonPanelSide>
        </PersonPanelSideProvider>
      );
    }
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <PanelHost />
      </QueryClientProvider>,
    );
  }

  it("bez `collapsible` (edytor CV, przegląd DL) nie ma zwijania ani paska wymagań", async () => {
    mountInPanel({ collapsible: false });
    await screen.findByTestId("file-preview");
    expect(screen.queryByRole("button", { name: "Zwiń CV" })).toBeNull();
    expect(screen.queryByTestId("requirements-strip")).toBeNull();
    await userEvent.setup().click(screen.getByRole("tab", { name: "Wymagania" }));
    expect(screen.queryByRole("button", { name: "Zwiń wymagania" })).toBeNull();
  });

  it("w zakładkach (laptop) pasek wymagań stoi nad CV, a „Wszystkie wymagania” przełącza zakładkę (D3)", async () => {
    const user = userEvent.setup();
    mountInPanel();
    await screen.findByTestId("file-preview");
    expect(screen.getByTestId("requirements-strip")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Wszystkie wymagania" }));
    expect(screen.getByRole("tab", { name: "Wymagania" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByTestId("requirements-strip")).toBeNull();
  });

  it("zwinięte CV: listwa, wymagania i „Po ludzku” naraz bez zakładek, panel na pół; rozwinięcie nie pobiera CV drugi raz", async () => {
    const user = userEvent.setup();
    mountInPanel();
    await screen.findByTestId("file-preview");
    expect(mocks.previewMounted).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Zwiń CV" }));
    expect(screen.getByTestId("file-preview")).not.toBeVisible();
    expect(screen.getByRole("button", { name: "Rozwiń CV" })).toBeVisible();
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.getByRole("region", { name: "Wymagania" })).toBeVisible();
    expect(screen.getByRole("region", { name: "Po ludzku" })).toBeVisible();
    expect(screen.getByTestId("candidate-preview-pane")).toHaveAttribute("data-cv-collapsed", "true");
    expect(screen.getByTestId("person-panel-column").className).toContain("lg:w-[calc((100%-2.75rem)/2)]");

    await user.click(screen.getByRole("button", { name: "Rozwiń CV" }));
    expect(screen.getByTestId("file-preview")).toBeVisible();
    expect(screen.getByRole("tab", { name: "CV" })).toHaveAttribute("aria-selected", "true");
    expect(mocks.previewMounted).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("person-panel-column").className).toContain("lg:w-[460px]");
  });

  it("„Szukaj w CV” przy zwiniętym CV rozwija je i szuka", async () => {
    const user = userEvent.setup();
    mountInPanel();
    await screen.findByTestId("file-preview");
    await user.click(screen.getByRole("button", { name: "Zwiń CV" }));

    await user.click(screen.getByRole("button", { name: "Kafka" }));
    expect(screen.getByTestId("file-preview")).toBeVisible();
    expect(screen.getByTestId("file-preview")).toHaveTextContent("szukam: Kafka");
    expect(screen.queryByRole("button", { name: "Rozwiń CV" })).toBeNull();
  });

  it("zwinięte wymagania: CV z paskiem, bez zakładek; „Wszystkie wymagania” je przywraca", async () => {
    const user = userEvent.setup();
    mountInPanel({ initialTab: "requirements" });
    await user.click(await screen.findByRole("button", { name: "Zwiń wymagania" }));

    expect(screen.queryByRole("tab")).toBeNull();
    expect(await screen.findByTestId("file-preview")).toBeVisible();
    expect(screen.getByTestId("requirements-strip")).toBeVisible();
    // Ukryta sekcja nie ma nazwy dostępnej — sprawdzamy jej treść.
    expect(screen.getByText("Kafka")).not.toBeVisible();
    expect(screen.getByTestId("candidate-preview-pane")).toHaveAttribute("data-info-collapsed", "true");

    // Klik w wymaganie z paska szuka w CV.
    await user.click(screen.getByRole("button", { name: "UML z paska" }));
    expect(screen.getByTestId("file-preview")).toHaveTextContent("szukam: UML");

    await user.click(screen.getByRole("button", { name: "Wszystkie wymagania" }));
    expect(screen.getByRole("tab", { name: "Wymagania" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("candidate-preview-pane")).not.toHaveAttribute("data-info-collapsed");
  });

  it("oba zwinięte: dwie listwy, strefa wąska, panel na resztę", async () => {
    const user = userEvent.setup();
    mountInPanel();
    await screen.findByTestId("file-preview");
    await user.click(screen.getByRole("button", { name: "Zwiń CV" }));
    await user.click(screen.getByRole("button", { name: "Zwiń wymagania" }));

    expect(screen.getByRole("button", { name: "Rozwiń CV" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Rozwiń wymagania" })).toBeVisible();
    // Ukryta sekcja nie ma nazwy dostępnej — sprawdzamy jej treść.
    expect(screen.getByText("Kafka")).not.toBeVisible();
    expect(screen.getByTestId("person-panel-side").className).toContain("lg:w-[5.5rem]");
    expect(screen.getByTestId("person-panel-column").className).toContain("lg:flex-1");

    await user.click(screen.getByRole("button", { name: "Rozwiń wymagania" }));
    expect(screen.getByRole("region", { name: "Wymagania" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Rozwiń wymagania" })).toBeNull();
  });

  it("zapamiętane zwinięte CV nie pobiera pliku, dopóki ktoś go nie rozwinie (D4)", async () => {
    window.localStorage.setItem(
      "nexus:person-preview-layout:7",
      JSON.stringify({ cvCollapsed: true, infoCollapsed: false }),
    );
    const user = userEvent.setup();
    mountInPanel();
    await user.click(await screen.findByRole("button", { name: "Rozwiń CV" }));
    expect(await screen.findByTestId("file-preview")).toBeVisible();
    expect(mocks.previewMounted).toHaveBeenCalledTimes(1);
    expect(JSON.parse(window.localStorage.getItem("nexus:person-preview-layout:7") ?? "null")).toEqual({
      cvCollapsed: false,
      infoCollapsed: false,
      columnWidth: null,
      compact: false,
    });
  });

  it("zapamiętane zwinięte CV: przed rozwinięciem podgląd pliku nie powstaje", async () => {
    window.localStorage.setItem(
      "nexus:person-preview-layout:7",
      JSON.stringify({ cvCollapsed: true, infoCollapsed: false }),
    );
    mountInPanel();
    await screen.findByRole("button", { name: "Rozwiń CV" });
    await act(async () => {});
    expect(screen.queryByTestId("file-preview")).toBeNull();
    expect(mocks.previewMounted).not.toHaveBeenCalled();
    expect(mocks.original).not.toHaveBeenCalled();
  });

  it("w szerokiej strefie (monitor) pasek stoi tylko przy zwiniętych wymaganiach", async () => {
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    vi.spyOn(Element.prototype, "clientWidth", "get").mockImplementation(() => 1200);
    try {
      const user = userEvent.setup();
      mountInPanel({ initialTab: "requirements" });
      expect(await screen.findByTestId("file-preview")).toBeVisible();
      expect(screen.getByTestId("candidate-preview-pane")).toHaveAttribute("data-dual", "true");
      expect(screen.getByRole("region", { name: "Wymagania" })).toBeVisible();
      expect(screen.queryByTestId("requirements-strip")).toBeNull();

      await user.click(screen.getByRole("button", { name: "Zwiń wymagania" }));
      expect(screen.getByTestId("requirements-strip")).toBeVisible();
      expect(screen.getByTestId("file-preview")).toBeVisible();

      await user.click(screen.getByRole("button", { name: "Wszystkie wymagania" }));
      expect(screen.queryByTestId("requirements-strip")).toBeNull();
      expect(screen.getByRole("region", { name: "Wymagania" })).toBeVisible();
      expect(mocks.previewMounted).toHaveBeenCalledTimes(1);
    } finally {
      vi.unstubAllGlobals();
      vi.restoreAllMocks();
    }
  });

  it("„Historia osoby” na listwie rozwija CV z historią", async () => {
    mocks.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: String(url).startsWith("/api/notes")
          ? { items: [{ id: 1, job_id: 201, content: "Umówiony telefon.", created_at: "2026-10-12T08:00:00Z", group: "talks" }] }
          : PROFILE_DOCS,
      }),
    );
    const user = userEvent.setup();
    mountInPanel();
    await screen.findByRole("button", { name: "Historia osoby (1)" });
    await user.click(screen.getByRole("button", { name: "Zwiń CV" }));

    await user.click(screen.getByRole("button", { name: "Pokaż historię osoby" }));
    expect(screen.getByRole("region", { name: "Historia osoby" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Rozwiń CV" })).toBeNull();
  });

  it("historia otwarta z zewnątrz rozwija CV także wtedy, gdy była otwarta przed zwinięciem", async () => {
    mocks.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: String(url).startsWith("/api/notes")
          ? { items: [{ id: 1, job_id: 201, content: "Umówiony telefon.", created_at: "2026-10-12T08:00:00Z", group: "talks" }] }
          : PROFILE_DOCS,
      }),
    );
    function ControlledHistory() {
      const [open, setOpen] = useState(false);
      return (
        <PersonPanelSideProvider>
          <PersonPanelSideZone />
          <button type="button" onClick={() => setOpen(true)}>
            Pokaż historię z profilu
          </button>
          <PersonPanelSide>
            <CandidatePreviewPane
              candidateId={101}
              jobId={201}
              stageId={901}
              historyOpen={open}
              onHistoryOpenChange={setOpen}
              collapsible
            />
          </PersonPanelSide>
        </PersonPanelSideProvider>
      );
    }
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ControlledHistory />
      </QueryClientProvider>,
    );
    await screen.findByRole("button", { name: "Historia osoby (1)" });
    await user.click(screen.getByRole("button", { name: "Pokaż historię z profilu" }));
    expect(screen.getByRole("region", { name: "Historia osoby" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Zwiń CV" }));
    expect(screen.getByRole("button", { name: "Rozwiń CV" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Pokaż historię z profilu" }));
    expect(screen.queryByRole("button", { name: "Rozwiń CV" })).toBeNull();
    expect(screen.getByRole("region", { name: "Historia osoby" })).toBeVisible();
  });

  it("zwinięcie w jednej zakładce panelu nie pobiera CV w ukrytym podglądzie innej zakładki", async () => {
    function TwoSections() {
      const [tab, setTab] = useState<PreviewTab>("cv");
      return (
        <PersonPanelSideProvider>
          <PersonPanelSideZone />
          <PersonPanelSideSection active>
            <PersonPanelSide>
              <CandidatePreviewPane
                candidateId={101}
                jobId={201}
                stageId={901}
                tab={tab}
                onTabChange={setTab}
                collapsible
              />
            </PersonPanelSide>
          </PersonPanelSideSection>
          {/* Np. podgląd Screeningu, gdy rekruter jest w zakładce CV. */}
          <PersonPanelSideSection active={false}>
            <PersonPanelSide>
              <CandidatePreviewPane candidateId={101} jobId={201} stageId={901} defaultTab="requirements" collapsible />
            </PersonPanelSide>
          </PersonPanelSideSection>
        </PersonPanelSideProvider>
      );
    }
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <TwoSections />
      </QueryClientProvider>,
    );
    await screen.findByTestId("file-preview");
    expect(mocks.previewMounted).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("tab", { name: "Wymagania" }));
    await user.click(screen.getByRole("button", { name: "Zwiń wymagania" }));
    await act(async () => {});
    expect(screen.getAllByTestId("file-preview")).toHaveLength(1);
    expect(mocks.previewMounted).toHaveBeenCalledTimes(1);
  });
});

/**
 * „Wgraj CV” w podglądzie po „Rozwiń” (13.10.2026): plik staje się głównym CV
 * i CV tej rekrutacji, podgląd przechodzi na „CV oryginalne”.
 */
describe("CandidatePreviewPane — Wgraj CV", () => {
  function mountWithUpload() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <CandidatePreviewPane
          candidateId={101}
          jobId={7}
          stageId={901}
          preferCompanyCv
          cvUpload={{ candidateName: "Tomasz Wzorcowy", jobTitle: "Senior Java Developer" }}
        />
      </QueryClientProvider>,
    );
  }

  beforeEach(() => {
    mocks.upload.mockReset();
    mocks.upload.mockResolvedValue({ data: { has_snapshot: true } });
  });

  it("przycisk w pasku źródeł wgrywa plik na CV tej rekrutacji", async () => {
    mountWithUpload();
    await screen.findByRole("group", { name: "Które CV pokazać" });
    expect(screen.getByRole("button", { name: /Wgraj CV/ })).toBeInTheDocument();

    const file = new File(["%PDF-1.4"], "Tomasz_CV_2026.pdf", { type: "application/pdf" });
    await act(async () => {
      fireEvent.change(screen.getByTestId("preview-cv-upload-input"), { target: { files: [file] } });
    });

    await waitFor(() => expect(mocks.upload).toHaveBeenCalledWith(901, file));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "CV oryginalne" })).toHaveAttribute("aria-pressed", "true"),
    );
  });

  it("plik „B2B_…” zostaje CV do klienta: podgląd przechodzi na „CV firmowe”", async () => {
    mocks.showActionToast.mockReset();
    mocks.upload.mockResolvedValue({
      data: {
        has_snapshot: true,
        outcome: "client_cv",
        client_cv: { status: "draft", source: "document", edit_revision: 1, candidate_stage_id: 901 },
        client_cv_stage_id: 901,
        replaced: "none",
        undo_available: true,
        uploaded_filename: "B2B_Tester_Jan_Testowy.docx",
      },
    });
    const user = userEvent.setup();
    mountWithUpload();
    await screen.findByRole("group", { name: "Które CV pokazać" });
    await user.click(screen.getByRole("button", { name: "CV oryginalne" }));
    expect(screen.getByRole("button", { name: "CV oryginalne" })).toHaveAttribute("aria-pressed", "true");

    const file = new File(["PK"], "B2B_Tester_Jan_Testowy.docx");
    await act(async () => {
      fireEvent.change(screen.getByTestId("preview-cv-upload-input"), { target: { files: [file] } });
    });

    await waitFor(() => expect(mocks.upload).toHaveBeenCalledWith(901, file));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "CV firmowe" })).toHaveAttribute("aria-pressed", "true"),
    );
    expect(mocks.showActionToast).toHaveBeenCalledWith(
      "CV do klienta z pliku B2B_Tester_Jan_Testowy.docx.",
      expect.objectContaining({ actionLabel: "Cofnij" }),
    );
  });

  it("zły format z przycisku: bez wysyłki", async () => {
    mountWithUpload();
    await screen.findByRole("group", { name: "Które CV pokazać" });

    fireEvent.change(screen.getByTestId("preview-cv-upload-input"), {
      target: { files: [new File(["x"], "cv.odt")] },
    });

    expect(mocks.upload).not.toHaveBeenCalled();
  });

  it("brak CV: kafelek „Wgraj CV” zamiast linku do profilu", async () => {
    mocks.original.mockResolvedValue({ data: { has_snapshot: false } });
    mocks.get.mockResolvedValue({ data: [] });
    mocks.branded.mockResolvedValue({ data: { status: "none" } });
    mountWithUpload();

    expect(await screen.findByText("Kandydat nie ma CV ani w zgłoszeniu, ani w profilu.")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Wgraj CV/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Dodaj CV w profilu kandydata/ })).toBeNull();
  });
});

/**
 * „Pobierz CV” w pasku źródeł (15.10.2026, D1–D5): pobiera to, co widać —
 * oryginał, zaznaczony plik albo CV firmowe (Word / PDF, ten sam plik co dok).
 */
describe("CandidatePreviewPane — Pobierz CV (D1–D5)", () => {
  const UPLOAD = { candidateName: "Tomasz Wzorcowy", jobTitle: "Senior Java Developer" };

  function mountPane(props: Partial<CandidatePreviewPaneProps> = {}, seed?: (client: QueryClient) => void) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    seed?.(queryClient);
    render(
      <QueryClientProvider client={queryClient}>
        <CandidatePreviewPane candidateId={101} jobId={201} stageId={901} {...props} />
      </QueryClientProvider>,
    );
  }

  beforeEach(() => {
    for (const fn of [
      mocks.downloadOriginal,
      mocks.downloadDocument,
      mocks.downloadBlob,
      mocks.stageCvFile,
      mocks.stageCvPdf,
      mocks.showError,
      mocks.refresh,
      mocks.candidateGet,
    ]) {
      fn.mockReset();
    }
    mocks.downloadOriginal.mockResolvedValue(undefined);
    mocks.downloadDocument.mockResolvedValue(undefined);
    mocks.stageCvFile.mockResolvedValue({ blob: new Blob(["docx"]), filename: "CV_firmowe.docx" });
    mocks.stageCvPdf.mockResolvedValue({ blob: new Blob(["pdf"]), filename: "CV_firmowe.pdf" });
  });

  it("kopia ze zgłoszenia: pobiera plik etapu, bez wpisu pobrania (D2, D5)", async () => {
    const user = userEvent.setup();
    mountPane();
    await screen.findByTestId("file-preview");
    await user.click(screen.getByRole("button", { name: "Pobierz CV" }));
    expect(mocks.downloadOriginal).toHaveBeenCalledWith(
      "/api/candidates/stages/901/cv/original/download",
      "CV_ze_zgloszenia.pdf",
    );
    expect(mocks.downloadDocument).not.toHaveBeenCalled();
  });

  it("podgląd kopii ze zgłoszenia idzie do dziennika jako podgląd, nie zapis (audyt 22.10, F25)", async () => {
    mocks.fetchBlob.mockReset();
    mocks.fetchBlob.mockResolvedValue(new Blob(["pdf"]));
    mocks.previewLoader.current = null;
    mountPane();
    await screen.findByTestId("file-preview");
    expect(mocks.previewLoader.current).not.toBeNull();
    await mocks.previewLoader.current!(101, 901);
    expect(mocks.fetchBlob).toHaveBeenCalledWith(
      "/api/candidates/stages/901/cv/original/download?disposition=inline",
    );
  });

  it("bez kopii ze zgłoszenia pobiera główne CV z profilu", async () => {
    mocks.original.mockResolvedValue({ data: { has_snapshot: false } });
    const user = userEvent.setup();
    mountPane();
    expect(await screen.findByTestId("file-preview")).toHaveTextContent("Tomasz_Wzorcowy_CV.pdf");
    await user.click(screen.getByRole("button", { name: "Pobierz CV" }));
    expect(mocks.downloadDocument).toHaveBeenCalledWith(101, expect.objectContaining({ id: 1 }));
  });

  it("„Inne pliki”: pobiera zaznaczony plik", async () => {
    const user = userEvent.setup();
    mountPane();
    await screen.findByTestId("file-preview");
    await user.click(screen.getByRole("button", { name: "Inne pliki (2)" }));
    const list = screen.getByRole("list", { name: "Pliki CV kandydata" });
    await user.click(within(list).getByRole("button", { name: /Tomasz_CV_EN\.docx/ }));
    await user.click(screen.getByRole("button", { name: "Pobierz CV" }));
    expect(mocks.downloadDocument).toHaveBeenCalledWith(101, expect.objectContaining({ id: 2 }));
  });

  it("stoi przed „Wgraj CV”, a bez prawa wgrania też jest (D1)", async () => {
    mountPane({ cvUpload: UPLOAD });
    await screen.findByTestId("file-preview");
    const download = screen.getByRole("button", { name: "Pobierz CV" });
    const upload = screen.getByRole("button", { name: /Wgraj CV/ });
    expect(download.compareDocumentPosition(upload) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    cleanup();

    mountPane();
    await screen.findByTestId("file-preview");
    expect(screen.getByRole("button", { name: "Pobierz CV" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /Wgraj CV/ })).toBeNull();
  });

  it("dymek mówi, jaki to plik i skąd jest (D2)", async () => {
    mountPane();
    await screen.findByTestId("file-preview");
    act(() => screen.getByRole("button", { name: "Pobierz CV" }).focus());
    const tip = await screen.findByRole("tooltip");
    expect(tip).toHaveTextContent("CV_ze_zgloszenia.pdf");
    expect(tip).toHaveTextContent("dołączony do zgłoszenia");
  });

  it("CV firmowe: Word i PDF z CV etapu, bez drugiego „Pobierz” w treści (D3)", async () => {
    const user = userEvent.setup();
    mountPane();
    await user.click(await screen.findByRole("button", { name: "CV firmowe" }));
    expect(await screen.findByTestId("stage-cv-preview")).toHaveAttribute("data-hide-download", "true");
    expect(screen.queryByRole("button", { name: "Pobierz CV" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Pobierz Word" }));
    expect(mocks.stageCvFile).toHaveBeenCalledWith(901, { download: "preview" });
    await waitFor(() => expect(mocks.downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "CV_firmowe.docx"));

    await user.click(screen.getByRole("button", { name: "Pobierz PDF" }));
    expect(mocks.stageCvPdf).toHaveBeenCalledWith(901, { download: "preview" });
    await waitFor(() => expect(mocks.downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "CV_firmowe.pdf"));
  });

  it("CV firmowe pary z poprzedniego wiersza etapu pobiera się z wiersza, na którym leży", async () => {
    mocks.branded.mockImplementation((stageId: number) =>
      Promise.resolve({
        data:
          stageId === 901
            ? { status: "none", edit_revision: 0, pair_source_stage_id: 880, pair_source_status: "draft" }
            : { status: "draft", from_generator: true, edit_revision: 4 },
      }),
    );
    const user = userEvent.setup();
    mountPane();
    await user.click(await screen.findByRole("button", { name: "CV firmowe" }));
    await screen.findByTestId("stage-cv-preview");
    await user.click(screen.getByRole("button", { name: "Pobierz Word" }));
    expect(mocks.stageCvFile).toHaveBeenCalledWith(880, { download: "preview" });
  });

  it("CV firmowe bez zgody RODO: oba przyciski wyłączone", async () => {
    mocks.branded.mockResolvedValue({ data: { status: "draft", from_generator: true, consent_missing: true } });
    const user = userEvent.setup();
    mountPane();
    await user.click(await screen.findByRole("button", { name: "CV firmowe" }));
    await screen.findByTestId("stage-cv-preview");
    expect(screen.getByRole("button", { name: "Pobierz Word" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Pobierz PDF" })).toBeDisabled();
  });

  it("bez CV firmowego nie ma czego pobrać", async () => {
    mocks.branded.mockResolvedValue({ data: { status: "none" } });
    const user = userEvent.setup();
    mountPane();
    await user.click(await screen.findByRole("button", { name: "CV firmowe" }));
    await screen.findByText(/CV firmowe jeszcze nie powstało/);
    expect(screen.queryByTestId("preview-cv-download")).toBeNull();
  });

  it("bez CV w zgłoszeniu i w profilu przycisku nie ma", async () => {
    mocks.original.mockResolvedValue({ data: { has_snapshot: false } });
    mocks.get.mockResolvedValue({ data: [] });
    mountPane();
    await screen.findByText("Kandydat nie ma CV ani w zgłoszeniu, ani w profilu.");
    expect(screen.queryByTestId("preview-cv-download")).toBeNull();
  });

  it("przy otwartej „Historii osoby” przycisku nie ma (D5)", async () => {
    mocks.get.mockImplementation((url: string) =>
      Promise.resolve({
        data: String(url).startsWith("/api/notes")
          ? { items: [{ id: 1, job_id: 201, content: "Umówiony telefon.", created_at: "2026-10-12T08:00:00Z", group: "talks" }] }
          : PROFILE_DOCS,
      }),
    );
    const user = userEvent.setup();
    mountPane();
    await screen.findByTestId("file-preview");
    await user.click(await screen.findByRole("button", { name: /Historia osoby/ }));
    expect(screen.queryByTestId("preview-cv-download")).toBeNull();
    await user.click(screen.getByRole("button", { name: "CV oryginalne" }));
    expect(screen.getByRole("button", { name: "Pobierz CV" })).toBeInTheDocument();
  });

  it("awaria pobrania mówi to wprost", async () => {
    mocks.downloadOriginal.mockRejectedValue(new Error("500"));
    const user = userEvent.setup();
    mountPane();
    await screen.findByTestId("file-preview");
    await user.click(screen.getByRole("button", { name: "Pobierz CV" }));
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Nie udało się pobrać pliku."));
  });

  describe("nowsze CV w profilu (D4)", () => {
    const NEWER = {
      ...PROFILE_DOCS[0],
      id: 5,
      filename: "Tomasz_CV_2026.pdf",
      uploaded_at: "2026-10-14T10:00:00Z",
      created_at: "2026-10-14T10:00:00Z",
    };
    beforeEach(() => {
      mocks.get.mockResolvedValue({ data: [NEWER, { ...PROFILE_DOCS[0], is_primary: false }, PROFILE_DOCS[1]] });
    });

    it("ramka nad oryginałem, „Pokaż” otwiera plik w „Innych plikach”; bez prawa wgrania bez podmiany", async () => {
      const user = userEvent.setup();
      mountPane();
      await screen.findByTestId("file-preview");
      expect(await screen.findByText("W profilu jest nowsze CV")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Użyj w tej rekrutacji/ })).toBeNull();

      await user.click(screen.getByRole("button", { name: "Pokaż" }));
      expect(screen.getByRole("button", { name: "Inne pliki (3)" })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByTestId("file-preview")).toHaveTextContent("Tomasz_CV_2026.pdf");
      expect(screen.queryByText("W profilu jest nowsze CV")).toBeNull();
    });

    it("z prawem wgrania „Użyj w tej rekrutacji” podmienia kopię etapu", async () => {
      mocks.refresh.mockResolvedValue({
        data: { has_snapshot: true, original_cv_filename: "Tomasz_CV_2026.pdf", original_snapshot_at: "2026-10-15T08:00:00Z" },
      });
      const user = userEvent.setup();
      mountPane({ cvUpload: UPLOAD });
      await user.click(await screen.findByRole("button", { name: /Użyj w tej rekrutacji/ }));
      expect(mocks.refresh).toHaveBeenCalledWith(901);
      await waitFor(() => expect(screen.getByTestId("file-preview")).toHaveTextContent("Tomasz_CV_2026.pdf"));
      expect(screen.queryByText("W profilu jest nowsze CV")).toBeNull();
    });
  });

  it("plik z kwarantanny tożsamości (CV innej osoby) nie jest oryginałem do pobrania — znacznik z pamięci zapytań", async () => {
    mocks.original.mockResolvedValue({ data: { has_snapshot: false } });
    mocks.get.mockResolvedValue({ data: [{ ...PROFILE_DOCS[0], id: 9, is_primary: false, filename: "Cudze_CV.pdf" }] });
    mountPane({}, (client) =>
      client.setQueryData(candidateQueryKeys.detail(101), {
        id: 101,
        cv_extracted_data: { _identity_quarantine_source: { kind: "document", id: 9 } },
      }),
    );
    expect(await screen.findByText("Kandydat nie ma CV ani w zgłoszeniu, ani w profilu.")).toBeInTheDocument();
    expect(screen.queryByTestId("preview-cv-download")).toBeNull();
    expect(mocks.candidateGet).not.toHaveBeenCalled();
  });
});
