/**
 * Podgląd obok formularza screeningu (0424, D3): zakładki CV / Wymagania /
 * Po ludzku, przełącznik „CV oryginalne / CV firmowe / Inne pliki”, klik
 * w technologię szuka jej w CV (CV firmowe → oryginał, bo tam jest szukanie).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
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
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => mocks.get(...a) },
  candidateStageCvApi: {
    original: { get: (...a: unknown[]) => mocks.original(...a) },
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
  useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }),
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
  }: {
    doc: { filename: string };
    searchRequest?: { text: string } | null;
  }) => {
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
  downloadDocumentBlob: vi.fn(),
  fetchDocumentBlob: vi.fn(),
}));

vi.mock("@/components/v2/person/StageCvPreview", () => ({
  StageCvPreview: ({ cvStageId, revision }: { cvStageId: number; revision?: number }) => (
    <div data-testid="stage-cv-preview" data-revision={revision}>
      CV firmowe etapu {cvStageId}
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
