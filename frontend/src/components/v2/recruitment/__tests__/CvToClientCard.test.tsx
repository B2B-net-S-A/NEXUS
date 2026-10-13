/**
 * Karta „CV do klienta” (generator CV v3) — stany z makiety: gotowe (z uwagami
 * kontroli AI i zgodą RODO), generuje się, brak (z powodem pominięcia
 * auto-CV), stary szablon tylko do odczytu, „Użyj nowej wersji”.
 *
 * 12.10.2026 — „Użyj innego CV”: pasek „Ta osoba ma już gotowe CV”, plakietka
 * pochodzenia kopii i zgoda RODO dołączana do CV etapu bez dokumentu generatora.
 *
 * Karta niczego nie blokuje w procesie — brak zgody wyłącza tylko pobranie.
 *
 * 13.10.2026 (PR 4 „CV w procesie”): „Generuj CV” / „Wygeneruj ponownie”
 * rozwijają w karcie panel „Z czego powstało” zamiast okna generatora,
 * a karta pokazuje jedną liczbę rzeczy do sprawdzenia przed wysłaniem.
 */

import { configure, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/store/auth";

// Panel generacji pyta o kilka rzeczy naraz — pod obciążeniem sekunda to za mało.
configure({ asyncUtilTimeout: 5000 });

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  brandedGet: vi.fn(),
  originalGet: vi.fn(),
  selectGenerated: vi.fn(),
  selectStageCv: vi.fn(),
  selectDocument: vi.fn(),
  sources: vi.fn(),
  otherDialogProps: null as null | Record<string, unknown>,
  downloadAuthenticatedFile: vi.fn(),
  postAuthenticatedDownload: vi.fn(),
  downloadBlob: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
  editorProps: null as null | Record<string, unknown>,
  consentProps: null as null | Record<string, unknown>,
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: mocks.apiGet, post: mocks.apiPost },
  candidateStageCvApi: {
    branded: {
      get: (...a: unknown[]) => mocks.brandedGet(...a),
      selectGenerated: (...a: unknown[]) => mocks.selectGenerated(...a),
      selectStageCv: (...a: unknown[]) => mocks.selectStageCv(...a),
      selectDocument: (...a: unknown[]) => mocks.selectDocument(...a),
      sources: (...a: unknown[]) => mocks.sources(...a),
    },
    original: { get: (...a: unknown[]) => mocks.originalGet(...a) },
  },
}));
vi.mock("@/lib/authenticated-files", () => ({
  downloadAuthenticatedFile: (...a: unknown[]) => mocks.downloadAuthenticatedFile(...a),
  postAuthenticatedDownload: (...a: unknown[]) => mocks.postAuthenticatedDownload(...a),
  downloadBlob: (...a: unknown[]) => mocks.downloadBlob(...a),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));
// Edytor (TipTap) za `dynamic()` — atrapa zaznacza, że się otworzył.
vi.mock("next/dynamic", () => ({
  default: () =>
    function EditorStub(props: { stageId?: number; initialPanel?: string }) {
      mocks.editorProps = props;
      return <div data-testid="editor-stub">{`editor:${props.stageId}`}</div>;
    },
}));
// Okno generatora nie może się już otworzyć z karty — atrapa to wykryje.
vi.mock("@/components/v2/cv-generator/CvGeneratorDialog", () => ({
  CvGeneratorDialog: () => <div data-testid="generator-dialog" />,
}));
vi.mock("@/components/v2/cv-generator/ConsentAttachButton", () => ({
  ConsentAttachButton: (props: Record<string, unknown>) => {
    mocks.consentProps = props;
    return <button type="button">Wgraj</button>;
  },
}));
// Okno wyboru ma własny test — tu sprawdzamy, że karta je otwiera.
vi.mock("@/components/v2/recruitment/UseOtherCvDialog", () => ({
  UseOtherCvDialog: (props: Record<string, unknown>) => {
    mocks.otherDialogProps = props;
    return <div data-testid="use-other-cv-dialog" />;
  },
}));
vi.mock("@/components/v2/modals/CVOriginalPreviewModal", () => ({
  CVOriginalPreviewModal: () => <div data-testid="original-preview" />,
}));

import { CvToClientCard } from "@/components/v2/recruitment/CvToClientCard";

type Row = Record<string, unknown> & { id: number };
let rows: Row[] = [];
let events: unknown[] = [];
// Generacja w karcie: proces osoby, pliki CV, „Z czego powstało”.
const RECRUITMENT = {
  stage_id: 21, job_id: 42, job_title: "Senior Java Developer", stage: "verified",
  has_champion: true, has_notes: true, has_cv: true, notes_chars: 900, ready: true,
  client_id: 7, client_name: "Bank Przykładowy", required_champion: false, required_notes_min_chars: 0, missing_inputs: [],
};
let recruitments: unknown[] = [RECRUITMENT];
const CV_SOURCES = [
  { id: 30, filename: "stare.docx", is_primary: false, uploaded_at: "2025-01-01T00:00:00Z" },
  { id: 31, filename: "Jan_Kowalski_CV.pdf", is_primary: true, uploaded_at: "2026-09-12T10:00:00Z" },
];
const AI_SOURCES = {
  original_cv: { document_id: 31, filename: "Jan_Kowalski_CV.pdf", uploaded_at: "2026-09-12T10:00:00Z" },
  champion: true,
  answers: { count: 5, excluded: 1 },
  notes: { count: 3, excluded: 0 },
  transcripts: { count: 2, excluded: 1 },
  prep: { count: 1, excluded: 0 },
  rate_notes: { count: 2, excluded: 0 },
  defaults: { answers: true, notes: true, transcripts: false, prep: false },
  last_used: null as null | Record<string, boolean>,
};
let aiSources = AI_SOURCES;
// Liczba rzeczy do sprawdzenia: QC karty (bez zapisu przebiegu) i uwagi edytora.
let qcChecks: unknown[] = [];
let qcError: unknown = null;
let issues = { generator_warnings: [] as string[], content_review: { status: null, version: null, findings: [] as unknown[] } };
// Źródła „Użyj innego CV”: wszystkie generacje osoby i pliki CV z profilu.
let personGenerated: Row[] = [];
let documents: Row[] = [];

function renderCard(overrides: Partial<React.ComponentProps<typeof CvToClientCard>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CvToClientCard
        stageId={21}
        candidateId={121}
        candidateName="Jan Kowalski"
        jobId={42}
        jobTitle="Senior Java Developer"
        readOnly={false}
        {...overrides}
      />
    </QueryClientProvider>,
  );
}

