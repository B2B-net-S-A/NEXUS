import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FileDropZone } from "@/components/ds/FileDropZone";

function pdf(name = "zamowienie.pdf", size = 1024) {
  const file = new File(["x"], name, { type: "application/pdf" });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

function setup(overrides: Partial<React.ComponentProps<typeof FileDropZone>> = {}) {
  const onPick = vi.fn();
  const onError = vi.fn();
  render(
    <FileDropZone
      inputId="test-po"
      file={null}
      onPick={onPick}
      onError={onError}
      accept=".pdf"
      maxBytes={25 * 1024 * 1024}
      label="PDF zamówienia od klienta"
      {...overrides}
    />,
  );
  return { onPick, onError };
}

describe("FileDropZone", () => {
  it("wiąże etykietę z prawdziwym polem pliku (dostępność i automatyzacja)", () => {
    setup();
    const input = screen.getByLabelText(/PDF zamówienia od klienta/i);
    expect(input).toHaveAttribute("type", "file");
  });

  it("upuszczenie pliku działa tak samo jak wybór z okna", () => {
    const { onPick } = setup();
    const file = pdf();
    fireEvent.drop(screen.getByTestId("dropzone-test-po"), {
      dataTransfer: { files: [file] },
    });
    expect(onPick).toHaveBeenCalledWith(file);
  });

  it("pole reaguje wizualnie na przeciąganie pliku nad nim", () => {
    setup();
    const zone = screen.getByTestId("dropzone-test-po");
    expect(zone).toHaveAttribute("data-drag-over", "false");
    fireEvent.dragOver(zone);
    expect(zone).toHaveAttribute("data-drag-over", "true");
    fireEvent.dragLeave(zone);
    expect(zone).toHaveAttribute("data-drag-over", "false");
  });

  it("walidacja rozszerzenia obowiązuje TAK SAMO przy upuszczeniu", () => {
    // Upuszczenie omija atrybut `accept` przeglądarki — bez jawnego
    // sprawdzenia drag&drop byłby furtką na to, czego okno wyboru nie puści.
    const { onPick, onError } = setup();
    fireEvent.drop(screen.getByTestId("dropzone-test-po"), {
      dataTransfer: { files: [new File(["x"], "zamowienie.exe")] },
    });
    expect(onPick).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith(expect.stringContaining(".pdf"));
  });

  it("walidacja rozmiaru obowiązuje TAK SAMO przy upuszczeniu", () => {
    const { onPick, onError } = setup();
    fireEvent.drop(screen.getByTestId("dropzone-test-po"), {
      dataTransfer: { files: [pdf("wielki.pdf", 30 * 1024 * 1024)] },
    });
    expect(onPick).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith(expect.stringContaining("25 MB"));
  });
});
