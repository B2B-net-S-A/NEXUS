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
 *
 * 14.10.2026 (Edytor CV 3, „Ekran 5”): gotowe CV = miniatura pierwszej strony
 * (klik otwiera strony), „Otwórz i popraw”, „Pobierz Word” i menu „⋯” (PDF,
 * inne CV, historia wersji, ponowna generacja); panel „Z czego powstało”
 * zwinięty do jednego zdania z „Zmień”.
 */

import { act, configure, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CvAiSourceFile, CvAiSourceUsedFile } from "@/lib/cv-ai-sources";

import { useAuthStore } from "@/store/auth";

// Panel generacji pyta o kilka rzeczy naraz — pod obciążeniem sekunda to za mało.
configure({ asyncUtilTimeout: 5000 });

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  brandedGet: vi.fn(),
  originalGet: vi.fn(),
  selectGenerated: vi.fn(),
  restorePrevious: vi.fn(),
  discard: vi.fn(),
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
  previewLoad: null as null | (() => Promise<Blob>),
  previewLoadPdf: null as null | (() => Promise<Blob>),
  thumbProps: null as null | {
    load: () => Promise<Blob>;
    onOpen: () => void;
    onPages?: (count: number) => void;
    label?: string;
  },
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: mocks.apiGet, post: mocks.apiPost },
  candidateStageCvApi: {
    branded: {
      get: (...a: unknown[]) => mocks.brandedGet(...a),
      selectGenerated: (...a: unknown[]) => mocks.selectGenerated(...a),
      restorePrevious: (...a: unknown[]) => mocks.restorePrevious(...a),
      discard: (...a: unknown[]) => mocks.discard(...a),
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
// Podgląd pliku (docx-preview) — atrapa trzyma loader i pokazuje zapas.
vi.mock("@/components/v2/cv/CvPagesPreview", () => ({
  CvPagesPreview: (props: {
    loadPdf: () => Promise<Blob>;
    loadDocx: () => Promise<Blob>;
    fallback?: React.ReactNode;
  }) => {
    mocks.previewLoadPdf = props.loadPdf;
    mocks.previewLoad = props.loadDocx;
    return <div data-testid="pages-preview">{props.fallback}</div>;
  },
}));

// Miniatura (pdf.js) ma własny test — atrapa trzyma loader i otwiera strony.
vi.mock("@/components/v2/cv/CvFirstPageThumb", () => ({
  CvFirstPageThumb: (props: NonNullable<typeof mocks.thumbProps>) => {
    mocks.thumbProps = props;
    return (
      <button type="button" aria-label={props.label ?? "Otwórz strony CV"} onClick={props.onOpen}>
        miniatura
      </button>
    );
  },
}));

import { CvToClientCard } from "@/components/v2/recruitment/CvToClientCard";
import { cvToClientRowsQueryKey, stageBrandedQueryKey } from "@/lib/cv-to-client";

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
let aiSources: typeof AI_SOURCES & { cv_files?: CvAiSourceFile[]; last_source_cv?: CvAiSourceUsedFile | null } = AI_SOURCES;
// Liczba rzeczy do sprawdzenia: QC karty (bez zapisu przebiegu) i uwagi edytora.
let qcChecks: unknown[] = [];
let qcError: unknown = null;
let issues = { generator_warnings: [] as string[], content_review: { status: null, version: null, findings: [] as unknown[] } };
// Źródła „Użyj innego CV”: wszystkie generacje osoby i pliki CV z profilu.
let personGenerated: Row[] = [];
let documents: Row[] = [];

function renderCard(
  overrides: Partial<React.ComponentProps<typeof CvToClientCard>> = {},
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
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

/** Menu „⋯” karty z gotowym CV. */
async function chooseFromMore(name: string | RegExp) {
  await userEvent.click(await screen.findByRole("button", { name: "Więcej akcji CV" }));
  await userEvent.click(await screen.findByRole("menuitem", { name }));
}

/** Zwinięty panel „Z czego powstało” → przełączniki, obróbka i język. */
async function expandSources(panel: HTMLElement) {
  await userEvent.click(await within(panel).findByRole("button", { name: "Zmień" }));
}

/** Trzy potwierdzenia przed „Generuj” (21.10.2026): plik, odpowiedzi, notatki. */
async function confirmAll(panel: HTMLElement) {
  await userEvent.click(await within(panel).findByRole("button", { name: "Potwierdź plik" }));
  await userEvent.click(within(panel).getByRole("button", { name: /^Potwierdź (odpowiedzi|bez odpowiedzi)$/ }));
  await userEvent.click(within(panel).getByRole("button", { name: "Nie mam nic do dodania" }));
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
  mocks.thumbProps = null;
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

    // Zwinięty panel: jedno zdanie z tych samych przełączników, które pójdą w żądaniu.
    expect(await within(panel).findByTestId("cv-generate-summary")).toHaveTextContent(
      "Z oryginału CV, Championa, screeningu i notatek · Pod rekrutację · polski · Zmień",
    );
    expect(within(panel).queryByRole("region", { name: "Z czego powstało" })).toBeNull();
    // 21.10.2026: „Generuj” czeka na trzy potwierdzenia, potem działa bez rozwijania.
    expect(within(panel).getByRole("button", { name: /^Generuj$/ })).toBeDisabled();
    expect(await within(panel).findByTestId("cv-confirm-left")).toHaveTextContent(
      "Potwierdź jeszcze: plik, odpowiedzi, notatki",
    );
    await confirmAll(panel);
    expect(within(panel).getByTestId("cv-confirm-count")).toHaveTextContent("Potwierdzone 3 z 3");
    await waitFor(() => expect(within(panel).getByRole("button", { name: /^Generuj$/ })).toBeEnabled());
    await expandSources(panel);

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
    await expandSources(panel);
    await userEvent.click(await within(panel).findByRole("switch", { name: "Transkrypty rozmów" }));
    await userEvent.click(within(panel).getByRole("switch", { name: "Odpowiedzi ze screeningu" }));
    await confirmAll(panel);
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
    expect(await within(panel).findByTestId("cv-generate-summary")).toHaveTextContent(
      "Z oryginału CV, Championa, notatek, transkryptów i prepu · Pod rekrutację · polski",
    );
    await expandSources(panel);
    expect(await within(panel).findByRole("switch", { name: "Odpowiedzi ze screeningu" })).not.toBeChecked();
    expect(within(panel).getByRole("switch", { name: "Transkrypty rozmów" })).toBeChecked();
    expect(within(panel).getByRole("switch", { name: "Podsumowania prepu" })).toBeChecked();
  });

  it("21.10.2026: wybrany plik i dodatkowa notatka idą w generacji; zmiana po potwierdzeniu zdejmuje potwierdzenie", async () => {
    aiSources = {
      ...AI_SOURCES,
      cv_files: [
        {
          document_id: 30,
          filename: "Jan_Kowalski_B2B_Orlen.docx",
          uploaded_at: "2026-10-20T10:00:00Z",
          is_primary: true,
          outdated: false,
          stage_original: false,
        },
        {
          document_id: 31,
          filename: "Jan_Kowalski_CV.pdf",
          uploaded_at: "2026-09-12T10:00:00Z",
          is_primary: false,
          outdated: false,
          stage_original: true,
        },
      ],
    };
    mocks.apiPost.mockImplementation(async (url: string) => {
      if (url === "/api/notes") return { data: { id: 1 } };
      if (url === "/api/cv-generator/generate") return { data: { id: 77, status: "processing", candidate_name: "Jan Kowalski" } };
      throw new Error(`unexpected POST ${url}`);
    });
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Generuj CV/ }));
    const panel = await screen.findByTestId("cv-generate-panel");
    const fileStep = await within(panel).findByTestId("cv-confirm-file");
    // Domyślnie kopia „Oryginał CV” rekrutacji, nie nowsze główne CV.
    expect(within(fileStep).getByRole("radio", { name: /Jan_Kowalski_CV\.pdf/ })).toBeChecked();
    expect(fileStep).toHaveTextContent("Oryginał CV w tej rekrutacji");
    await userEvent.click(within(fileStep).getByRole("radio", { name: /Jan_Kowalski_B2B_Orlen/ }));
    await userEvent.click(within(panel).getByRole("button", { name: "Potwierdź plik" }));
    expect(within(panel).getByTestId("cv-confirm-file")).toHaveTextContent("Plik CV: Jan_Kowalski_B2B_Orlen.docx");
    await userEvent.click(within(panel).getByRole("button", { name: "Potwierdź odpowiedzi" }));
    await userEvent.type(within(panel).getByRole("textbox", { name: "Dodatkowe notatki do CV" }), "Migracja Jenkinsa");
    await userEvent.click(within(panel).getByRole("button", { name: "Potwierdź notatki" }));
    expect(within(panel).getByTestId("cv-confirm-count")).toHaveTextContent("Potwierdzone 3 z 3");

    // Edycja notatki po potwierdzeniu wymaga potwierdzenia jeszcze raz.
    await userEvent.click(within(panel).getByRole("button", { name: "Edytuj notatki" }));
    await userEvent.type(within(panel).getByRole("textbox", { name: "Dodatkowe notatki do CV" }), " do GitHub Actions");
    expect(within(panel).getByTestId("cv-confirm-count")).toHaveTextContent("Potwierdzone 2 z 3");
    expect(within(panel).getByRole("button", { name: /^Generuj$/ })).toBeDisabled();
    await userEvent.click(within(panel).getByRole("button", { name: "Potwierdź notatki" }));

    const generate = within(panel).getByRole("button", { name: /^Generuj$/ });
    await waitFor(() => expect(generate).toBeEnabled());
    await userEvent.click(generate);
    await waitFor(() => expect(generatePosts()).toHaveLength(1));
    expect(generatePosts()[0][1]).toMatchObject({ cv_document_id: 30 });
    // Notatka zapisana w rekrutacji PRZED generacją.
    const notePosts = mocks.apiPost.mock.calls.filter(([url]) => url === "/api/notes");
    expect(notePosts).toHaveLength(1);
    expect(notePosts[0][1]).toMatchObject({ content: "Migracja Jenkinsa do GitHub Actions", job_id: 42 });
    const order = mocks.apiPost.mock.calls.map(([url]) => url);
    expect(order.indexOf("/api/notes")).toBeLessThan(order.indexOf("/api/cv-generator/generate"));
  });

  // Audyt 22.10 (F66): świeżo wgrany Oryginał CV, którego lista generatora
  // jeszcze nie zna — „Generuj” było wyłączone bez słowa.
  it("plik spoza listy generatora: panel pyta listę od nowa, a potem mówi, czego brak", async () => {
    const fresh: CvAiSourceFile = {
      document_id: 32, filename: "Jan_CV_nowe.pdf", uploaded_at: null, is_primary: true, outdated: false, stage_original: true,
    };
    aiSources = { ...AI_SOURCES, original_cv: { ...AI_SOURCES.original_cv, document_id: 32, filename: "Jan_CV_nowe.pdf" }, cv_files: [fresh] };
    let sourcesCalls = 0;
    const base = mocks.apiGet.getMockImplementation()!;
    mocks.apiGet.mockImplementation((url: string, config?: { params?: Record<string, unknown> }) => {
      if (url === "/api/cv-generator/candidates/121/cv-sources") {
        sourcesCalls += 1;
        return Promise.resolve({ data: CV_SOURCES });
      }
      return base(url, config);
    });
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Generuj CV/ }));
    const panel = await screen.findByTestId("cv-generate-panel");
    await confirmAll(panel);
    await waitFor(() => expect(sourcesCalls).toBe(2));
    expect(await within(panel).findByTestId("cv-file-not-in-generator")).toHaveTextContent(
      "Generator nie widzi tego pliku",
    );
    expect(within(panel).getByRole("button", { name: /^Generuj$/ })).toBeDisabled();
  });

  it("plik, który lista generatora poznaje po odświeżeniu: „Generuj” się odblokowuje", async () => {
    const fresh: CvAiSourceFile = {
      document_id: 32, filename: "Jan_CV_nowe.pdf", uploaded_at: null, is_primary: true, outdated: false, stage_original: true,
    };
    aiSources = { ...AI_SOURCES, original_cv: { ...AI_SOURCES.original_cv, document_id: 32, filename: "Jan_CV_nowe.pdf" }, cv_files: [fresh] };
    let sourcesCalls = 0;
    const base = mocks.apiGet.getMockImplementation()!;
    mocks.apiGet.mockImplementation((url: string, config?: { params?: Record<string, unknown> }) => {
      if (url === "/api/cv-generator/candidates/121/cv-sources") {
        sourcesCalls += 1;
        const list = sourcesCalls === 1 ? CV_SOURCES : [...CV_SOURCES, { id: 32, filename: "Jan_CV_nowe.pdf", is_primary: true, uploaded_at: null }];
        return Promise.resolve({ data: list });
      }
      return base(url, config);
    });
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Generuj CV/ }));
    const panel = await screen.findByTestId("cv-generate-panel");
    await confirmAll(panel);
    const generate = within(panel).getByRole("button", { name: /^Generuj$/ });
    await waitFor(() => expect(generate).toBeEnabled());
    await userEvent.click(generate);
    await waitFor(() => expect(generatePosts()).toHaveLength(1));
    expect(generatePosts()[0][1]).toMatchObject({ cv_document_id: 32 });
  });

  it("odmowa serwera (reguła klienta, 422) stoi w panelu, a panel zostaje otwarty", async () => {
    mocks.apiPost.mockRejectedValue({
      response: { status: 422, data: { detail: "Ten klient wymaga numeru projektu w CV." } },
    });
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Generuj CV/ }));
    const panel = await screen.findByTestId("cv-generate-panel");
    await confirmAll(panel);
    const generate = within(panel).getByRole("button", { name: /^Generuj$/ });
    await waitFor(() => expect(generate).toBeEnabled());
    await userEvent.click(generate);
    expect(await within(panel).findByRole("alert")).toHaveTextContent("Ten klient wymaga numeru projektu w CV.");
    expect(mocks.showError).toHaveBeenCalledWith("Ten klient wymaga numeru projektu w CV.");
    // Odmowa rozwija panel sam — rekruter ma co zmienić.
    expect(within(panel).getByRole("region", { name: "Z czego powstało" })).toBeInTheDocument();
    expect(within(panel).queryByTestId("cv-generate-summary")).toBeNull();
  });

  it("tej rekrutacji nie ma na liście procesów osoby — CV nie powstanie dla innego procesu", async () => {
    recruitments = [{ ...RECRUITMENT, stage_id: 99, job_id: 900 }];
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Generuj CV/ }));
    const panel = await screen.findByTestId("cv-generate-panel");
    expect(await within(panel).findByTestId("cvgen-missing")).toHaveTextContent(/tej rekrutacji nie ma na liście procesów/);
    expect(within(panel).getByRole("button", { name: /^Generuj$/ })).toBeDisabled();
    // Brak do uzupełnienia = panel rozwinięty od razu.
    expect(within(panel).queryByTestId("cv-generate-summary")).toBeNull();
    expect(within(panel).getByRole("group", { name: "Obróbka treści" })).toBeInTheDocument();
  });

  it("awaria odczytu źródeł rozwija panel z komunikatem, a „Generuj” działa (domyślne serwera)", async () => {
    const base = mocks.apiGet.getMockImplementation()!;
    mocks.apiGet.mockImplementation((url: string, config?: { params?: Record<string, unknown> }) =>
      /\/cv\/ai-sources$/.test(url) ? Promise.reject({ response: { status: 500 } }) : base(url, config),
    );
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Generuj CV/ }));
    const panel = await screen.findByTestId("cv-generate-panel");
    expect(await within(panel).findByText(/Nie udało się wczytać źródeł/)).toBeInTheDocument();
    expect(within(panel).queryByTestId("cv-generate-summary")).toBeNull();
    // Plik z listy generatora, odpowiedzi „nie udało się sprawdzić” — potwierdzenia dalej działają.
    expect(within(panel).getByTestId("cv-confirm-answers")).toHaveTextContent("nie udało się sprawdzić");
    await confirmAll(panel);
    await waitFor(() => expect(within(panel).getByRole("button", { name: /^Generuj$/ })).toBeEnabled());
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
    const facts = await screen.findByTestId("cv-ready-facts");
    expect(facts).toHaveTextContent("szkic");
    expect(facts).toHaveTextContent("Pod rekrutację · EN");
    expect(screen.getByText("wygenerowane automatycznie — sprawdź przed wysyłką")).toBeInTheDocument();
    expect(await screen.findByTestId("cv-checks-count")).toHaveTextContent("2 rzeczy do sprawdzenia przed wysłaniem");
    expect(screen.getByRole("button", { name: /Pobierz Word/ })).toBeDisabled();
    // Strony (miniatura) i edycja działają bez zgody.
    expect(screen.getByRole("button", { name: "Otwórz strony CV — Jan Kowalski" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Otwórz i popraw/ })).toBeEnabled();
    expect(screen.getByText(/Zgoda RODO: brak zrzutu/)).toBeInTheDocument();
    expect(mocks.consentProps).toMatchObject({ generatedId: 5, hasConsent: false, compact: true });
    // Bez zgody serwer i tak odpowie 409 — miniatura nie pyta o PDF.
    await expect(mocks.thumbProps!.load()).rejects.toThrow();
    expect(mocks.apiPost).not.toHaveBeenCalled();
    // „Pobierz PDF” w „⋯” też czeka na zgodę.
    await userEvent.click(screen.getByRole("button", { name: "Więcej akcji CV" }));
    expect(await screen.findByRole("menuitem", { name: /Pobierz PDF/ })).toHaveAttribute("aria-disabled", "true");
  });

  it("zatwierdzona wersja pobiera Word tej wersji; „Otwórz i popraw” otwiera edytor etapu", async () => {
    mocks.brandedGet.mockResolvedValue({
      data: { status: "finalized", from_generator: true, generated_document_id: 5, edit_revision: 4, version: 2, docx_filename: "CV_Kowalski.docx" },
    });
    rows = [{ id: 5, status: "ready" }];
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Pobierz Word/ }));
    await waitFor(() =>
      expect(mocks.downloadAuthenticatedFile).toHaveBeenCalledWith(
        "/api/candidates/stages/21/cv/branded/versions/2/docx?intent=download&surface=card",
        "CV_Kowalski.docx",
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: /Otwórz i popraw/ }));
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
    await userEvent.click(await screen.findByRole("button", { name: /Pobierz Word/ }));
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

  it("podmiana szkicu niesie wersję z chwili zlecenia — edycja w trakcie generacji daje 409, nie nadpisanie", async () => {
    // Przegląd PR 4: wersja szkicu czytana przy podpięciu zawsze przechodziła
    // `check_revision`, więc autozapis z edytora w trakcie generacji ginął.
    mocks.brandedGet.mockResolvedValue({
      data: { status: "draft", from_generator: true, generated_document_id: 5, edit_revision: 4, version: 1 },
    });
    mocks.selectGenerated.mockRejectedValue({ response: { status: 409, data: { detail: "Szkic zmienił się." } } });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    mocks.apiPost.mockImplementation(async () => {
      rows = [{ id: 5, status: "ready", package_id: 5 }, { id: 77, status: "processing", package_id: 77 }];
      return { data: { id: 77, status: "processing", candidate_name: "Jan Kowalski" } };
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <CvToClientCard
          stageId={21}
          candidateId={121}
          candidateName="Jan Kowalski"
          jobId={42}
          jobTitle="Senior Java Developer"
          readOnly={false}
        />
      </QueryClientProvider>,
    );
    await chooseFromMore(/Wygeneruj ponownie/);
    const panel = await screen.findByTestId("cv-generate-panel");
    await confirmAll(panel);
    const generate = within(panel).getByRole("button", { name: /^Generuj$/ });
    await waitFor(() => expect(generate).toBeEnabled());
    await userEvent.click(generate);
    await waitFor(() => expect(mocks.apiPost).toHaveBeenCalled());

    // Autozapis edytora w trakcie generacji: szkic ma już wersję 5.
    mocks.brandedGet.mockResolvedValue({
      data: { status: "draft", from_generator: true, generated_document_id: 5, edit_revision: 5, version: 1 },
    });
    await client.invalidateQueries({ queryKey: stageBrandedQueryKey(21) });
    rows = [{ id: 5, status: "ready", package_id: 5 }, { id: 77, status: "ready", package_id: 77 }];
    await client.invalidateQueries({ queryKey: cvToClientRowsQueryKey(121, 42) });

    await waitFor(() => expect(mocks.selectGenerated).toHaveBeenCalledWith(21, 77, 4));
    expect(mocks.selectGenerated).toHaveBeenCalledTimes(1);
    expect(mocks.showError).toHaveBeenCalledWith("Szkic zmienił się.");
  }, 20000);

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
    await chooseFromMore(/Wygeneruj ponownie/);
    const panel = await screen.findByTestId("cv-generate-panel");
    expect(screen.queryByTestId("generator-dialog")).toBeNull();
    expect(panel).toHaveTextContent("Nowa wersja zastąpi bieżący szkic, gdy będzie gotowa");
    await confirmAll(panel);
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
    await chooseFromMore(/Wygeneruj ponownie/);
    const regenPanel = await screen.findByTestId("cv-generate-panel");
    await confirmAll(regenPanel);
    const generate = within(regenPanel).getByRole("button", { name: /^Generuj$/ });
    await waitFor(() => expect(generate).toBeEnabled());
    await userEvent.click(generate);
    expect(await screen.findByText(/Nowa wersja nie powstała: Model nie odpowiedział/)).toBeInTheDocument();
    expect(screen.getByTestId("cv-ready-facts")).toHaveTextContent("szkic");
    // Ponowienie stoi przy komunikacie, nie tylko w „⋯”.
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
    expect(mocks.selectGenerated).not.toHaveBeenCalled();
  });
});