function setUser(access: "read" | "write" = "write") {
  useAuthStore.setState({
    user: {
      id: 12, email: "r@example.com", name: "Rekruter", role: "recruiter", roles: ["recruiter"],
      profile_completed: true, profile_completed_at: null, force_password_change: false,
      effective_section_access: { sourcing: access },
    } as never,
    realUser: null,
    hydrated: true,
  });
}

function generatePosts(): Array<[string, Record<string, unknown>]> {
  return mocks.apiPost.mock.calls.filter(([url]) => url === "/api/cv-generator/generate") as Array<
    [string, Record<string, unknown>]
  >;
}

beforeEach(() => {
  vi.clearAllMocks();
  setUser();
  sessionStorage.clear();
  mocks.editorProps = null;
  mocks.consentProps = null;
  mocks.otherDialogProps = null;
  rows = [];
  events = [];
  personGenerated = [];
  documents = [];
  recruitments = [RECRUITMENT];
  aiSources = AI_SOURCES;
  qcChecks = [];
  qcError = null;
  issues = { generator_warnings: [], content_review: { status: null, version: null, findings: [] } };
  mocks.apiPost.mockImplementation(async (url: string) => {
    if (url === "/api/cv-generator/generate") return { data: { id: 77, status: "processing", candidate_name: "Jan Kowalski" } };
    throw new Error(`unexpected POST ${url}`);
  });
  mocks.apiGet.mockImplementation((url: string, config?: { params?: Record<string, unknown> }) => {
    if (url === "/api/cv-generator/candidates/121/recruitments") return Promise.resolve({ data: recruitments });
    if (url === "/api/cv-generator/candidates/121/cv-sources") return Promise.resolve({ data: CV_SOURCES });
    if (url.endsWith("/rule-for-generation")) return Promise.resolve({ data: { is_active: false } });
    if (/^\/api\/candidates\/stages\/\d+\/cv\/ai-sources$/.test(url)) return Promise.resolve({ data: aiSources });
    if (/^\/api\/pipeline\/stages\/\d+\/qc$/.test(url)) {
      if (qcError) return Promise.reject(qcError);
      const stageId = Number(url.split("/")[4]);
      return Promise.resolve({ data: { stage_id: stageId, cv: { stage_id: stageId }, checks: qcChecks } });
    }
    if (/^\/api\/candidates\/stages\/\d+\/cv\/branded\/issues$/.test(url)) return Promise.resolve({ data: issues });
    if (url === "/api/cv-generator/generated") {
      // Karta pyta o parę (z `job_id`), lista wyboru — o całą osobę.
      return Promise.resolve({ data: config?.params?.job_id != null ? rows : personGenerated });
    }
    if (url.startsWith("/api/candidates/121/documents")) return Promise.resolve({ data: documents });
    if (url === "/api/cv-generator/policy") return Promise.resolve({ data: {} });
    return Promise.resolve({ data: { job_id: 42, items: events, limit: 30 } });
  });
  mocks.sources.mockResolvedValue({ data: { items: [] } });
  mocks.brandedGet.mockResolvedValue({ data: { status: "none", edit_revision: 0, version: 0 } });
  mocks.originalGet.mockResolvedValue({
    data: { has_snapshot: true, original_cv_filename: "Jan_Kowalski_CV.pdf", original_snapshot_at: "2026-09-12T10:00:00Z" },
  });
});

