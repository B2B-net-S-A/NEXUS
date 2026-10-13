import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const upload = vi.fn();
vi.mock("@/lib/api", () => ({
  candidateStageCvApi: { original: { upload: (...a: unknown[]) => upload(...a) } },
}));
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: (...a: unknown[]) => toastSuccess(...a),
    showError: (...a: unknown[]) => toastError(...a),
  }),
}));

import { FileDropZone } from "@/components/ds/FileDropZone";
import {
  CvFileDropTarget,
  StageCvUploadTile,
  cvFileProblem,
  useStageCvUpload,
} from "@/components/v2/person/StageCvUpload";

function pdf(name = "Anna_Nowak_CV.pdf") {
  return new File(["%PDF-1.4"], name, { type: "application/pdf" });
}

function Harness({ enabled = true, onUploaded }: { enabled?: boolean; onUploaded?: () => void }) {
  const cv = useStageCvUpload({ candidateId: 41, stageId: 900, jobId: 7, onUploaded });
  return (
    <CvFileDropTarget enabled={enabled} upload={cv} title="Anna Nowak · Senior Java Developer">
      <div data-testid="panel-content">
        <StageCvUploadTile upload={cv} />
      </div>
    </CvFileDropTarget>
  );
}

function renderHarness(props: { enabled?: boolean; onUploaded?: () => void } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <Harness {...props} />
    </QueryClientProvider>,
  );
  return { invalidate };
}

describe("cvFileProblem", () => {
  it("przepuszcza PDF, DOC i DOCX do 10 MB", () => {
    expect(cvFileProblem(pdf())).toBeNull();
    expect(cvFileProblem(new File(["x"], "cv.DOCX"))).toBeNull();
    expect(cvFileProblem(new File(["x"], "cv.doc"))).toBeNull();
  });

  it("odrzuca inne formaty, pusty plik i za duży plik", () => {
    expect(cvFileProblem(new File(["x"], "cv.odt"))).toBe("Dozwolone formaty: .pdf, .doc, .docx");
    expect(cvFileProblem(new File([], "cv.pdf"))).toBe("Plik jest pusty.");
    const big = new File(["x"], "cv.pdf");
    Object.defineProperty(big, "size", { value: 11 * 1024 * 1024 });
    expect(cvFileProblem(big)).toBe("Plik przekracza 10 MB");
  });
});