describe("CvToClientCard — „Napisz od nowa” (Edytor CV 3, PR 5)", () => {
  const DRAFT = { status: "draft", from_generator: true, generated_document_id: 5, edit_revision: 4, version: 1 };

  it("pole w karcie: notatka z uwagą, generacja sama rusza, poprawki zostają, „Wróć do poprzedniej”", async () => {
    mocks.brandedGet.mockResolvedValue({ data: DRAFT });
    mocks.selectGenerated.mockResolvedValue({
      data: {
        ...DRAFT,
        generated_document_id: 77,
        edit_revision: 5,
        rewrite: { kept: ["Logistyka Przykład"], recognized: true, can_restore: true },
      },
    });
    mocks.restorePrevious.mockResolvedValue({ data: { ...DRAFT, edit_revision: 6 } });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    const posts: Array<[string, unknown]> = [];
    mocks.apiPost.mockImplementation(async (url: string, body: unknown) => {
      posts.push([url, body]);
      if (url === "/api/notes") return { data: { id: 1 } };
      rows = [{ id: 5, status: "ready", package_id: 5 }, { id: 77, status: "ready", package_id: 77 }];
      return { data: { id: 77, status: "processing", candidate_name: "Jan Kowalski" } };
    });
    renderCard();
    const form = await screen.findByRole("form", { name: "Napisz od nowa" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Co poprawić?" }), "krócej, więcej o Kafce");
    await userEvent.click(within(form).getByRole("button", { name: /Napisz od nowa/ }));

    // Panel w trybie „Napisz od nowa” rusza sam — bez drugiego kliknięcia.
    expect(await screen.findByTestId("cv-rewrite-instruction")).toHaveTextContent("„krócej, więcej o Kafce”");
    await waitFor(() => expect(posts.map(([url]) => url)).toEqual(["/api/notes", "/api/cv-generator/generate"]));
    expect(posts[0][1]).toMatchObject({ content: "Uwaga do CV: krócej, więcej o Kafce", job_id: 42 });
    expect(posts[1][1]).toMatchObject({ instruction: "krócej, więcej o Kafce" });

    await waitFor(() =>
      expect(mocks.selectGenerated).toHaveBeenCalledWith(21, 77, 4, undefined, { keepEdits: true }),
    );
    const bar = await screen.findByTestId("cv-rewrite-result");
    expect(bar).toHaveTextContent("Nowa wersja CV. „Logistyka Przykład” zostało w Twojej wersji.");
    expect(mocks.showSuccess).not.toHaveBeenCalledWith("CV podpięte do tej rekrutacji.");

    await userEvent.click(within(bar).getByRole("button", { name: /Wróć do poprzedniej/ }));
    await waitFor(() => expect(mocks.restorePrevious).toHaveBeenCalledWith(21, 5));
    expect(mocks.showSuccess).toHaveBeenCalledWith("Przywrócono poprzednią wersję CV.");
    await waitFor(() => expect(screen.queryByTestId("cv-rewrite-result")).toBeNull());
  }, 20000);

  it("nowa wersja bez rozpoznanych poprawek mówi to wprost", async () => {
    mocks.brandedGet.mockResolvedValue({ data: DRAFT });
    mocks.selectGenerated.mockResolvedValue({
      data: { ...DRAFT, generated_document_id: 77, edit_revision: 5, rewrite: { kept: [], recognized: false, can_restore: true } },
    });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    mocks.apiPost.mockImplementation(async () => {
      rows = [{ id: 5, status: "ready", package_id: 5 }, { id: 77, status: "ready", package_id: 77 }];
      return { data: { id: 77, status: "processing", candidate_name: "Jan Kowalski" } };
    });
    renderCard();
    const form = await screen.findByRole("form", { name: "Napisz od nowa" });
    // Pusta uwaga też działa: nowa wersja z zachowaniem poprawek.
    await userEvent.click(within(form).getByRole("button", { name: /Napisz od nowa/ }));
    expect(await screen.findByTestId("cv-rewrite-result")).toHaveTextContent(
      "Ręcznych poprawek nie dało się rozpoznać — to cała nowa wersja.",
    );
    expect(mocks.apiPost).not.toHaveBeenCalledWith("/api/notes", expect.anything());
  }, 20000);

  it("„Napisz od nowa” z asystenta w edytorze trafia do tego samego panelu", async () => {
    mocks.brandedGet.mockResolvedValue({ data: DRAFT });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Otwórz i popraw/ }));
    await screen.findByTestId("editor-stub");
    const onRewrite = mocks.editorProps?.onRewrite as ((instruction: string) => void) | undefined;
    expect(onRewrite).toBeTypeOf("function");
    act(() => onRewrite?.("więcej o Kafce"));
    expect(await screen.findByTestId("cv-rewrite-instruction")).toHaveTextContent("„więcej o Kafce”");
    // Edytor zamknął się sam (zapisany szkic), panel pracuje w karcie.
    expect(screen.queryByTestId("editor-stub")).toBeNull();
  });

  /** Odczyt `url` przychodzi dopiero po `ms` — reszta jak w `beforeEach`. */
  function slowGet(match: (url: string) => boolean, data: unknown, ms = 400) {
    const base = mocks.apiGet.getMockImplementation()!;
    mocks.apiGet.mockImplementation((url: string, config?: { params?: Record<string, unknown> }) =>
      match(url)
        ? new Promise((resolve) => setTimeout(() => resolve({ data }), ms))
        : base(url, config),
    );
  }

  async function startRewrite(text: string) {
    const form = await screen.findByRole("form", { name: "Napisz od nowa" });
    if (text) await userEvent.type(within(form).getByRole("textbox", { name: "Co poprawić?" }), text);
    await userEvent.click(within(form).getByRole("button", { name: /Napisz od nowa/ }));
  }

  // Przegląd PR 5: start ruszał, zanim przyszła reguła klienta — z pominięciem zgody RODO.
  it("reguła klienta wymaga zgody RODO: panel czeka na rekrutera, nie generuje sam", async () => {
    mocks.brandedGet.mockResolvedValue({ data: DRAFT });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    slowGet((url) => url.endsWith("/rule-for-generation"), { is_active: true, requires_rodo_consent_block: true });
    renderCard();
    await startRewrite("krócej");
    const panel = await screen.findByTestId("cv-generate-panel");
    await act(() => new Promise((resolve) => setTimeout(resolve, 900)));
    expect(mocks.apiPost).not.toHaveBeenCalled();
    expect(panel).toBeInTheDocument();
  }, 20000);

  // Przegląd PR 5: start brał domyślne sprzed odczytu polityki (język, numer projektu).
  it("polityka klienta przychodzi ostatnia: generacja bierze jej język i numer projektu", async () => {
    mocks.brandedGet.mockResolvedValue({ data: DRAFT });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    slowGet((url) => url === "/api/cv-generator/policy", {
      managed: true,
      effective_policy: { cv_language: "en" },
      project_ref: "PRJ-9",
    });
    renderCard();
    await startRewrite("");
    await waitFor(() => expect(mocks.apiPost).toHaveBeenCalledWith("/api/cv-generator/generate", expect.anything(), expect.anything()));
    const payload = mocks.apiPost.mock.calls.find(([url]) => url === "/api/cv-generator/generate")![1];
    expect(payload).toMatchObject({ language: "en", project_ref: "PRJ-9" });
  }, 20000);

  // Audyt 22.10 (F65): „Napisz od nowa” brało plik domyślny zamiast pliku,
  // z którego powstało poprawiane CV.
  const CV_FILES: CvAiSourceFile[] = [
    { document_id: 31, filename: "Jan_Kowalski_CV.pdf", uploaded_at: null, is_primary: true, outdated: false, stage_original: true },
    { document_id: 30, filename: "stare.docx", uploaded_at: null, is_primary: false, outdated: false, stage_original: false },
  ];

  it("„Napisz od nowa” pisze z pliku, z którego powstało poprawiane CV", async () => {
    mocks.brandedGet.mockResolvedValue({ data: DRAFT });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    aiSources = {
      ...AI_SOURCES,
      cv_files: CV_FILES,
      last_source_cv: { document_id: 30, filename: "stare.docx", outdated: false, stage_original: false, removed: false },
    };
    renderCard();
    await startRewrite("");
    await waitFor(() => expect(generatePosts()).toHaveLength(1));
    expect(generatePosts()[0][1]).toMatchObject({ cv_document_id: 30 });
  }, 20000);

  it("„Napisz od nowa”: plik poprzedniego CV usunięty z profilu — wraca Oryginał CV", async () => {
    mocks.brandedGet.mockResolvedValue({ data: DRAFT });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    aiSources = {
      ...AI_SOURCES,
      cv_files: CV_FILES,
      last_source_cv: { document_id: 99, filename: "usuniete.pdf", outdated: false, stage_original: false, removed: true },
    };
    renderCard();
    await startRewrite("");
    await waitFor(() => expect(generatePosts()).toHaveLength(1));
    expect(generatePosts()[0][1]).toMatchObject({ cv_document_id: 31 });
  }, 20000);

  // Przegląd PR 5: każde ponowienie po błędzie dopisywało kolejną notatkę „Uwaga do CV”.
  it("ponowienie po błędzie nie zapisuje uwagi drugi raz", async () => {
    mocks.brandedGet.mockResolvedValue({ data: DRAFT });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    let attempt = 0;
    mocks.apiPost.mockImplementation(async (url: string) => {
      if (url === "/api/notes") return { data: { id: 1 } };
      attempt += 1;
      if (attempt === 1) throw { response: { status: 422, data: { detail: "Chwilowy błąd." } } };
      return { data: { id: 77, status: "processing", candidate_name: "Jan Kowalski" } };
    });
    renderCard();
    await startRewrite("krócej");
    const panel = await screen.findByTestId("cv-generate-panel");
    expect(await within(panel).findByRole("alert")).toHaveTextContent("Chwilowy błąd.");
    await userEvent.click(within(panel).getByRole("button", { name: /Napisz od nowa/ }));
    await waitFor(() => expect(attempt).toBe(2));
    expect(mocks.apiPost.mock.calls.filter(([url]) => url === "/api/notes")).toHaveLength(1);
  }, 20000);

  // Przegląd PR 5: z edytora dało się zlecić drugą generację w trakcie pierwszej.
  it("w trakcie generacji edytor nie dostaje „Napisz od nowa”", async () => {
    mocks.brandedGet.mockResolvedValue({ data: DRAFT });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    mocks.apiPost.mockImplementation(async (url: string) => {
      if (url === "/api/notes") return { data: { id: 1 } };
      rows = [{ id: 5, status: "ready", package_id: 5 }, { id: 77, status: "processing", package_id: 77 }];
      return { data: { id: 77, status: "processing", candidate_name: "Jan Kowalski" } };
    });
    renderCard();
    await startRewrite("krócej");
    await waitFor(() => expect(mocks.apiPost).toHaveBeenCalledWith("/api/cv-generator/generate", expect.anything(), expect.anything()));
    await waitFor(() => expect(screen.queryByTestId("cv-generate-panel")).toBeNull());
    await userEvent.click(await screen.findByRole("button", { name: /Otwórz i popraw/ }));
    await screen.findByTestId("editor-stub");
    expect(mocks.editorProps?.onRewrite).toBeUndefined();
  }, 20000);

  // Prośba rekrutera 15.10.2026: poprawek bywa więcej niż 300 znaków.
  it("lista poprawek: Enter robi nową linię, Ctrl+Enter wysyła listę z liniami do notatki i generatora", async () => {
    mocks.brandedGet.mockResolvedValue({ data: DRAFT });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    const posts: Array<[string, unknown]> = [];
    mocks.apiPost.mockImplementation(async (url: string, body: unknown) => {
      posts.push([url, body]);
      if (url === "/api/notes") return { data: { id: 1 } };
      return { data: { id: 77, status: "processing", candidate_name: "Jan Kowalski" } };
    });
    renderCard();
    const form = await screen.findByRole("form", { name: "Napisz od nowa" });
    const field = within(form).getByRole("textbox", { name: "Co poprawić?" });
    await userEvent.type(field, "1. krócej{Enter}2. więcej o Kafce");
    expect(field).toHaveValue("1. krócej\n2. więcej o Kafce");
    expect(screen.queryByTestId("cv-generate-panel")).toBeNull();

    await userEvent.type(field, "{Control>}{Enter}{/Control}");
    await waitFor(() => expect(posts.map(([url]) => url)).toEqual(["/api/notes", "/api/cv-generator/generate"]));
    expect(posts[0][1]).toMatchObject({ content: "Uwaga do CV:\n1. krócej\n2. więcej o Kafce" });
    expect(posts[1][1]).toMatchObject({ instruction: "1. krócej\n2. więcej o Kafce" });
  }, 20000);

  it("za długa lista: nic się nie ucina, licznik mówi, o ile skrócić, a przycisk czeka", async () => {
    mocks.brandedGet.mockResolvedValue({ data: DRAFT });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    renderCard();
    const form = await screen.findByRole("form", { name: "Napisz od nowa" });
    const field = within(form).getByRole("textbox", { name: "Co poprawić?" });
    await userEvent.click(field);
    await userEvent.paste("x".repeat(1599));
    expect(within(form).queryByTestId("text-limit-counter")).toBeNull();
    await userEvent.paste("x");
    expect(within(form).getByTestId("text-limit-counter")).toHaveTextContent("1600 / 2000 znaków");

    await userEvent.paste("x".repeat(500));
    expect(field).toHaveValue("x".repeat(2100));
    expect(within(form).getByTestId("text-limit-counter")).toHaveTextContent("2100 / 2000 znaków — skróć o 100");
    expect(within(form).getByRole("button", { name: /Napisz od nowa/ })).toBeDisabled();
    await userEvent.type(field, "{Control>}{Enter}{/Control}");
    expect(screen.queryByTestId("cv-generate-panel")).toBeNull();
    expect(mocks.apiPost).not.toHaveBeenCalled();
  }, 20000);

  it("niewysłana lista zostaje po zamknięciu karty, długa zwija się w panelu, a „Anuluj” ją oddaje", async () => {
    mocks.brandedGet.mockResolvedValue({ data: DRAFT });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    // Zgoda RODO u klienta: panel czeka na rekrutera, więc da się go anulować.
    slowGet((url) => url.endsWith("/rule-for-generation"), { is_active: true, requires_rodo_consent_block: true });
    const list = "1. krócej\n2. więcej o Kafce\n3. bez hobby\n4. certyfikaty wyżej";
    const first = renderCard();
    const field = within(await screen.findByRole("form", { name: "Napisz od nowa" })).getByRole("textbox", {
      name: "Co poprawić?",
    });
    await userEvent.click(field);
    await userEvent.paste(list);
    first.unmount();

    renderCard();
    const form = await screen.findByRole("form", { name: "Napisz od nowa" });
    expect(within(form).getByRole("textbox", { name: "Co poprawić?" })).toHaveValue(list);
    await userEvent.click(within(form).getByRole("button", { name: /Napisz od nowa/ }));

    const panel = await screen.findByTestId("cv-generate-panel");
    const instruction = within(panel).getByTestId("cv-rewrite-instruction");
    await userEvent.click(within(instruction).getByRole("button", { name: "Pokaż całość" }));
    expect(within(instruction).getByRole("button", { name: "Zwiń" })).toHaveAttribute("aria-expanded", "true");
    // Wysłana lista nie czeka już w szkicu…
    expect(Object.keys(sessionStorage).filter((key) => key.startsWith("nexus:cv-rewrite-draft"))).toEqual([]);

    // …ale „Anuluj” oddaje ją do pola.
    await userEvent.click(within(panel).getByRole("button", { name: "Anuluj" }));
    expect(
      within(await screen.findByRole("form", { name: "Napisz od nowa" })).getByRole("textbox", { name: "Co poprawić?" }),
    ).toHaveValue(list);
    expect(mocks.apiPost).not.toHaveBeenCalled();
  }, 20000);

  it("tylko do odczytu: bez pola i bez przekazania z edytora", async () => {
    mocks.brandedGet.mockResolvedValue({ data: DRAFT });
    rows = [{ id: 5, status: "ready", package_id: 5 }];
    renderCard({ readOnly: true });
    await screen.findByTestId("cv-ready-facts");
    expect(screen.queryByRole("form", { name: "Napisz od nowa" })).toBeNull();
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
    // „Otwórz i popraw” otwiera edytor bez wymuszania panelu.
    await userEvent.click(screen.getByRole("button", { name: /Otwórz i popraw/ }));
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
    expect(screen.queryByRole("button", { name: /Otwórz i popraw/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Pobierz Word/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Więcej akcji CV" })).toBeNull();
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
    expect(await screen.findByTestId("cv-ready-facts")).toHaveTextContent("wersja 2");
    expect(screen.queryByText(/Jeszcze nie ma CV do klienta/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Generuj CV/ })).toBeNull();
    expect(mocks.brandedGet).toHaveBeenCalledWith(20);
    await userEvent.click(screen.getByRole("button", { name: /Pobierz Word/ }));
    await waitFor(() =>
      expect(mocks.downloadAuthenticatedFile).toHaveBeenCalledWith(
        "/api/candidates/stages/20/cv/branded/versions/2/docx?intent=download&surface=card",
        "CV_Kowalski.docx",
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: /Otwórz i popraw/ }));
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

  it("CV wybrane świadomie: bez paska, z plakietką; „⋯ → Użyj innego CV” otwiera okno wyboru", async () => {
    mocks.brandedGet.mockResolvedValue({ data: COPY });
    // Starsze auto-CV tej pary nie jest „nowszą wersją” świeżo wybranej kopii.
    rows = [{ id: 5, status: "ready", origin: "auto", job_id: 42, created_at: "2026-10-12T08:00:00Z" }];
    renderCard();

    expect(await screen.findByTestId("cv-origin-badge")).toHaveTextContent("z rekrutacji ZOB-9000");
    expect(screen.getByText(/w wersji po poprawkach rekrutera/)).toBeInTheDocument();
    expect(screen.queryByTestId("ready-cv-hint")).toBeNull();
    expect(screen.queryByRole("button", { name: "Użyj nowej wersji" })).toBeNull();
    expect(mocks.sources).not.toHaveBeenCalled();

    // Rzadka akcja — w menu „⋯”, nie na karcie.
    expect(screen.queryByRole("button", { name: /Użyj innego CV/ })).toBeNull();
    await chooseFromMore(/Użyj innego CV/);
    expect(await screen.findByTestId("use-other-cv-dialog")).toBeInTheDocument();
    expect(mocks.otherDialogProps).toMatchObject({ candidateId: 121, candidateName: "Jan Kowalski", replaces: true });
  });

  it("kopia bez zgody: pobranie zablokowane, a zgoda idzie na CV etapu, nie na dokument generatora", async () => {
    mocks.brandedGet.mockResolvedValue({
      data: { ...COPY, consent_required: true, consent_attached: false, consent_missing: true },
    });
    renderCard();

    expect(await screen.findByText(/Zgoda RODO: brak zrzutu/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pobierz Word/ })).toBeDisabled();
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

describe("CvToClientCard — po „Zapisz i przekaż dalej” (14.10.2026)", () => {
  const READY = { status: "draft", from_generator: true, generated_document_id: 5, edit_revision: 3, version: 1 };
  const progress = () => screen.getByTestId("cv-forward-progress");
  const generatedCalls = () =>
    mocks.apiGet.mock.calls.filter(([url, config]) => url === "/api/cv-generator/generated" && config?.params?.job_id != null)
      .length;

  it("bez `forwarded` nie ma bloku postępu", async () => {
    renderCard();
    expect(await screen.findByText(/Jeszcze nie ma CV do klienta/)).toBeInTheDocument();
    expect(screen.queryByTestId("cv-forward-progress")).toBeNull();
  });

  it("21.10.2026: po przekazaniu CV czeka na rekrutera — potwierdzenia otwarte, karta nie odpytuje", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderCard({ forwarded: true });
      expect(await screen.findByTestId("cv-forward-progress")).toBeInTheDocument();
      expect(within(progress()).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
        "Screening zapisany",
        "CV czeka na Ciebie — potwierdź niżej, z czego je zrobić",
        "QC — po CV",
      ]);
      expect(progress()).not.toHaveTextContent("Dam znać w ikonie „CV”");
      // Panel z potwierdzeniami otwiera się sam.
      const panel = await screen.findByTestId("cv-generate-panel");
      expect(await within(panel).findByTestId("cv-confirm-file")).toBeInTheDocument();
      const before = generatedCalls();
      await act(async () => {
        vi.advanceTimersByTime(8200);
      });
      expect(generatedCalls()).toBe(before);
    } finally {
      vi.useRealTimers();
    }
  });

  it("automat pominął osobę: krok CV mówi dlaczego, bez „Dam znać”", async () => {
    events = [
      {
        id: 9,
        kind: "cv_auto_generate_skipped",
        created_at: new Date().toISOString(),
        reason: "consent_screenshot_required",
        candidate: { id: 121, name: "Jan Kowalski" },
      },
    ];
    renderCard({ forwarded: true });
    await waitFor(() =>
      expect(progress()).toHaveTextContent(
        "CV nie powstało automatycznie: reguła klienta wymaga zrzutu zgody RODO",
      ),
    );
    expect(progress()).not.toHaveTextContent("Dam znać w ikonie „CV”");
  });

  it("po pominięciu ręczna generacja: „generuje się” bez obietnicy dzwonka (dzwoni tylko automat)", async () => {
    events = [
      {
        id: 9,
        kind: "cv_auto_generate_skipped",
        created_at: new Date().toISOString(),
        reason: "consent_screenshot_required",
        candidate: { id: 121, name: "Jan Kowalski" },
      },
    ];
    rows = [{ id: 78, status: "processing", origin: "manual" }];
    renderCard({ forwarded: true });
    await waitFor(() => expect(progress()).toHaveTextContent("CV generuje się (ok. 40 s)"));
    expect(progress()).not.toHaveTextContent("Dam znać w ikonie „CV”");
  });

  it("stare pominięcie (sprzed przekazania) nie jest odpowiedzią — CV czeka na rekrutera", async () => {
    events = [
      {
        id: 9,
        kind: "cv_auto_generate_skipped",
        created_at: "2026-09-01T08:00:00Z",
        reason: "consent_screenshot_required",
        candidate: { id: 121, name: "Jan Kowalski" },
      },
    ];
    renderCard({ forwarded: true });
    expect(await screen.findByTestId("auto-cv-skip-notice")).toBeInTheDocument();
    expect(progress()).toHaveTextContent("CV czeka na Ciebie");
  });

  it("para miała już CV (plik Word): „CV firmowe: z pliku Word”, QC z liczbą", async () => {
    mocks.brandedGet.mockResolvedValue({
      data: { ...READY, generated_document_id: null, source: "document", origin: { kind: "upload", label: "Anna_B2B.docx" } },
    });
    qcChecks = [
      { key: "no_unsupported", label: "Zgodność", severity: "blocking", status: "fail", summary: null, items: [{ term: "AWS" }] },
    ];
    renderCard({ forwarded: true });
    await waitFor(() => expect(progress()).toHaveTextContent("CV firmowe: z pliku Word"));
    await waitFor(() => expect(progress()).toHaveTextContent("QC: 1 do poprawy"));
  });

  it("„Następna w Screeningu” otwiera osobę dopiero po kliknięciu", async () => {
    const onOpenPerson = vi.fn();
    renderCard({
      forwarded: true,
      nextInScreening: { candidateId: 55, name: "Ewa Nowak", detail: "czeka 2 dni" },
      onOpenPerson,
    });
    const next = await screen.findByRole("button", { name: /Następna w Screeningu: Ewa Nowak/ });
    expect(next).toHaveTextContent("(czeka 2 dni) · Otwórz");
    expect(onOpenPerson).not.toHaveBeenCalled();
    await userEvent.click(next);
    expect(onOpenPerson).toHaveBeenCalledWith(55);
  });

  it("`handoff` idzie do edytora z „Otwórz i popraw” i „Sprawdź i popraw”", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready" }];
    issues = { generator_warnings: ["WERYFIKUJ: daty"], content_review: { status: null, version: null, findings: [] } };
    const handoff = { onSaveAndHandOff: vi.fn(async () => true) };
    renderCard({ handoff });
    await userEvent.click(await screen.findByRole("button", { name: /Sprawdź i popraw/ }));
    expect(mocks.editorProps).toMatchObject({ stageId: 21, initialPanel: "issues", handoff });
  });

  it("bez `handoff` edytor nie dostaje przekazania", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready" }];
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Otwórz i popraw/ }));
    expect(mocks.editorProps?.handoff).toBeUndefined();
  });
});

