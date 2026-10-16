/**
 * Lupa „Szukaj w CV” nad PDF-em (09.2026). pdf.js nie działa w jsdom, więc
 * `PdfDocumentViewer` jest zastąpiony atrapą, która zapisuje wywołania
 * sterowania i pozwala podać wynik wyszukiwania tak, jak robi to pdf.js.
 */
import * as React from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  PdfDocumentViewer as RealViewer,
  PdfViewerHandle,
} from "@/components/v2/files/PdfDocumentViewer";

const viewer = vi.hoisted(() => ({
  handle: {
    search: vi.fn(),
    step: vi.fn(),
    zoomIn: vi.fn(),
    zoomOut: vi.fn(),
    fitWidth: vi.fn(),
  },
  props: null as null | React.ComponentProps<typeof RealViewer>,
}));

vi.mock("@/components/v2/files/PdfDocumentViewer", async () => {
  const react = await import("react");
  return {
    PdfDocumentViewer: (props: React.ComponentProps<typeof RealViewer>) => {
      viewer.props = props;
      react.useImperativeHandle(
        props.handleRef,
        () => viewer.handle as PdfViewerHandle,
      );
      return <div data-testid="pdf-document-viewer" />;
    },
  };
});

import { FilePreviewContent } from "@/components/v2/files/FilePreviewModal";
import { SearchablePdfPreview } from "@/components/v2/files/SearchablePdfPreview";

function renderPreview(scope: "dialog" | "container" = "dialog") {
  const file = new Blob(["%PDF"], { type: "application/pdf" });
  return render(
    <div style={{ position: "relative", height: 600 }}>
      <SearchablePdfPreview file={file} findShortcutScope={scope} />
    </div>,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  Object.values(viewer.handle).forEach((fn) => fn.mockReset());
});

afterEach(() => {
  vi.useRealTimers();
});

describe("SearchablePdfPreview", () => {
  it("searches the PDF after typing and shows the match counter", () => {
    renderPreview();
    act(() => viewer.props?.onTextAvailability?.("has_text"));

    const input = screen.getByRole("searchbox", { name: "Szukaj w CV" });
    fireEvent.change(input, { target: { value: "Selenium" } });
    act(() => vi.advanceTimersByTime(250));
    expect(viewer.handle.search).toHaveBeenLastCalledWith("Selenium");

    act(() => viewer.props?.onFindResult?.({ current: 2, total: 5, pending: false }));
    expect(screen.getByText("2 z 5")).toBeInTheDocument();

    fireEvent.keyDown(input, { key: "Enter" });
    expect(viewer.handle.step).toHaveBeenLastCalledWith(false);
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(viewer.handle.step).toHaveBeenLastCalledWith(true);

    fireEvent.click(screen.getByRole("button", { name: "Następne trafienie" }));
    expect(viewer.handle.step).toHaveBeenLastCalledWith(false);
  });

  it("says 'Brak wyników' instead of an empty counter", () => {
    renderPreview();
    act(() => viewer.props?.onTextAvailability?.("has_text"));
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "Kubernetes" },
    });
    act(() => vi.advanceTimersByTime(250));
    act(() => viewer.props?.onFindResult?.({ current: 0, total: 0, pending: false }));
    expect(screen.getByText("Brak wyników")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Następne trafienie" }),
    ).toBeDisabled();
  });

  // „Szukaj w CV” przy wymaganiu (16.10.2026): pole pokazuje nazwę wymagania,
  // pdf.js dostaje listę słów, a linia pod paskiem mówi, czego lupa szuka.
  it("searches the requirement's words and says what it searched for", () => {
    const file = new Blob(["%PDF"], { type: "application/pdf" });
    render(
      <div style={{ position: "relative", height: 600 }}>
        <SearchablePdfPreview
          file={file}
          query=".NET lub C#"
          onQueryChange={vi.fn()}
          terms={[".NET", "C#"]}
        />
      </div>,
    );
    act(() => viewer.props?.onTextAvailability?.("has_text"));
    act(() => vi.advanceTimersByTime(250));
    expect(viewer.handle.search).toHaveBeenLastCalledWith([".NET", "C#"]);
    const line = screen.getByTestId("document-search-terms");
    expect(line).toHaveTextContent("Szukam:");
    expect(within(line).getByText(".NET")).toBeInTheDocument();
    expect(within(line).getByText("C#")).toBeInTheDocument();

    act(() => viewer.props?.onFindResult?.({ current: 0, total: 0, pending: false }));
    expect(line).toHaveTextContent("Szukałem:");
    expect(line).toHaveTextContent("nie ma w CV");
  });

  it("a requirement search uses its words until the user types something else", async () => {
    const pdf = new Blob(["%PDF"], { type: "application/pdf" });
    render(
      <div style={{ position: "relative", height: 600 }}>
        <FilePreviewContent
          doc={{
            id: 1,
            filename: "CV.pdf",
            content_type: "application/pdf",
            size_bytes: 4,
            document_kind: "cv",
            is_primary: true,
            uploaded_at: "2026-10-16T08:00:00Z",
            external_source: null,
            created_at: "2026-10-16T08:00:00Z",
          }}
          candidateId={7}
          onDownload={vi.fn()}
          loadDocumentBlob={async () => pdf}
          searchRequest={{ text: ".NET lub C#", nonce: 1, terms: [".NET", "C#"] }}
        />
      </div>,
    );
    await act(async () => {});
    act(() => viewer.props?.onTextAvailability?.("has_text"));
    act(() => vi.advanceTimersByTime(250));
    const input = screen.getByRole("searchbox", { name: "Szukaj w CV" }) as HTMLInputElement;
    expect(input.value).toBe(".NET lub C#");
    expect(viewer.handle.search).toHaveBeenLastCalledWith([".NET", "C#"]);
    expect(screen.getByTestId("document-search-terms")).toBeInTheDocument();

    // Ręcznie wpisany tekst to znowu zwykła fraza — bez linii „Szukam:”.
    fireEvent.change(input, { target: { value: "Azure" } });
    act(() => vi.advanceTimersByTime(250));
    expect(viewer.handle.search).toHaveBeenLastCalledWith("Azure");
    expect(screen.queryByTestId("document-search-terms")).toBeNull();
  });

  it("tells the user a scanned PDF has no text to search", () => {
    renderPreview();
    act(() => viewer.props?.onTextAvailability?.("no_text"));
    expect(
      screen.getByText("Ten plik to skan — nie ma w nim tekstu do przeszukania"),
    ).toBeInTheDocument();
  });

  it("Escape clears the query before anything else", () => {
    renderPreview();
    const input = screen.getByRole("searchbox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "java" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input.value).toBe("");
  });

  it("Ctrl+F focuses the CV search instead of the browser find", () => {
    renderPreview("dialog");
    const input = screen.getByRole("searchbox");
    const event = new KeyboardEvent("keydown", {
      key: "f",
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    });
    act(() => {
      window.dispatchEvent(event);
    });
    expect(event.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(input);
  });

  it("inline preview leaves Ctrl+F to the browser when the pointer is elsewhere", () => {
    renderPreview("container");
    const event = new KeyboardEvent("keydown", {
      key: "f",
      metaKey: true,
      bubbles: true,
      cancelable: true,
    });
    act(() => {
      window.dispatchEvent(event);
    });
    expect(event.defaultPrevented).toBe(false);
    expect(document.activeElement).not.toBe(screen.getByRole("searchbox"));
  });
});
