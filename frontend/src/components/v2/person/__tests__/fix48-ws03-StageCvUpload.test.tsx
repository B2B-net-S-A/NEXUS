/**
 * Audyt 48 h (13.10.2026): podwójne wgranie CV przy upuszczeniu pliku w oknie
 * węższym niż 1024 px. Lewa strefa panelu (`lg:block`) jest wtedy ukryta,
 * podgląd CV z własnym `CvFileDropTarget` stoi w DOM-ie panelu osoby, więc
 * upuszczenie na podgląd obsługiwał on i zewnętrzny obszar panelu — dwa
 * żądania `…/cv/original/upload` z tym samym plikiem.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const upload = vi.fn();
vi.mock("@/lib/api", () => ({
  candidateStageCvApi: { original: { upload: (...a: unknown[]) => upload(...a) } },
}));
const toastError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: (...a: unknown[]) => toastError(...a) }),
}));

import { CvFileDropTarget, useStageCvUpload } from "@/components/v2/person/StageCvUpload";

function pdf(name = "Anna_Nowak_CV.pdf") {
  return new File(["%PDF-1.4"], name, { type: "application/pdf" });
}

/** Panel osoby (zewnętrzny obszar) z podglądem CV w środku (wąskie okno). */
function NarrowPanel() {
  const panel = useStageCvUpload({ candidateId: 41, stageId: 900, jobId: 7 });
  const preview = useStageCvUpload({ candidateId: 41, stageId: 900, jobId: 7 });
  return (
    <CvFileDropTarget enabled upload={panel} title="Anna Nowak · Senior Java Developer">
      <div data-testid="panel-content">
        <CvFileDropTarget enabled upload={preview} title="Anna Nowak · Senior Java Developer">
          <div data-testid="preview-content">podgląd CV</div>
        </CvFileDropTarget>
      </div>
    </CvFileDropTarget>
  );
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NarrowPanel />
    </QueryClientProvider>,
  );
}

describe("CvFileDropTarget — podgląd CV w panelu osoby poniżej 1024 px", () => {
  beforeEach(() => {
    upload.mockReset();
    toastError.mockReset();
  });

  it("upuszczenie na podgląd wgrywa CV raz", async () => {
    upload.mockResolvedValue({ data: {} });
    renderPanel();
    const preview = screen.getByTestId("preview-content");
    fireEvent.dragEnter(preview, { dataTransfer: { types: ["Files"], files: [] } });

    fireEvent.drop(preview, { dataTransfer: { types: ["Files"], files: [pdf()] } });

    await waitFor(() => expect(upload).toHaveBeenCalled());
    // Druga obsługa poszłaby synchronicznie w tym samym zdarzeniu.
    expect(upload).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("cv-drop-overlay")).toBeNull();
  });

  it("plik w złym formacie na podglądzie: jeden komunikat", () => {
    renderPanel();
    const preview = screen.getByTestId("preview-content");
    fireEvent.dragEnter(preview, { dataTransfer: { types: ["Files"], files: [] } });

    fireEvent.drop(preview, { dataTransfer: { types: ["Files"], files: [new File(["x"], "cv.png")] } });

    expect(toastError).toHaveBeenCalledTimes(1);
    expect(upload).not.toHaveBeenCalled();
  });

  it("upuszczenie poza podglądem dalej wgrywa CV przez panel", async () => {
    upload.mockResolvedValue({ data: {} });
    renderPanel();
    const panel = screen.getByTestId("panel-content");
    fireEvent.dragEnter(panel, { dataTransfer: { types: ["Files"], files: [] } });

    fireEvent.drop(panel, { dataTransfer: { types: ["Files"], files: [pdf()] } });

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
  });
});