describe("CvToClientCard — brak CV", () => {
  it("„Generuj CV” rozwija w karcie „Z czego powstało” — bez okna generatora", async () => {
    renderCard();
    expect(await screen.findByText(/Jeszcze nie ma CV do klienta/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Generuj CV/ }));
    const panel = await screen.findByTestId("cv-generate-panel");
    expect(screen.queryByTestId("generator-dialog")).toBeNull();
    // Przycisk, który otworzył panel, znika — w panelu jest „Generuj”.
    expect(screen.queryByRole("button", { name: /Generuj CV/ })).toBeNull();

    const sources = within(panel).getByRole("region", { name: "Z czego powstało" });
    // Wiersze pojawiają się po odczycie `…/ai-sources` („Wczytuję źródła…”).
    expect(await within(sources).findByTestId("ai-source-original")).toHaveTextContent("Jan_Kowalski_CV.pdf");
    expect(within(sources).getByTestId("ai-source-original")).toHaveTextContent("zawsze");
    expect(within(sources).getByTestId("ai-source-champion")).toHaveTextContent("zawsze");
    expect(within(sources).getByTestId("ai-source-answers")).toHaveTextContent(
      "5 odpowiedzi, 1 przeczy pytaniu — nie jest dowodem",
    );
    expect(within(sources).getByTestId("ai-source-transcripts")).toHaveTextContent(
      "2 rozmowy, 1 spoza tej rekrutacji nie wchodzi",
    );
    // Domyślne: odpowiedzi i notatki tak, transkrypty i prep nie; stawka zawsze wycinana.
    expect(await within(sources).findByRole("switch", { name: "Odpowiedzi ze screeningu" })).toBeChecked();
    expect(within(sources).getByRole("switch", { name: "Notatki tej rekrutacji" })).toBeChecked();
    expect(within(sources).getByRole("switch", { name: "Transkrypty rozmów" })).not.toBeChecked();
    expect(within(sources).getByRole("switch", { name: "Podsumowania prepu" })).not.toBeChecked();
    const rate = within(sources).getByRole("switch", { name: "Notatki ze stawką — zawsze wycinane" });
    expect(rate).not.toBeChecked();
    expect(rate).toBeDisabled();
    // Obróbka i język — te same przełączniki co w oknie generatora.
    expect(within(panel).getByRole("group", { name: "Obróbka treści" })).toBeInTheDocument();
    expect(within(panel).getByRole("group", { name: "Język CV" })).toBeInTheDocument();
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/candidates/stages/21/cv/ai-sources");
  });

  it("„Generuj” wysyła oryginał i przełączniki źródeł; karta mówi „Generuje się…”", async () => {
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Generuj CV/ }));
    const panel = await screen.findByTestId("cv-generate-panel");
    await userEvent.click(await within(panel).findByRole("switch", { name: "Transkrypty rozmów" }));
    await userEvent.click(within(panel).getByRole("switch", { name: "Odpowiedzi ze screeningu" }));
    const generate = within(panel).getByRole("button", { name: /^Generuj$/ });
    await waitFor(() => expect(generate).toBeEnabled());
    rows = [{ id: 77, status: "processing", origin: "manual" }];
    await userEvent.click(generate);

    await waitFor(() => expect(generatePosts()).toHaveLength(1));
    expect(generatePosts()[0][1]).toMatchObject({
      candidate_id: 121,
      stage_id: 21,
      cv_document_id: 31,
      content_mode: "tailored",
      sources: { answers: false, notes: true, transcripts: true, prep: false },
    });
    expect(await screen.findByText("Generuje się…")).toBeInTheDocument();
    expect(screen.getByText(/Możesz zamknąć panel/)).toBeInTheDocument();
    expect(screen.queryByText(/Moich CV/)).toBeNull();
    expect(screen.queryByTestId("cv-generate-panel")).toBeNull();
    expect(screen.queryByText(/Jeszcze nie ma CV do klienta/)).toBeNull();
  });

  it("przełączniki startują od wyboru, z którego powstała bieżąca wersja", async () => {
    aiSources = { ...AI_SOURCES, last_used: { answers: false, notes: true, transcripts: true, prep: true } };
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Generuj CV/ }));
    const panel = await screen.findByTestId("cv-generate-panel");
    expect(await within(panel).findByRole("switch", { name: "Odpowiedzi ze screeningu" })).not.toBeChecked();
    expect(within(panel).getByRole("switch", { name: "Transkrypty rozmów" })).toBeChecked();
    expect(within(panel).getByRole("switch", { name: "Podsumowania prepu" })).toBeChecked();
  });

  it("odmowa serwera (reguła klienta, 422) stoi w panelu, a panel zostaje otwarty", async () => {
    mocks.apiPost.mockRejectedValue({
      response: { status: 422, data: { detail: "Ten klient wymaga numeru projektu w CV." } },
    });
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Generuj CV/ }));
    const panel = await screen.findByTestId("cv-generate-panel");
    const generate = within(panel).getByRole("button", { name: /^Generuj$/ });
    await waitFor(() => expect(generate).toBeEnabled());
    await userEvent.click(generate);
    expect(await within(panel).findByRole("alert")).toHaveTextContent("Ten klient wymaga numeru projektu w CV.");
    expect(mocks.showError).toHaveBeenCalledWith("Ten klient wymaga numeru projektu w CV.");
  });

  it("tej rekrutacji nie ma na liście procesów osoby — CV nie powstanie dla innego procesu", async () => {
    recruitments = [{ ...RECRUITMENT, stage_id: 99, job_id: 900 }];
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Generuj CV/ }));
    const panel = await screen.findByTestId("cv-generate-panel");
    expect(await within(panel).findByTestId("cvgen-missing")).toHaveTextContent(/tej rekrutacji nie ma na liście procesów/);
    expect(within(panel).getByRole("button", { name: /^Generuj$/ })).toBeDisabled();
  });

  it("bez prawa zapisu w Sourcing panel mówi o uprawnieniu zamiast formularza", async () => {
    setUser("read");
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Generuj CV/ }));
    expect(await screen.findByTestId("cv-generate-panel")).toHaveTextContent(
      "Generowanie CV wymaga prawa zapisu w Sourcing.",
    );
    expect(screen.queryByRole("button", { name: /^Generuj$/ })).toBeNull();
  });

  it("pokazuje, dlaczego automat nie przygotował CV — z „Pracy w tle”", async () => {
    events = [
      {
        id: 9,
        kind: "cv_auto_generate_skipped",
        created_at: "2026-09-21T08:00:00Z",
        reason: "consent_screenshot_required",
        candidate: { id: 121, name: "Jan Kowalski" },
      },
    ];
    renderCard();
    expect(await screen.findByTestId("auto-cv-skip-notice")).toHaveTextContent(
      "CV nie zostało wygenerowane automatycznie: reguła klienta wymaga zrzutu zgody RODO.",
    );
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/jobs/42/background-events", { params: { limit: 30 } });
  });

  it("awaria wczytania to błąd z ponowieniem, nie „brak CV”", async () => {
    mocks.brandedGet.mockRejectedValue(new Error("offline"));
    renderCard();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wczytać CV do klienta.");
    expect(screen.queryByText(/Jeszcze nie ma CV do klienta/)).toBeNull();
  });

  it("tylko do odczytu: bez „Generuj CV”", async () => {
    renderCard({ readOnly: true });
    expect(await screen.findByText(/Jeszcze nie ma CV do klienta/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Generuj CV/ })).toBeNull();
  });
});

