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
const toastInfo = vi.fn();
const toastAction = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: (...a: unknown[]) => toastSuccess(...a),
    showError: (...a: unknown[]) => toastError(...a),
    showInfo: (...a: unknown[]) => toastInfo(...a),
    showActionToast: (...a: unknown[]) => toastAction(...a),
  }),
}));

import { FileDropZone } from "@/components/ds/FileDropZone";
import type { StageCvUploadKind } from "@/components/v2/person/StageCvUpload";
import {
  CvFileDropTarget,
  StageCvUploadTile,
  cvFileProblem,
  useStageCvUpload,
} from "@/components/v2/person/StageCvUpload";

function pdf(name = "Anna_Nowak_CV.pdf") {
  return new File(["%PDF-1.4"], name, { type: "application/pdf" });
}

type OnUploaded = (kind: StageCvUploadKind) => void;

function Harness({ enabled = true, onUploaded }: { enabled?: boolean; onUploaded?: OnUploaded }) {
  const cv = useStageCvUpload({ candidateId: 41, stageId: 900, jobId: 7, onUploaded });
  return (
    <CvFileDropTarget enabled={enabled} upload={cv} title="Anna Nowak · Senior Java Developer">
      <div data-testid="panel-content">
        <StageCvUploadTile upload={cv} />
      </div>
      {cv.confirmDialog}
    </CvFileDropTarget>
  );
}

function renderHarness(props: { enabled?: boolean; onUploaded?: OnUploaded } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <Harness {...props} />
    </QueryClientProvider>,
  );
  return { client, invalidate };
}