describe("CvToClientCard — podgląd = plik dla klienta (Edytor CV 3, 14.10.2026)", () => {
  it("miniatura otwiera strony CV etapu bez intencji pobrania, a treść w układzie kartki jako zapas", async () => {
    setUser();
    mocks.brandedGet.mockResolvedValue({
      data: {
        status: "draft",
        from_generator: true,
        edit_revision: 3,
        version: 1,
        language: "pl",
        text_align: "left",
        content_html: "<p>Treść CV po poprawkach</p>",
      },
    });
    const blob = new Blob(["docx"]);
    const pages = new Blob(["%PDF"]);
    const loadStageCvFile = vi.fn().mockResolvedValue({ blob });
    const loadStageCvPdf = vi.fn().mockResolvedValue({ blob: pages });
    renderCard({ loadStageCvFile, loadStageCvPdf });
    const thumb = await screen.findByRole("button", { name: "Otwórz strony CV — Jan Kowalski" });
    // Miniatura i okno stron dzielą jeden PDF — serwer zamienia plik raz.
    await expect(mocks.thumbProps!.load()).resolves.toBe(pages);
    await userEvent.click(thumb);

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Tak zobaczy to klient: ten sam plik co „Pobierz”.")).toBeInTheDocument();
    // Strony PDF z pliku Word, a sam plik Word jako zapas — oba bez intencji pobrania.
    await expect(mocks.previewLoadPdf?.()).resolves.toBe(pages);
    expect(loadStageCvPdf).toHaveBeenCalledTimes(1);
    expect(loadStageCvPdf).toHaveBeenCalledWith(21);
    await expect(mocks.previewLoad?.()).resolves.toBe(blob);
    expect(loadStageCvFile).toHaveBeenCalledWith(21);
    // Zapas (gdy pliku nie da się pokazać): kartka edytora, nie surowy tekst.
    const paper = await within(dialog).findByTestId("cv-paper-html");
    expect(paper).toHaveTextContent("Treść CV po poprawkach");
    expect(paper.parentElement).toHaveAttribute("data-cv-align", "left");
    expect(mocks.postAuthenticatedDownload).not.toHaveBeenCalled();
  });
});