describe("Wgraj nowe CV — kafelek i upuszczenie na panel", () => {
  beforeEach(() => {
    upload.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
  });

  it("kafelek wysyła plik na trasę etapu i odświeża CV rekrutacji i profilu", async () => {
    upload.mockResolvedValue({ data: { has_snapshot: true } });
    const onUploaded = vi.fn();
    const { invalidate } = renderHarness({ onUploaded });

    fireEvent.change(screen.getByLabelText(/Wgraj nowe CV/), { target: { files: [pdf()] } });

    await waitFor(() => expect(upload).toHaveBeenCalledWith(900, expect.any(File)));
    await waitFor(() => expect(onUploaded).toHaveBeenCalled());
    expect(toastSuccess).toHaveBeenCalledWith("Nowe CV wgrane. Jest główne w profilu i w tej rekrutacji.");
    const keys = invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
    expect(keys).toContain(JSON.stringify(["cv-original", 900]));
    expect(keys).toContain(JSON.stringify(["candidate-documents", 41]));
    expect(keys).toContain(JSON.stringify(["kanban", "7"]));
  });

  it("zły format z kafelka: komunikat w kafelku, bez wysyłki", async () => {
    renderHarness();

    fireEvent.change(screen.getByLabelText(/Wgraj nowe CV/), {
      target: { files: [new File(["x"], "cv.odt")] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Dozwolone formaty: .pdf, .doc, .docx");
    expect(upload).not.toHaveBeenCalled();
  });

  it("nakładka pojawia się przy przeciąganiu pliku, a upuszczenie wgrywa CV", async () => {
    upload.mockResolvedValue({ data: {} });
    renderHarness();
    const panel = screen.getByTestId("panel-content");

    fireEvent.dragEnter(panel, { dataTransfer: { types: ["Files"], files: [] } });
    const overlay = screen.getByTestId("cv-drop-overlay");
    expect(overlay).toHaveTextContent("Upuść, aby wgrać nowe CV");
    expect(overlay).toHaveTextContent("Anna Nowak · Senior Java Developer");

    // Nakładka to sama grafika — upuszczenie trafia w element pod spodem.
    fireEvent.drop(panel, { dataTransfer: { types: ["Files"], files: [pdf()] } });

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("cv-drop-overlay")).toBeNull();
  });

  it("przeciąganie tekstu albo karty nie pokazuje nakładki", () => {
    renderHarness();

    fireEvent.dragEnter(screen.getByTestId("panel-content"), { dataTransfer: { types: ["text/plain"] } });

    expect(screen.queryByTestId("cv-drop-overlay")).toBeNull();
  });

  it("upuszczony plik w złym formacie: komunikat, bez wysyłki", () => {
    renderHarness();
    const panel = screen.getByTestId("panel-content");
    fireEvent.dragEnter(panel, { dataTransfer: { types: ["Files"], files: [] } });

    fireEvent.drop(panel, {
      dataTransfer: { types: ["Files"], files: [new File(["x"], "cv.png")] },
    });

    expect(toastError).toHaveBeenCalledWith("Dozwolone formaty: .pdf, .doc, .docx");
    expect(upload).not.toHaveBeenCalled();
  });

  it("bez prawa do wgrywania: brak nakładki", () => {
    renderHarness({ enabled: false });

    fireEvent.dragEnter(screen.getByTestId("panel-content"), { dataTransfer: { types: ["Files"], files: [] } });

    expect(screen.queryByTestId("cv-drop-overlay")).toBeNull();
  });
});

// Przegląd kodu 13.10.2026: zdarzenia z portali wędrują w Reakcie do przodków,
// a pole pliku w środku panelu ma własne przeznaczenie.
describe("CvFileDropTarget — granice upuszczania", () => {
  function Dock({ children }: { children: ReactNode }) {
    const cv = useStageCvUpload({ candidateId: 41, stageId: 900, jobId: 7 });
    return (
      <CvFileDropTarget enabled upload={cv} title="Anna Nowak · dok">
        <div data-testid="dock">{children}</div>
      </CvFileDropTarget>
    );
  }

  function SidePreview() {
    // Podgląd po „Rozwiń” idzie portalem do lewej strefy panelu.
    const cv = useStageCvUpload({ candidateId: 41, stageId: 900, jobId: 7 });
    return createPortal(
      <CvFileDropTarget enabled upload={cv} title="Anna Nowak · podgląd">
        <div data-testid="preview">podgląd</div>
      </CvFileDropTarget>,
      document.body,
    );
  }

  function wrap(ui: ReactNode) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  }

  beforeEach(() => {
    upload.mockReset();
    upload.mockResolvedValue({ data: {} });
  });

  it("plik upuszczony na podgląd w portalu wgrywa się raz", async () => {
    wrap(
      <Dock>
        <SidePreview />
      </Dock>,
    );
    const preview = screen.getByTestId("preview");
    fireEvent.dragEnter(preview, { dataTransfer: { types: ["Files"], files: [] } });
    expect(screen.getAllByTestId("cv-drop-overlay")).toHaveLength(1);

    fireEvent.drop(preview, { dataTransfer: { types: ["Files"], files: [pdf()] } });

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(upload).toHaveBeenCalledTimes(1);
  });

  it("plik upuszczony w oknie (portal) zostaje w oknie", async () => {
    const onPick = vi.fn();
    function Dialog() {
      return createPortal(
        <FileDropZone inputId="champion" file={null} onPick={onPick} accept=".docx,.pdf" label="Plik Championa" />,
        document.body,
      );
    }
    wrap(
      <Dock>
        <Dialog />
      </Dock>,
    );
    const zone = screen.getByTestId("dropzone-champion");
    fireEvent.dragEnter(zone, { dataTransfer: { types: ["Files"], files: [] } });
    expect(screen.queryByTestId("cv-drop-overlay")).toBeNull();

    fireEvent.drop(zone, { dataTransfer: { types: ["Files"], files: [new File(["PK"], "champion.docx")] } });

    expect(onPick).toHaveBeenCalledTimes(1);
    expect(upload).not.toHaveBeenCalled();
  });

  it("pole pliku w panelu (notatka w Screeningu) dostaje plik samo", () => {
    const onPick = vi.fn();
    wrap(
      <Dock>
        <FileDropZone inputId="card-note-file" file={null} onPick={onPick} accept=".docx,.pdf,.txt" label="Notatka" />
      </Dock>,
    );
    const zone = screen.getByTestId("dropzone-card-note-file");
    fireEvent.dragEnter(zone, { dataTransfer: { types: ["Files"], files: [] } });
    expect(screen.queryByTestId("cv-drop-overlay")).toBeNull();

    fireEvent.drop(zone, {
      dataTransfer: { types: ["Files"], files: [new File(["PK"], "notatki-ze-screeningu.docx")] },
    });

    expect(onPick).toHaveBeenCalledTimes(1);
    expect(upload).not.toHaveBeenCalled();
  });
});