function invalidatedKeys(invalidate: { mock: { calls: unknown[][] } }) {
  return invalidate.mock.calls.map(([filters]) => JSON.stringify((filters as { queryKey?: unknown } | undefined)?.queryKey));
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
    toastInfo.mockReset();
    toastAction.mockReset();
  });

  it("kafelek wysyła plik na trasę etapu i odświeża CV rekrutacji i profilu", async () => {
    upload.mockResolvedValue({ data: { has_snapshot: true } });
    const onUploaded = vi.fn();
    const { invalidate } = renderHarness({ onUploaded });

    fireEvent.change(screen.getByLabelText(/Wgraj nowe CV/), { target: { files: [pdf()] } });

    await waitFor(() => expect(upload).toHaveBeenCalledWith(900, expect.any(File)));
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith("original"));
    expect(toastSuccess).toHaveBeenCalledWith(
      "Nowe CV kandydata wgrane. Jest główne w profilu i oryginałem w tej rekrutacji.",
    );
    const keys = invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
    expect(keys).toContain(JSON.stringify(["cv-original", 900]));
    expect(keys).toContain(JSON.stringify(["candidate-documents", 41]));
    expect(keys).toContain(JSON.stringify(["kanban", "7"]));
    // Audyt 22.10 (F66): otwarty panel „Z czego zrobić CV?” bierze nowy plik
    // jako Oryginał CV i generator go zna (bez cichego wyłączenia „Generuj”).
    expect(keys).toContain(JSON.stringify(["cv-ai-sources"]));
    expect(keys).toContain(JSON.stringify(["cv-gen-sources", 41]));
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

// 15.10.2026: gotowe CV do klienta („B2B_…docx”) z kafelka trafia od razu do
// „CV do klienta” tej rekrutacji; oryginał i główne CV profilu bez zmian.
describe("Wgraj nowe CV — plik „B2B_…” jako CV do klienta", () => {
  const CLIENT_FILE = "B2B_Tester_Jan_Testowy.docx";
  const clientCvFile = () => new File(["PK"], CLIENT_FILE);
  const clientCvState = { status: "draft", source: "document", edit_revision: 1, candidate_stage_id: 900 };

  function clientCvResult(extra: Record<string, unknown> = {}) {
    return {
      data: {
        has_snapshot: true,
        outcome: "client_cv",
        client_cv: clientCvState,
        client_cv_stage_id: 900,
        replaced: "none",
        undo_available: true,
        uploaded_filename: CLIENT_FILE,
        ...extra,
      },
    };
  }

  function replaceConfirm() {
    return {
      response: {
        status: 409,
        data: {
          detail: {
            code: "client_cv_replace_confirm",
            message: "CV do klienta poprawiała Anna Przykładowa 14.10.2026. Zastąpić je tym plikiem?",
            status: "draft",
            updated_at: "2026-10-14T12:00:00Z",
          },
        },
      },
    };
  }

  beforeEach(() => {
    upload.mockReset();
    toastSuccess.mockReset();
    toastError.mockReset();
    toastInfo.mockReset();
    toastAction.mockReset();
  });

  it("CV do klienta bez odczytu AI: stan CV etapu z odpowiedzi i „Cofnij” w komunikacie", async () => {
    upload.mockResolvedValueOnce(clientCvResult());
    const onUploaded = vi.fn();
    const { client, invalidate } = renderHarness({ onUploaded });

    fireEvent.change(screen.getByLabelText(/Wgraj nowe CV/), { target: { files: [clientCvFile()] } });

    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith("client_cv"));
    expect(upload).toHaveBeenCalledWith(900, expect.any(File));
    expect(client.getQueryData(["cv-branded", 900])).toEqual(clientCvState);
    const keys = invalidatedKeys(invalidate);
    expect(keys).toContain(JSON.stringify(["cv-generated", "to-client", 41, 7]));
    expect(keys).toContain(JSON.stringify(["cv-qc", 900]));
    expect(keys).toContain(JSON.stringify(["candidate-documents", 41]));
    // Oryginał i profil bez zmian — nic do odświeżenia, bez „AI czyta nowe CV”.
    expect(keys).not.toContain(JSON.stringify(["cv-original", 900]));
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(toastAction).toHaveBeenCalledWith(
      `CV do klienta z pliku ${CLIENT_FILE}.`,
      expect.objectContaining({ actionLabel: "Cofnij" }),
    );

    // „Cofnij” = ten sam plik jako CV kandydata; flaga cofnięcia nie idzie do serwera.
    upload.mockResolvedValueOnce({ data: { has_snapshot: true, outcome: "original" } });
    const { onAction } = toastAction.mock.calls[0][1] as { onAction: () => Promise<void> };
    await onAction();

    expect(upload).toHaveBeenLastCalledWith(900, expect.any(File), { mode: "original" });
    expect((upload.mock.calls[1][1] as File).name).toBe(CLIENT_FILE);
    expect(toastSuccess).toHaveBeenCalledWith(
      "Cofnięte. Plik jest CV kandydata: główne w profilu i oryginał w tej rekrutacji.",
    );
    expect(onUploaded).toHaveBeenLastCalledWith("original");
    expect(invalidatedKeys(invalidate)).toContain(JSON.stringify(["cv-branded", 900]));
  });

  it("CV pary na wcześniejszym wierszu etapu: stan na tamten wiersz, bieżący od nowa", async () => {
    upload.mockResolvedValueOnce(
      clientCvResult({ client_cv_stage_id: 880, replaced: "auto_cv", undo_available: false }),
    );
    const { client, invalidate } = renderHarness();

    fireEvent.change(screen.getByLabelText(/Wgraj nowe CV/), { target: { files: [clientCvFile()] } });

    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith(`CV do klienta z pliku ${CLIENT_FILE}. Zastąpiło CV od automatu.`),
    );
    expect(toastAction).not.toHaveBeenCalled();
    expect(client.getQueryData(["cv-branded", 880])).toEqual(clientCvState);
    const keys = invalidatedKeys(invalidate);
    expect(keys).toContain(JSON.stringify(["cv-branded", 900]));
    expect(keys).toContain(JSON.stringify(["cv-qc", 880]));
  });

  it("klient ma już CV tej osoby: informacja, plik tylko w profilu", async () => {
    upload.mockResolvedValueOnce({ data: { has_snapshot: true, outcome: "client_cv_kept", stored_in_profile: true } });
    const onUploaded = vi.fn();
    renderHarness({ onUploaded });

    fireEvent.change(screen.getByLabelText(/Wgraj nowe CV/), { target: { files: [clientCvFile()] } });

    await waitFor(() =>
      expect(toastInfo).toHaveBeenCalledWith(
        "Klient ma już CV tej osoby, więc go nie podmieniam. Plik zapisany w profilu w „CV dla klientów”.",
      ),
    );
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(onUploaded).not.toHaveBeenCalled();
  });

  it("CV do klienta poprawione przez kogoś: pytanie, „Zastąp” wysyła ten sam plik jeszcze raz", async () => {
    upload
      .mockRejectedValueOnce(replaceConfirm())
      .mockResolvedValueOnce(clientCvResult({ replaced: "confirmed", undo_available: false }));
    renderHarness();

    fireEvent.change(screen.getByLabelText(/Wgraj nowe CV/), { target: { files: [clientCvFile()] } });

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Zastąpić CV do klienta?");
    expect(dialog).toHaveTextContent("CV do klienta poprawiała Anna Przykładowa 14.10.2026. Zastąpić je tym plikiem?");
    expect(toastError).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Zastąp" }));

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    expect(upload).toHaveBeenLastCalledWith(900, expect.any(File), { replaceClientCv: true });
    expect((upload.mock.calls[1][1] as File).name).toBe(CLIENT_FILE);
    await waitFor(() =>
      expect(toastSuccess).toHaveBeenCalledWith(
        `CV do klienta z pliku ${CLIENT_FILE}. Poprzednia wersja jest w historii.`,
      ),
    );
  });

  it("„Nie podmieniaj”: nic nie idzie, a drugi plik w trakcie pytania czeka", async () => {
    upload.mockRejectedValueOnce(replaceConfirm());
    renderHarness();

    fireEvent.change(screen.getByLabelText(/Wgraj nowe CV/), { target: { files: [clientCvFile()] } });
    await screen.findByRole("dialog");

    // Upuszczenie kolejnego pliku przy otwartym pytaniu nie wysyła nic.
    const panel = screen.getByTestId("panel-content");
    fireEvent.dragEnter(panel, { dataTransfer: { types: ["Files"], files: [] } });
    fireEvent.drop(panel, { dataTransfer: { types: ["Files"], files: [pdf()] } });

    fireEvent.click(screen.getByRole("button", { name: "Nie podmieniaj" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(upload).toHaveBeenCalledTimes(1);
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(toastError).not.toHaveBeenCalled();
    expect(toastAction).not.toHaveBeenCalled();
  });

  it("CV z nagłówkiem innej osoby: komunikat serwera, bez pytania", async () => {
    upload.mockRejectedValueOnce({
      response: {
        status: 422,
        data: {
          detail: {
            code: "client_cv_other_person",
            message: "Ten plik to CV innej osoby (Piotr Przykładowy) — nie wgrałem go.",
          },
        },
      },
    });
    renderHarness();

    fireEvent.change(screen.getByLabelText(/Wgraj nowe CV/), { target: { files: [clientCvFile()] } });

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Ten plik to CV innej osoby (Piotr Przykładowy) — nie wgrałem go."),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(upload).toHaveBeenCalledTimes(1);
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
