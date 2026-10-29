/**
 * Okno „Użyj innego CV” (12.10.2026): CV etapu z innej rekrutacji, plik Word
 * z profilu i plik z dysku jako szkic tej rekrutacji — bez generacji.
 *
 * Dane i akcje przychodzą z `useReadyCvChoice`; tu sprawdzamy, co okno z nimi
 * robi: awaria listy nie wygląda jak „brak CV”, plik z dysku nie wysyła się
 * sam, a zły format nie dochodzi do serwera.
 *
 * 29.10.2026: plik bez układu szablonu B2B (CV kandydata) nie zapisuje się
 * jako CV do klienta bez pytania „Wygeneruj z tego pliku / Użyj tak, jak jest”.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  brandedGet: vi.fn(),
  showError: vi.fn(),
  fetchStageCvFile: vi.fn(),
  fetchStageCvPdf: vi.fn(),
  previewLoad: null as null | (() => Promise<Blob>),
  previewLoadPdf: null as null | (() => Promise<Blob>),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: vi.fn() },
  candidateStageCvApi: { branded: { get: (...a: unknown[]) => mocks.brandedGet(...a) } },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: mocks.showError }),
}));
vi.mock("@/lib/stage-cv-file", () => ({
  fetchStageCvFile: (...a: unknown[]) => mocks.fetchStageCvFile(...a),
  fetchStageCvPdf: (...a: unknown[]) => mocks.fetchStageCvPdf(...a),
}));
// Strony CV etapu (PDF, zapas: plik Word) — atrapa trzyma loadery i pokazuje zapas.
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
// Podgląd pliku (pdf.js, docx-preview) siedzi za `dynamic()`.
vi.mock("next/dynamic", () => ({
  default: () =>
    function FilePreviewStub(props: { doc?: { filename?: string } }) {
      return <div data-testid="file-preview-stub">{props.doc?.filename}</div>;
    },
}));

import { buildStageCvOptions } from "@/lib/stage-cv-options";
import { UseOtherCvDialog } from "@/components/v2/recruitment/UseOtherCvDialog";
import type { ReadyCvChoice } from "@/components/v2/recruitment/useReadyCvChoice";

const DOCUMENT = {
  id: 2,
  filename: "CV_B2B_Jan_Fikcyjny.docx",
  content_type: null,
  size_bytes: 1200,
  document_kind: "cv" as const,
  is_primary: false,
  uploaded_at: "2026-09-28T10:00:00Z",
  external_source: null,
  created_at: "2026-09-28T10:00:00Z",
};
const OPTIONS = buildStageCvOptions({
  stages: [
    { job_id: 300, stage_id: 31, job_title: "DevOps Engineer", reference_number: "ZOB-9000", client_name: "Bank Fikcyjny", status: "finalized", version: 2 },
  ],
  generated: [],
  documents: [DOCUMENT],
  jobId: 42,
  consentClient: false,
});
const EMPTY = buildStageCvOptions({ generated: [], documents: [], jobId: 42, consentClient: false });

function choice(overrides: Partial<ReadyCvChoice> = {}): ReadyCvChoice {
  return {
    options: OPTIONS,
    documents: [DOCUMENT],
    isPending: false,
    isError: false,
    refetch: vi.fn(),
    choose: vi.fn(async () => undefined),
    upload: vi.fn(async () => undefined),
    inspect: vi.fn(async () => true),
    busyKey: null,
    uploading: false,
    confirmDialog: null,
    ...overrides,
  };
}

function renderDialog(
  value: ReadyCvChoice,
  replaces = true,
  extra: { onGenerateFromFile?: (file: File) => void; generatingFromFile?: boolean } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <UseOtherCvDialog
        open
        onOpenChange={vi.fn()}
        candidateId={121}
        candidateName="Jan Fikcyjny"
        jobLabel="Python Developer"
        choice={value}
        replaces={replaces}
        {...extra}
      />
    </QueryClientProvider>,
  );
}

function pickFile(file: File) {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("UseOtherCvDialog", () => {
  it("pokazuje CV z innych rekrutacji i pliki z profilu; „Wybierz” oddaje opcję karcie", async () => {
    const value = choice();
    renderDialog(value);

    expect(screen.getByRole("heading", { name: "Użyj innego CV" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Z innych rekrutacji" })).toHaveTextContent("DevOps Engineer");
    expect(screen.getByRole("region", { name: "Pliki Word z profilu" })).toHaveTextContent(DOCUMENT.filename);
    expect(screen.getByText(/zastąpi bieżący szkic tej rekrutacji/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Wybierz: DevOps Engineer" }));

    expect(value.choose).toHaveBeenCalledWith(OPTIONS.stages[0]);
  });

  it("plik z dysku nie wysyła się sam — dopiero „Użyj tego pliku”", async () => {
    const value = choice({ options: EMPTY, documents: [] });
    renderDialog(value, false);

    // Bez gotowych CV okno nadal pozwala wgrać plik; nic nie jest zastępowane.
    expect(screen.getByRole("heading", { name: "Użyj gotowego CV" })).toBeInTheDocument();
    expect(screen.getByTestId("use-other-cv-empty")).toBeInTheDocument();
    expect(screen.queryByText(/zastąpi bieżący szkic/)).toBeNull();
    const submit = screen.getByRole("button", { name: /Użyj tego pliku/ });
    expect(submit).toBeDisabled();

    const file = new File(["docx"], "CV_gotowe_dla_klienta.docx");
    pickFile(file);
    expect(value.upload).not.toHaveBeenCalled();
    await userEvent.click(submit);

    // Plik w układzie szablonu B2B: bez pytania, jak dotąd.
    expect(value.inspect).toHaveBeenCalledWith(file);
    await waitFor(() => expect(value.upload).toHaveBeenCalledWith(file));
    expect(screen.queryByTestId("use-other-cv-candidate-file")).toBeNull();
  });

  it("sekcja pliku mówi, że to gotowe CV do klienta bez AI, i odsyła CV kandydata do „Wgraj nowe CV”", () => {
    renderDialog(choice());

    expect(screen.getByRole("region", { name: "Gotowe CV do klienta z dysku" })).toBeInTheDocument();
    expect(screen.getByText("Wgraj gotowe CV do klienta (bez AI)")).toBeInTheDocument();
    expect(screen.getByTestId("use-other-cv-candidate-hint")).toHaveTextContent(
      /„Wgraj nowe CV”.*„Generuj CV”/,
    );
  });

  describe("plik wygląda na CV kandydata (zgłoszenie 29.10.2026)", () => {
    const candidateCv = () => new File(["docx"], "CV_kandydatki.docx");

    async function askAbout(file: File, extra: Parameters<typeof renderDialog>[2] = {}) {
      const value = choice({ inspect: vi.fn(async () => false) });
      renderDialog(value, true, extra);
      pickFile(file);
      await userEvent.click(screen.getByRole("button", { name: /Użyj tego pliku/ }));
      await screen.findByTestId("use-other-cv-candidate-file");
      return value;
    }

    it("nie zapisuje pliku jako CV do klienta, tylko pyta", async () => {
      const value = await askAbout(candidateCv(), { onGenerateFromFile: vi.fn() });

      expect(screen.getByTestId("use-other-cv-candidate-file")).toHaveTextContent(
        "To wygląda na CV kandydata, nie na CV w szablonie B2B. Wygenerować z niego CV?",
      );
      expect(value.upload).not.toHaveBeenCalled();
    });

    it("„Wygeneruj z tego pliku” oddaje plik karcie, nie zapisuje go jako CV do klienta", async () => {
      const onGenerateFromFile = vi.fn();
      const file = candidateCv();
      const value = await askAbout(file, { onGenerateFromFile });

      await userEvent.click(screen.getByRole("button", { name: /Wygeneruj z tego pliku/ }));

      expect(onGenerateFromFile).toHaveBeenCalledWith(file);
      expect(value.upload).not.toHaveBeenCalled();
    });

    it("„Użyj tak, jak jest” robi to, co dotąd: plik jako CV do klienta", async () => {
      const file = candidateCv();
      const value = await askAbout(file, { onGenerateFromFile: vi.fn() });

      await userEvent.click(screen.getByRole("button", { name: "Użyj tak, jak jest" }));

      expect(value.upload).toHaveBeenCalledWith(file);
      expect(screen.queryByTestId("use-other-cv-candidate-file")).toBeNull();
    });

    it("nowy plik zdejmuje pytanie o poprzedni", async () => {
      await askAbout(candidateCv(), { onGenerateFromFile: vi.fn() });

      pickFile(new File(["docx"], "B2B_CV.docx"));

      expect(screen.queryByTestId("use-other-cv-candidate-file")).toBeNull();
      expect(screen.getByRole("button", { name: /Użyj tego pliku/ })).toBeEnabled();
    });

    it("w trakcie zapisu pliku jako CV kandydata oba przyciski czekają", async () => {
      const value = choice({ inspect: vi.fn(async () => false) });
      const onGenerateFromFile = vi.fn();
      const { rerender } = renderDialog(value, true, { onGenerateFromFile });
      pickFile(candidateCv());
      await userEvent.click(screen.getByRole("button", { name: /Użyj tego pliku/ }));
      await screen.findByTestId("use-other-cv-candidate-file");

      rerender(
        <QueryClientProvider client={new QueryClient()}>
          <UseOtherCvDialog
            open
            onOpenChange={vi.fn()}
            candidateId={121}
            candidateName="Jan Fikcyjny"
            jobLabel="Python Developer"
            choice={value}
            replaces
            onGenerateFromFile={onGenerateFromFile}
            generatingFromFile
          />
        </QueryClientProvider>,
      );

      expect(screen.getByRole("button", { name: /Wygeneruj z tego pliku/ })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Użyj tak, jak jest" })).toBeDisabled();
    });

    it("bez akcji generowania zostaje tylko „Użyj tak, jak jest”", async () => {
      await askAbout(candidateCv());

      expect(screen.queryByRole("button", { name: /Wygeneruj z tego pliku/ })).toBeNull();
      expect(screen.getByRole("button", { name: "Użyj tak, jak jest" })).toBeInTheDocument();
    });
  });

  it("pliku, którego serwer nie odczytał, okno nie zapisuje i o nic nie pyta", async () => {
    const value = choice({ inspect: vi.fn(async () => null) });
    renderDialog(value);
    pickFile(new File(["docx"], "CV_uszkodzone.docx"));

    await userEvent.click(screen.getByRole("button", { name: /Użyj tego pliku/ }));

    await waitFor(() => expect(value.inspect).toHaveBeenCalled());
    expect(value.upload).not.toHaveBeenCalled();
    expect(screen.queryByTestId("use-other-cv-candidate-file")).toBeNull();
  });

  it("plik inny niż .docx nie dochodzi do serwera", () => {
    const value = choice({ options: EMPTY, documents: [] });
    renderDialog(value, false);

    pickFile(new File(["pdf"], "CV_skan.pdf"));

    expect(screen.getByRole("alert")).toHaveTextContent("Dozwolone formaty: .docx");
    expect(screen.getByRole("button", { name: /Użyj tego pliku/ })).toBeDisabled();
    expect(value.upload).not.toHaveBeenCalled();
  });

  it("awaria listy to błąd z ponowieniem, nie „ta osoba nie ma gotowego CV”", async () => {
    const value = choice({ options: EMPTY, documents: [], isError: true });
    renderDialog(value);

    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się wczytać listy gotowych CV.");
    expect(screen.queryByTestId("use-other-cv-empty")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Ponów" }));

    expect(value.refetch).toHaveBeenCalled();
  });

  it("w trakcie wyboru albo wgrywania pozostałe akcje czekają", () => {
    renderDialog(choice({ uploading: true }));

    expect(screen.getByRole("button", { name: "Wybierz: DevOps Engineer" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Użyj tego pliku/ })).toBeDisabled();
  });

  it("podgląd CV z innej rekrutacji pokazuje plik spod wiersza etapu źródła", async () => {
    mocks.brandedGet.mockResolvedValue({
      data: { status: "finalized", content_html: "<p>Treść po poprawkach rekrutera</p>" },
    });
    const blob = new Blob(["docx"]);
    mocks.fetchStageCvFile.mockResolvedValue({ blob, filename: "CV.docx" });
    const pages = new Blob(["%PDF"]);
    mocks.fetchStageCvPdf.mockResolvedValue({ blob: pages, filename: "CV.pdf" });
    renderDialog(choice());

    await userEvent.click(screen.getByRole("button", { name: "Podgląd: DevOps Engineer" }));

    expect(await screen.findByTestId("pages-preview")).toBeInTheDocument();
    await expect(mocks.previewLoadPdf?.()).resolves.toBe(pages);
    await expect(mocks.previewLoad?.()).resolves.toBe(blob);
    // Bez intencji pobrania — podgląd nie jest pobraniem.
    expect(mocks.fetchStageCvPdf).toHaveBeenCalledWith(31);
    expect(mocks.fetchStageCvFile).toHaveBeenCalledWith(31);
    await waitFor(() => expect(mocks.brandedGet).toHaveBeenCalledWith(31));
    // Zapas, gdy pliku nie da się pokazać: ta sama treść w układzie kartki.
    expect(await screen.findByText("Treść po poprawkach rekrutera")).toBeInTheDocument();
  });

  it("podgląd pliku otwiera plik z profilu, nie wybiera go", async () => {
    const value = choice();
    renderDialog(value);

    await userEvent.click(screen.getByRole("button", { name: "Podgląd" }));

    expect(await screen.findByTestId("file-preview-stub")).toHaveTextContent(DOCUMENT.filename);
    expect(value.choose).not.toHaveBeenCalled();
  });
});