describe("CvToClientCard — miniatura i menu „⋯” (Edytor CV 3, „Ekran 5”, 14.10.2026)", () => {
  const READY = {
    status: "draft",
    from_generator: true,
    generated_document_id: 5,
    edit_revision: 3,
    version: 1,
    content_html: "<p>CV</p>",
  };

  it("autozapisy w otwartym edytorze nie zamawiają nowych stron PDF — odświeżenie raz, po zamknięciu", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready", content_mode: "tailored", language: "pl" }];
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const loadStageCvPdf = vi.fn().mockResolvedValue({ blob: new Blob(["%PDF"]) });
    renderCard({ loadStageCvPdf }, client);
    await screen.findByRole("button", { name: /Otwórz strony CV/ });
    await mocks.thumbProps!.load();
    expect(loadStageCvPdf).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: /Otwórz i popraw/ }));
    await screen.findByTestId("editor-stub");
    // Autozapis edytora podbija rewizję w tym samym kluczu, który czyta karta.
    for (const revision of [4, 5, 6]) {
      await act(async () => {
        client.setQueryData(stageBrandedQueryKey(21), { ...READY, edit_revision: revision });
        // React Query powiadamia komponenty w następnym takcie.
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
      await mocks.thumbProps!.load();
    }
    expect(loadStageCvPdf).toHaveBeenCalledTimes(1);

    // Po zamknięciu karta czyta stan od nowa — serwer ma już rewizję po autozapisach.
    mocks.brandedGet.mockResolvedValue({ data: { ...READY, edit_revision: 7 } });
    act(() => (mocks.editorProps as unknown as { onOpenChange: (open: boolean) => void }).onOpenChange(false));
    await waitFor(() => expect(screen.queryByTestId("editor-stub")).toBeNull());
    await waitFor(async () => {
      await mocks.thumbProps!.load();
      expect(loadStageCvPdf).toHaveBeenCalledTimes(2);
    });
  });

  it("liczba stron z miniatury stoi pod stanem CV, z polską odmianą", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready", content_mode: "tailored", language: "pl" }];
    renderCard();
    const facts = await screen.findByTestId("cv-ready-facts");
    expect(facts).toHaveTextContent("szkic");
    expect(facts).toHaveTextContent("Pod rekrutację · PL");
    act(() => mocks.thumbProps!.onPages!(2));
    expect(facts).toHaveTextContent("2 strony · Pod rekrutację · PL");
    act(() => mocks.thumbProps!.onPages!(1));
    expect(facts).toHaveTextContent("1 strona · Pod rekrutację");
    act(() => mocks.thumbProps!.onPages!(5));
    expect(facts).toHaveTextContent("5 stron · Pod rekrutację");
  });

  it("„Pobierz PDF” pobiera strony z intencją pobrania z karty", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready" }];
    const pdf = new Blob(["%PDF"]);
    const loadStageCvPdf = vi.fn().mockResolvedValue({ blob: pdf, filename: "CV_Kowalski.pdf" });
    renderCard({ loadStageCvPdf });
    await chooseFromMore(/Pobierz PDF/);
    await waitFor(() => expect(mocks.downloadBlob).toHaveBeenCalledWith(pdf, "CV_Kowalski.pdf"));
    expect(loadStageCvPdf).toHaveBeenCalledWith(21, { download: "card" });
  });

  it("„Pobierz PDF”: odmowa serwera (503) jako polski komunikat", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready" }];
    const loadStageCvPdf = vi.fn().mockRejectedValue({
      response: { status: 503, data: { detail: "PDF chwilowo niedostępny — pobierz plik Word." } },
    });
    renderCard({ loadStageCvPdf });
    await chooseFromMore(/Pobierz PDF/);
    await waitFor(() =>
      expect(mocks.showError).toHaveBeenCalledWith("PDF chwilowo niedostępny — pobierz plik Word."),
    );
    expect(mocks.downloadBlob).not.toHaveBeenCalled();
  });

  it("„Historia wersji” otwiera edytor na historii", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready" }];
    renderCard();
    await chooseFromMore(/Historia wersji/);
    expect(await screen.findByTestId("editor-stub")).toHaveTextContent("editor:21");
    expect(mocks.editorProps).toMatchObject({ stageId: 21, initialPanel: "history" });
  });

  it("menu „⋯” ma wszystkie rzadkie akcje, a pod kartą nie ma już rzędu przycisków", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready" }];
    renderCard();
    await screen.findByTestId("cv-ready-facts");
    expect(screen.queryByRole("button", { name: /Wygeneruj ponownie/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Podgląd/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Więcej akcji CV" }));
    const items = await screen.findAllByRole("menuitem");
    expect(items.map((item) => item.textContent?.trim())).toEqual([
      "Pobierz PDF",
      "Użyj innego CV",
      "Historia wersji",
      "Wygeneruj ponownie",
      "Odrzuć to CV i zacznij od nowa",
    ]);
  });

  it("21.10.2026: „Powstało z” i ramka przy CV z pliku „CV dla klienta”; „Wygeneruj z innego pliku” otwiera potwierdzenia", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready" }];
    aiSources = {
      ...AI_SOURCES,
      cv_files: [
        { document_id: 31, filename: "Jan_Kowalski_CV.pdf", uploaded_at: null, is_primary: false, outdated: false, stage_original: true },
        { document_id: 30, filename: "Jan_Kowalski_B2B_Orlen.docx", uploaded_at: null, is_primary: true, outdated: false, stage_original: false },
      ],
      last_source_cv: { document_id: 30, filename: "Jan_Kowalski_B2B_Orlen.docx", outdated: false, stage_original: false, removed: false },
    } as typeof aiSources;
    renderCard();
    expect(await screen.findByTestId("cv-source-file")).toHaveTextContent("Powstało z: Jan_Kowalski_B2B_Orlen.docx");
    const warning = await screen.findByTestId("cv-source-warning");
    expect(warning).toHaveTextContent("to „CV dla klienta”, nie CV kandydata");
    expect(warning).toHaveTextContent("Oryginał CV w tej rekrutacji to Jan_Kowalski_CV.pdf");
    await userEvent.click(within(warning).getByRole("button", { name: /Wygeneruj z innego pliku/ }));
    const panel = await screen.findByTestId("cv-generate-panel");
    expect(within(await within(panel).findByTestId("cv-confirm-file")).getByRole("radio", { name: /Jan_Kowalski_CV\.pdf/ })).toBeChecked();
  });

  it("21.10.2026: „Odrzuć to CV” pyta, wysyła wersję szkicu i wraca do potwierdzeń", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready" }];
    mocks.discard.mockImplementation(async () => {
      mocks.brandedGet.mockResolvedValue({ data: { status: "none", edit_revision: 4, version: 1 } });
      // Serwer nie kasuje dokumentu generatora — oznacza go jako odrzucony
      // (audyt 22.10, F64), więc wiersz dalej jest na liście pary.
      rows = [{ id: 5, status: "ready", discarded: true }];
      return { data: { status: "none", edit_revision: 4, version: 1 } };
    });
    renderCard();
    await chooseFromMore("Odrzuć to CV i zacznij od nowa");
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("nic nie jest kasowane");
    await userEvent.click(within(dialog).getByRole("button", { name: "Odrzuć i zacznij od nowa" }));
    await waitFor(() => expect(mocks.discard).toHaveBeenCalledWith(21, READY.edit_revision));
    expect(mocks.showSuccess).toHaveBeenCalledWith("CV odrzucone. Potwierdź, z czego zrobić nowe.");
    expect(await screen.findByTestId("cv-generate-panel")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Użyj tej wersji/ })).toBeNull();
  });

  it("tylko do odczytu: bez „Otwórz i popraw”; w „⋯” zostaje samo „Pobierz PDF”", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready" }];
    renderCard({ readOnly: true });
    await screen.findByTestId("cv-ready-facts");
    expect(screen.queryByRole("button", { name: /Otwórz i popraw/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Pobierz Word/ })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Więcej akcji CV" }));
    const items = await screen.findAllByRole("menuitem");
    expect(items.map((item) => item.textContent?.trim())).toEqual(["Pobierz PDF"]);
  });

  // D3 (14.10.2026): osoba już u klienta — karta zamiast widoku tylko do odczytu,
  // ale bez podmiany CV, które klient ma w ręku.
  it("po „CV wysłane”: w „⋯” tylko „Pobierz PDF” i „Historia wersji”, poprawki dalej w edytorze", async () => {
    mocks.brandedGet.mockResolvedValue({ data: READY });
    rows = [{ id: 5, status: "ready" }];
    renderCard({ lockedAfterSend: true });
    await screen.findByTestId("cv-ready-facts");
    expect(screen.getByTestId("cv-locked-after-send")).toHaveTextContent("CV jest już u klienta");
    expect(screen.queryByText("Napisz od nowa")).toBeNull();
    expect(screen.getByRole("button", { name: /Otwórz i popraw/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pobierz Word/ })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Więcej akcji CV" }));
    const items = await screen.findAllByRole("menuitem");
    expect(items.map((item) => item.textContent?.trim())).toEqual(["Pobierz PDF", "Historia wersji"]);
  });

  it("po „CV wysłane” bez CV firmowego: zdanie zamiast generowania i wyboru gotowego CV", async () => {
    mocks.brandedGet.mockResolvedValue({ data: { status: "none", edit_revision: 0, version: 0 } });
    rows = [];
    renderCard({ lockedAfterSend: true });
    expect(await screen.findByText("CV firmowego nie ma w tej rekrutacji.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Generuj CV/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Użyj gotowego CV/ })).toBeNull();
    expect(screen.queryByTestId("cv-locked-after-send")).toBeNull();
  });
});
