/**
 * Karta „CV do klienta” (generator CV v3) — stany z makiety: gotowe (z uwagami
 * kontroli AI i zgodą RODO), generuje się, brak (z powodem pominięcia
 * auto-CV), stary szablon tylko do odczytu, „Użyj nowej wersji”.
 *
 * Karta niczego nie blokuje w procesie — brak zgody wyłącza tylko pobranie.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  brandedGet: vi.fn(),
  originalGet: vi.fn(),
  selectGenerated: vi.fn(),
  downloadAuthenticatedFile: vi.fn(),
  postAuthenticatedDownload: vi.fn(),
  downloadBlob: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
  dialogProps: null as null | Record<string, unknown>,
  consentProps: null as null | Record<string, unknown>,
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: mocks.apiGet },
  candidateStageCvApi: {
    branded: {
      get: (...a: unknown[]) => mocks.brandedGet(...a),
      selectGenerated: (...a: unknown[]) => mocks.selectGenerated(...a),
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
    function EditorStub(props: { stageId?: number }) {
      return <div data-testid="editor-stub">{`editor:${props.stageId}`}</div>;
    },
}));
vi.mock("@/components/v2/cv-generator/CvGeneratorDialog", () => ({
  CvGeneratorDialog: (props: Record<string, unknown> & { onEnqueued?: (id: number) => void }) => {
    mocks.dialogProps = props;
    return (
      <div data-testid="generator-dialog">
        <button type="button" onClick={() => props.onEnqueued?.(77)}>
          Zleć generację
        </button>
      </div>
    );
  },
}));
vi.mock("@/components/v2/cv-generator/ConsentAttachButton", () => ({
  ConsentAttachButton: (props: Record<string, unknown>) => {
    mocks.consentProps = props;
    return <button type="button">Wgraj</button>;
  },
}));
vi.mock("@/components/v2/modals/CVOriginalPreviewModal", () => ({
  CVOriginalPreviewModal: () => <div data-testid="original-preview" />,
}));

import { CvToClientCard } from "@/components/v2/recruitment/CvToClientCard";

type Row = Record<string, unknown> & { id: number };
let rows: Row[] = [];
let events: unknown[] = [];

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

beforeEach(() => {
  vi.clearAllMocks();
  mocks.dialogProps = null;
  mocks.consentProps = null;
  rows = [];
  events = [];
  mocks.apiGet.mockImplementation((url: string) =>
    Promise.resolve({
      data: url === "/api/cv-generator/generated"
        ? rows
        : { job_id: 42, items: events, limit: 30 },
    }),
  );
  mocks.brandedGet.mockResolvedValue({ data: { status: "none", edit_revision: 0, version: 0 } });
  mocks.originalGet.mockResolvedValue({
    data: { has_snapshot: true, original_cv_filename: "Jan_Kowalski_CV.pdf", original_snapshot_at: "2026-09-12T10:00:00Z" },
  });
});

describe("CvToClientCard — brak CV", () => {
  it("„Generuj CV” otwiera okno generatora z osobą i tą rekrutacją", async () => {
    renderCard();
    expect(await screen.findByText(/Jeszcze nie ma CV do klienta/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Generuj CV/ }));
    expect(screen.getByTestId("generator-dialog")).toBeInTheDocument();
    expect(mocks.dialogProps).toMatchObject({ candidateId: 121, jobId: 42, candidateName: "Jan Kowalski" });
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/cv-generator/generated", {
      params: { candidate_id: 121, job_id: 42, limit: 20 },
    });
  });

  it("po zleceniu generacji karta mówi „Generuje się…”, a nie „brak CV”", async () => {
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Generuj CV/ }));
    rows = [{ id: 77, status: "processing", origin: "manual" }];
    await userEvent.click(screen.getByRole("button", { name: "Zleć generację" }));
    expect(await screen.findByText("Generuje się…")).toBeInTheDocument();
    expect(screen.getByText(/Możesz zamknąć panel/)).toBeInTheDocument();
    expect(screen.queryByText(/Jeszcze nie ma CV do klienta/)).toBeNull();
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
    renderCard();
    expect(await screen.findByText("CV gotowe · szkic")).toBeInTheDocument();
    expect(screen.getByText("Pod rekrutację")).toBeInTheDocument();
    expect(screen.getByText("EN")).toBeInTheDocument();
    expect(screen.getByText("wygenerowane automatycznie — sprawdź przed wysyłką")).toBeInTheDocument();
    expect(screen.getByText(/2 rzeczy do sprawdzenia/)).toBeInTheDocument();
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
        "/api/candidates/stages/21/cv/branded/versions/2/docx",
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
      "/api/candidates/stages/21/cv/branded/preview-docx",
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

  it("„Wygeneruj ponownie” otwiera to samo okno generatora", async () => {
    mocks.brandedGet.mockResolvedValue({
      data: { status: "finalized", from_generator: true, generated_document_id: 5, edit_revision: 4, version: 2 },
    });
    rows = [{ id: 5, status: "ready" }];
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /Wygeneruj ponownie/ }));
    expect(mocks.dialogProps).toMatchObject({ candidateId: 121, jobId: 42 });
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