describe("CvToClientCard — CV gotowe", () => {
  it("uwagi kontroli AI, auto-CV do sprawdzenia i zgoda RODO blokująca TYLKO pobranie", async () => {
    mocks.brandedGet.mockResolvedValue({
      data: { status: "draft", from_generator: true, generated_document_id: 5, edit_revision: 3, version: 1, content_html: "<p>CV</p>" },
    });
    rows = [
      {
        id: 5,
        status: "ready",
        origin: "auto",
        needs_review: true,
        content_mode: "tailored",
        language: "en",
        created_at: "2026-09-22T12:40:00Z",
        consent_required: true,
        consent_missing: true,
        factual_review: { status: "advisory", findings: 2 },
      },
    ];
    issues = {
      generator_warnings: [],
      content_review: {
        status: null,
        version: null,
        findings: [
          { text: "Przeglądy kodu.", status: "unsupported" },
          { text: "Mentoring.", status: "contradicted" },
        ],
      },
    };
    renderCard();
    expect(await screen.findByText("CV gotowe · szkic")).toBeInTheDocument();
    expect(screen.getByText("Pod rekrutację")).toBeInTheDocument();
    expect(screen.getByText("EN")).toBeInTheDocument();
    expect(screen.getByText("wygenerowane automatycznie — sprawdź przed wysyłką")).toBeInTheDocument();
    expect(await screen.findByTestId("cv-checks-count")).toHaveTextContent("2 rzeczy do sprawdzenia przed wysłaniem");
    expect(screen.getByRole("button", { name: /Pobierz DOCX/ })).toBeDisabled();
    // Podgląd i edycja działają bez zgody.
    expect(screen.getByRole("button", { name: /Podgląd/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Edytuj/ })).toBeEnabled();
    expect(screen.getByText(/Zgoda RODO: brak zrzutu/)).toBeInTheDocument();
    expect(mocks.consentProps).toMatchObject({ generatedId: 5, hasConsent: false, compact: true });
  });

  it("zatwierdzona wersja pobiera DOCX tej wersji; „Edytuj” otwiera edytor etapu", async () => {
    mocks.brandedGet.mockResolvedValue({
      data: { status: "finalized", from_generator: true, generated_document_id: 5, edit_revision: 4, version: 2, docx_filename: "CV_Kowalski.docx" },
    });
    rows = [{ id: 5, status: "ready" }];
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Pobierz DOCX/ }));
    await waitFor(() =>
      expect(mocks.downloadAuthenticatedFile).toHaveBeenCalledWith(
        "/api/candidates/stages/21/cv/branded/versions/2/docx?intent=download&surface=card",
        "CV_Kowalski.docx",
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: /Edytuj/ }));
    expect(screen.getByTestId("editor-stub")).toHaveTextContent("editor:21");
  });

  it("odmowa pobrania (409 zgoda) pokazuje polski komunikat serwera", async () => {
    mocks.brandedGet.mockResolvedValue({
      data: { status: "draft", from_generator: true, generated_document_id: 5, edit_revision: 4, version: 1, content_html: "<p>x</p>" },
    });
    rows = [{ id: 5, status: "ready" }];
    mocks.postAuthenticatedDownload.mockRejectedValue({
      response: { status: 409, data: { detail: { code: "consent_required", message: "Dołącz zrzut zgody RODO, aby pobrać CV." } } },
    });
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Pobierz DOCX/ }));
    await waitFor(() =>
      expect(mocks.showError).toHaveBeenCalledWith("Dołącz zrzut zgody RODO, aby pobrać CV."),
    );
    expect(mocks.postAuthenticatedDownload).toHaveBeenCalledWith(
      "/api/candidates/stages/21/cv/branded/preview-docx?intent=download&surface=card",
      { content_html: "<p>x</p>", expected_revision: 4 },
    );
  });

  it("nowsza gotowa generacja: „Użyj nowej wersji” podpina ją do etapu", async () => {
    mocks.brandedGet.mockResolvedValue({
      data: { status: "draft", from_generator: true, generated_document_id: 5, edit_revision: 7, version: 1 },
    });
    rows = [{ id: 5, status: "ready", package_id: 1 }, { id: 9, status: "ready", package_id: 2 }];
    mocks.selectGenerated.mockResolvedValue({
      data: { status: "draft", from_generator: true, generated_document_id: 9, edit_revision: 8, version: 1 },
    });
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: "Użyj nowej wersji" }));
    await waitFor(() => expect(mocks.selectGenerated).toHaveBeenCalledWith(21, 9, 7));
    expect(mocks.showSuccess).toHaveBeenCalledWith("CV podpięte do tej rekrutacji.");
  });

  it("„Wygeneruj ponownie”: panel w karcie, a gotowa wersja sama zastępuje szkic", async () => {
    mocks.brandedGet.mockResolvedValue({
      data: { status: "draft", from_generator: true, generated_document_id: 5, edit_revision: 4, version: 1 },
    });
    mocks.selectGenerated.mockResolvedValue({
      data: { status: "draft", from_generator: true, generated_document_id: 77, edit_revision: 5, version: 1 },
    });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    mocks.apiPost.mockImplementation(async () => {
      // Serwer nie podpina CV do etapu, który ma już szkic — wersja leży obok.
      rows = [{ id: 5, status: "ready", package_id: 5 }, { id: 77, status: "ready", package_id: 77 }];
      return { data: { id: 77, status: "processing", candidate_name: "Jan Kowalski" } };
    });
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Wygeneruj ponownie/ }));
    const panel = await screen.findByTestId("cv-generate-panel");
    expect(screen.queryByTestId("generator-dialog")).toBeNull();
    expect(panel).toHaveTextContent("Nowa wersja zastąpi bieżący szkic, gdy będzie gotowa");
    const generate = within(panel).getByRole("button", { name: /^Generuj$/ });
    await waitFor(() => expect(generate).toBeEnabled());
    await userEvent.click(generate);

    // Ta sama operacja co „Użyj nowej wersji” — z rewizją szkicu, raz.
    await waitFor(() => expect(mocks.selectGenerated).toHaveBeenCalledWith(21, 77, 4));
    expect(mocks.selectGenerated).toHaveBeenCalledTimes(1);
    expect(mocks.showSuccess).toHaveBeenCalledWith("CV podpięte do tej rekrutacji.");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Użyj nowej wersji" })).toBeNull());
  });

  it("nieudana ponowna generacja nie rusza bieżącego CV i mówi dlaczego", async () => {
    mocks.brandedGet.mockResolvedValue({
      data: { status: "draft", from_generator: true, generated_document_id: 5, edit_revision: 4, version: 1 },
    });
    rows = [{ id: 5, status: "ready" }];
    mocks.apiPost.mockImplementation(async () => {
      rows = [{ id: 5, status: "ready" }, { id: 77, status: "failed", error_message: "Model nie odpowiedział" }];
      return { data: { id: 77, status: "processing", candidate_name: "Jan Kowalski" } };
    });
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Wygeneruj ponownie/ }));
    const generate = within(await screen.findByTestId("cv-generate-panel")).getByRole("button", { name: /^Generuj$/ });
    await waitFor(() => expect(generate).toBeEnabled());
    await userEvent.click(generate);
    expect(await screen.findByText(/Nowa wersja nie powstała: Model nie odpowiedział/)).toBeInTheDocument();
    expect(screen.getByText("CV gotowe · szkic")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
    expect(mocks.selectGenerated).not.toHaveBeenCalled();
  });
});

