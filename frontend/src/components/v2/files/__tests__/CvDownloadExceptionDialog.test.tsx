import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const download = vi.hoisted(() => vi.fn());
const downloadBlob = vi.hoisted(() => vi.fn());
const showError = vi.hoisted(() => vi.fn());
const showSuccess = vi.hoisted(() => vi.fn());

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess }) }));
vi.mock("@/lib/authenticated-files", () => ({ downloadBlob, fetchAuthenticatedDownload: vi.fn() }));
vi.mock("@/lib/cv-download-access", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/cv-download-access")>()),
  downloadOriginalAfterGenerator: download,
}));

import { CvDownloadExceptionDialog } from "../CvDownloadExceptionDialog";

function setup() {
  const onOpenChange = vi.fn();
  render(<CvDownloadExceptionDialog stageId={55} open onOpenChange={onOpenChange} />);
  return { onOpenChange, submit: screen.getByRole("button", { name: "Pobierz oryginał" }) };
}

describe("CvDownloadExceptionDialog", () => {
  beforeEach(() => {
    download.mockReset();
    downloadBlob.mockReset();
    showError.mockReset();
    showSuccess.mockReset();
  });

  it("bez powodu nie da się pobrać", () => {
    const { submit } = setup();
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Układ, format"));
    expect(submit).toBeEnabled();
    fireEvent.click(screen.getByLabelText("Układ, format"));
    expect(submit).toBeDisabled();
  });

  it("„Inny powód” wymaga opisu", () => {
    const { submit } = setup();
    fireEvent.click(screen.getByLabelText("Inny powód"));
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Przykład z tego CV"), { target: { value: "Brak projektu" } });
    expect(submit).toBeEnabled();
  });

  it("wysyła powody, zapisuje plik i zamyka okno", async () => {
    const blob = new Blob(["x"]);
    download.mockResolvedValue({ blob, filename: "cv.pdf" });
    const { submit, onOpenChange } = setup();
    fireEvent.click(screen.getByLabelText("Złe lata albo daty"));
    fireEvent.click(submit);
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(download).toHaveBeenCalledWith(55, { reasons: ["years"], detail: "" });
    expect(downloadBlob).toHaveBeenCalledWith(blob, "cv.pdf");
  });

  it("odmowa serwera zostaje w oknie z komunikatem", async () => {
    download.mockRejectedValue(
      Object.assign(new Error("x"), {
        response: { status: 409, data: { detail: { message: "Najpierw wygeneruj CV." } } },
      }),
    );
    const { submit, onOpenChange } = setup();
    fireEvent.click(screen.getByLabelText("Układ, format"));
    fireEvent.click(submit);
    await waitFor(() => expect(showError).toHaveBeenCalledWith("Najpierw wygeneruj CV."));
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(downloadBlob).not.toHaveBeenCalled();
  });
});
