/**
 * Sprzątanie po odmontowaniu (NEXUS-FE-7M): `destroy()` dopiero po odpowiedzi
 * workera na `getPage` w locie — inaczej pdf.js odrzuca je „Transport destroyed”.
 */
import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PdfDocumentViewer } from "@/components/v2/files/PdfDocumentViewer";

const fake = vi.hoisted(() => ({
  destroy: vi.fn(() => Promise.resolve()),
  getPage: vi.fn(),
  documentPromise: null as null | Promise<unknown>,
}));

vi.mock("@/lib/pdfjs-loader", () => {
  class EventBus {
    on() {}
    dispatch() {}
  }
  class PDFViewer {
    currentScale = 1;
    currentPageNumber = 1;
    pagesCount = 1;
    currentScaleValue = "";
    setDocument() {}
  }
  const modules = {
    lib: {
      AnnotationMode: { DISABLE: 0 },
      getDocument: () => ({ promise: fake.documentPromise, destroy: fake.destroy }),
    },
    viewer: {
      EventBus,
      PDFViewer,
      PDFLinkService: class {
        setViewer() {}
        setDocument() {}
      },
      PDFFindController: class {},
      FindState: { PENDING: 3 },
    },
  };
  return { loadPdfJs: () => Promise.resolve(modules) };
});

function pdfFile() {
  const file = new Blob(["%PDF"], { type: "application/pdf" });
  file.arrayBuffer = () => Promise.resolve(new ArrayBuffer(4));
  return file;
}

beforeEach(() => {
  fake.destroy.mockClear();
  fake.getPage.mockReset();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal("requestAnimationFrame", () => 0);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PdfDocumentViewer: sprzątanie", () => {
  it("czeka z destroy() na getPage w locie", async () => {
    let answerPage: () => void = () => undefined;
    fake.getPage.mockImplementation(
      () =>
        new Promise((resolve) => {
          answerPage = () => resolve({ getTextContent: () => Promise.resolve({ items: [] }) });
        }),
    );
    fake.documentPromise = Promise.resolve({ numPages: 1, getPage: fake.getPage });
    const onLoaded = vi.fn();
    const view = render(<PdfDocumentViewer file={pdfFile()} onLoaded={onLoaded} />);
    await waitFor(() => expect(fake.getPage).toHaveBeenCalled());

    view.unmount();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fake.destroy).not.toHaveBeenCalled();

    answerPage();
    await waitFor(() => expect(fake.destroy).toHaveBeenCalledTimes(1));
  });

  it("odmontowanie w trakcie wczytywania dokumentu niszczy go od razu", async () => {
    fake.documentPromise = new Promise(() => undefined);
    const view = render(<PdfDocumentViewer file={pdfFile()} />);
    await new Promise((resolve) => setTimeout(resolve, 20));
    view.unmount();
    await waitFor(() => expect(fake.destroy).toHaveBeenCalledTimes(1));
  });
});