describe("CvToClientCard — jedna liczba rzeczy do sprawdzenia (13.10.2026)", () => {
  const READY = { status: "draft", from_generator: true, generated_document_id: 5, edit_revision: 3, version: 1 };

  it("QC, generator i kontrola AI razem; „MUST-HAVE: X” nie dubluje pozycji QC; „Sprawdź i popraw” → „Do poprawy”", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready", factual_review: { status: "advisory", findings: 7 } }];
    qcChecks = [
      { key: "no_unsupported", label: "Zgodność", severity: "blocking", status: "fail", summary: null, items: [{ term: "AWS" }] },
      { key: "must_in_cv", label: "Wymagania", severity: "warning", status: "fail", summary: null, items: [{ requirement: "Kafka" }] },
      { key: "dates", label: "Daty", severity: "warning", status: "fail", summary: null, muted: true, items: [{ detail: "x" }] },
    ];
    issues = {
      generator_warnings: ["MUST-HAVE: Kafka", "WERYFIKUJ: usunięto „OpenTelemetry”", "Wyróżnienia: pogrubiono 3 terminy."],
      content_review: { status: null, version: null, findings: [{ text: "Przeglądy kodu.", status: "unsupported" }] },
    };
    renderCard();
    // 1 blokada + 1 uwaga QC + 1 uwaga generatora + 1 kontrola AI; wyciszona, informacja i dubel nie.
    expect(await screen.findByTestId("cv-checks-count")).toHaveTextContent("4 rzeczy do sprawdzenia przed wysłaniem");
    // Stary licznik kontroli AI z listy wygenerowanych CV zniknął.
    expect(screen.queryByText(/kontrola AI nie znalazła pokrycia/)).toBeNull();
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/pipeline/stages/21/qc", { params: { transient: true } });

    await userEvent.click(screen.getByRole("button", { name: /Sprawdź i popraw/ }));
    expect(screen.getByTestId("editor-stub")).toHaveTextContent("editor:21");
    expect(mocks.editorProps).toMatchObject({ stageId: 21, initialPanel: "issues" });
  });

  it("zero znaczy zero — tylko gdy oba odczyty się udały", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready" }];
    renderCard();
    expect(await screen.findByTestId("cv-checks-count")).toHaveTextContent("Nic do sprawdzenia przed wysłaniem");
    // „Edytuj” otwiera edytor bez wymuszania panelu.
    await userEvent.click(screen.getByRole("button", { name: /Edytuj/ }));
    expect(mocks.editorProps?.initialPanel).toBeUndefined();
  });

  it("awaria QC nie wygląda jak „nic do sprawdzenia”", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready" }];
    qcError = { response: { status: 500 } };
    renderCard();
    expect(await screen.findByText(/Nie udało się policzyć rzeczy do sprawdzenia/)).toBeInTheDocument();
    expect(screen.queryByText("Nic do sprawdzenia przed wysłaniem")).toBeNull();
    qcError = null;
    await userEvent.click(screen.getByRole("button", { name: "Ponów" }));
    expect(await screen.findByText("Nic do sprawdzenia przed wysłaniem")).toBeInTheDocument();
  });

  it("tylko do odczytu: liczba bez „Sprawdź i popraw”", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready" }];
    issues = { generator_warnings: ["WERYFIKUJ: daty"], content_review: { status: null, version: null, findings: [] } };
    renderCard({ readOnly: true });
    expect(await screen.findByTestId("cv-checks-count")).toHaveTextContent("1 rzecz do sprawdzenia przed wysłaniem");
    expect(screen.queryByRole("button", { name: /Sprawdź i popraw/ })).toBeNull();
  });
});

describe("CvToClientCard — stary szablon", () => {
  it("tylko podgląd i podpowiedź „Wygeneruj CV” — bez edycji i pobrania", async () => {
    mocks.brandedGet.mockResolvedValue({
      data: { status: "draft", from_generator: false, edit_revision: 2, version: 1, content_html: "<p>stary</p>" },
    });
    renderCard();
    expect(await screen.findByText("Stary szablon · tylko odczyt")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Podgląd/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Wygeneruj CV/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edytuj/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Pobierz DOCX/ })).toBeNull();
  });
});

describe("CvToClientCard — plik źródłowy", () => {
  it("pokazuje plik CV kandydata i otwiera oryginał", async () => {
    renderCard();
    expect(await screen.findByText(/Plik CV: Jan_Kowalski_CV\.pdf/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Pokaż oryginał" }));
    expect(screen.getByTestId("original-preview")).toBeInTheDocument();
  });
});

describe("CvToClientCard — CV firmowe pary na innym etapie (runda 11, F23)", () => {
  it("nowy wiersz etapu bez CV pokazuje, pobiera i edytuje CV z etapu źródłowego", async () => {
    mocks.brandedGet.mockImplementation((stageId: number) =>
      Promise.resolve({
        data:
          stageId === 21
            ? { status: "none", edit_revision: 0, version: 1, pair_source_stage_id: 20, pair_source_status: "finalized" }
            : { status: "finalized", from_generator: true, generated_document_id: 5, edit_revision: 4, version: 2, docx_filename: "CV_Kowalski.docx" },
      }),
    );
    rows = [{ id: 5, status: "ready" }];
    renderCard();
    expect(await screen.findByText("CV gotowe · wersja 2")).toBeInTheDocument();
    expect(screen.queryByText(/Jeszcze nie ma CV do klienta/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Generuj CV/ })).toBeNull();
    expect(mocks.brandedGet).toHaveBeenCalledWith(20);
    await userEvent.click(screen.getByRole("button", { name: /Pobierz DOCX/ }));
    await waitFor(() =>
      expect(mocks.downloadAuthenticatedFile).toHaveBeenCalledWith(
        "/api/candidates/stages/20/cv/branded/versions/2/docx?intent=download&surface=card",
        "CV_Kowalski.docx",
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: /Edytuj/ }));
    expect(screen.getByTestId("editor-stub")).toHaveTextContent("editor:20");
  });
});

describe("CvToClientCard — „Użyj innego CV” (12.10.2026)", () => {
  const COPY = {
    status: "draft",
    from_generator: true,
    generated_document_id: null,
    source: "generator",
    edit_revision: 1,
    version: 1,
    content_html: "<p>CV po poprawkach</p>",
    origin: { kind: "stage_copy", label: "ZOB-9000", job_id: 300, selected_at: "2026-10-12T10:00:00Z" },
  };

  it("brak CV, a osoba ma CV w innej rekrutacji: pasek i „Użyj tego CV” bez pytania", async () => {
    mocks.sources.mockResolvedValue({
      data: {
        items: [
          { job_id: 300, stage_id: 31, job_title: "DevOps Engineer", reference_number: "ZOB-9000", status: "finalized", version: 2 },
        ],
      },
    });
    mocks.selectStageCv.mockResolvedValue({ data: COPY });
    renderCard();

    const hint = await screen.findByTestId("ready-cv-hint");
    expect(hint).toHaveTextContent("Ta osoba ma już gotowe CV");
    expect(hint).toHaveTextContent("DevOps Engineer · zatwierdzone · wersja 2");
    await userEvent.click(screen.getByRole("button", { name: "Użyj tego CV" }));

    // Rekrutacja źródłowa, wiersz etapu tej pary i jego rewizja; nie ma czego zastępować.
    await waitFor(() => expect(mocks.selectStageCv).toHaveBeenCalledWith(21, 300, 0));
    expect(screen.queryByText("Zastąpić CV do klienta?")).toBeNull();
    expect(await screen.findByTestId("cv-origin-badge")).toHaveTextContent("z rekrutacji ZOB-9000");
    expect(screen.queryByTestId("ready-cv-hint")).toBeNull();
  });

  it("auto-CV nieprzejrzane, a w profilu leży plik Word: podmiana po potwierdzeniu", async () => {
    mocks.brandedGet.mockResolvedValue({
      data: { status: "draft", from_generator: true, generated_document_id: 5, edit_revision: 3, version: 1, content_html: "<p>CV</p>" },
    });
    rows = [{ id: 5, status: "ready", origin: "auto", needs_review: true, job_id: 42 }];
    personGenerated = rows;
    documents = [
      { id: 2, filename: "CV_B2B_Jan_Kowalski.docx", is_primary: false, uploaded_at: "2026-09-28T10:00:00Z", created_at: "2026-09-28T10:00:00Z", external_source: null },
    ];
    mocks.selectDocument.mockResolvedValue({
      data: { ...COPY, source: "document", from_generator: false, origin: { kind: "profile_file", label: "CV_B2B_Jan_Kowalski.docx" } },
    });
    renderCard();

    // Generacja TEJ rekrutacji nie jest „innym CV” — podpowiedzią jest plik.
    expect(await screen.findByTestId("ready-cv-hint")).toHaveTextContent("CV_B2B_Jan_Kowalski.docx");
    await userEvent.click(screen.getByRole("button", { name: "Użyj tego CV" }));
    expect(await screen.findByText("Zastąpić CV do klienta?")).toBeInTheDocument();
    expect(mocks.selectDocument).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Zastąp" }));

    await waitFor(() => expect(mocks.selectDocument).toHaveBeenCalledWith(21, 2, 3));
    expect(await screen.findByTestId("cv-origin-badge")).toHaveTextContent("z pliku Word");
  });

  it("CV wybrane świadomie: bez paska, z plakietką; „Użyj innego CV” otwiera okno wyboru", async () => {
    mocks.brandedGet.mockResolvedValue({ data: COPY });
    // Starsze auto-CV tej pary nie jest „nowszą wersją” świeżo wybranej kopii.
    rows = [{ id: 5, status: "ready", origin: "auto", job_id: 42, created_at: "2026-10-12T08:00:00Z" }];
    renderCard();

    expect(await screen.findByTestId("cv-origin-badge")).toHaveTextContent("z rekrutacji ZOB-9000");
    expect(screen.getByText(/w wersji po poprawkach rekrutera/)).toBeInTheDocument();
    expect(screen.queryByTestId("ready-cv-hint")).toBeNull();
    expect(screen.queryByRole("button", { name: "Użyj nowej wersji" })).toBeNull();
    expect(mocks.sources).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: /Użyj innego CV/ }));
    expect(screen.getByTestId("use-other-cv-dialog")).toBeInTheDocument();
    expect(mocks.otherDialogProps).toMatchObject({ candidateId: 121, candidateName: "Jan Kowalski", replaces: true });
  });

  it("kopia bez zgody: pobranie zablokowane, a zgoda idzie na CV etapu, nie na dokument generatora", async () => {
    mocks.brandedGet.mockResolvedValue({
      data: { ...COPY, consent_required: true, consent_attached: false, consent_missing: true },
    });
    renderCard();

    expect(await screen.findByText(/Zgoda RODO: brak zrzutu/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pobierz DOCX/ })).toBeDisabled();
    expect(mocks.consentProps).toMatchObject({ stageCopy: { candidateId: 121, stageId: 21 }, hasConsent: false });
    expect(mocks.consentProps?.generatedId).toBeUndefined();
  });

  it("brak CV i brak gotowych: „Użyj gotowego CV” prowadzi do okna z wgraniem pliku", async () => {
    renderCard();

    await userEvent.click(await screen.findByRole("button", { name: /Użyj gotowego CV/ }));
    expect(screen.getByTestId("use-other-cv-dialog")).toBeInTheDocument();
    expect(mocks.otherDialogProps).toMatchObject({ replaces: false });
    expect(screen.queryByTestId("ready-cv-hint")).toBeNull();
  });

  it("tylko do odczytu: bez paska, bez okna i bez pytania o gotowe CV", async () => {
    mocks.sources.mockResolvedValue({
      data: { items: [{ job_id: 300, stage_id: 31, job_title: "DevOps Engineer", status: "finalized" }] },
    });
    renderCard({ readOnly: true });

    expect(await screen.findByText(/Jeszcze nie ma CV do klienta/)).toBeInTheDocument();
    expect(screen.queryByTestId("ready-cv-hint")).toBeNull();
    expect(screen.queryByRole("button", { name: /Użyj gotowego CV/ })).toBeNull();
    expect(mocks.sources).not.toHaveBeenCalled();
  });
});
