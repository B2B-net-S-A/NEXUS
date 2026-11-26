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
  /** Zachowanie `PDFViewer.setDocument` w danym teście (domyślnie nic). */
  setDocument: null as null | ((viewer: { _pages: { pdfPage: unknown }[] }, doc: unknown) => void),
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
    _pages: { pdfPage: unknown }[] = [];
    setDocument(doc: unknown) {
      fake.setDocument?.(this, doc);
    }
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
  fake.setDocument = null;
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

  it("nie zdejmuje dokumentu z przeglądarki, zanim pdf.js dostanie strony w locie", async () => {
    // 26.11.2026: pdf.js po `setDocument` dociąga strony 2..N i w odpowiedzi
    // czyta `this._pages[n - 1].pdfPage`. Odmontowanie podglądu (`setDocument(null)`
    // czyści `_pages`) przed odpowiedzią dawało nieobsłużony
    // „Cannot read properties of undefined (reading 'pdfPage')” na Tablicy.
    const errors: unknown[] = [];
    let answerPage2: () => void = () => undefined;
    fake.getPage.mockImplementation((n: number) =>
      n === 2
        ? new Promise((resolve) => {
            answerPage2 = () => resolve({ n });
          })
        : Promise.resolve({ getTextContent: () => Promise.resolve({ items: [{ str: "CV" }] }) }),
    );
    fake.setDocument = (viewer, doc) => {
      if (!doc) {
        viewer._pages = [];
        return;
      }
      viewer._pages = [{ pdfPage: null }, { pdfPage: null }];
      (doc as { getPage: (n: number) => Promise<unknown> })
        .getPage(2)
        .then((page) => {
          const pageView = viewer._pages[1];
          if (!pageView.pdfPage) pageView.pdfPage = page;
        })
        .catch((error: unknown) => errors.push(error));
    };
    fake.documentPromise = Promise.resolve({ numPages: 2, getPage: fake.getPage });
    const view = render(<PdfDocumentViewer file={pdfFile()} />);
    await waitFor(() => expect(fake.getPage).toHaveBeenCalledWith(2));

    view.unmount();
    answerPage2();
    await waitFor(() => expect(fake.destroy).toHaveBeenCalledTimes(1));
    expect(errors).toEqual([]);
  });

  it("odmontowanie w trakcie wczytywania dokumentu niszczy go od razu", async () => {
    fake.documentPromise = new Promise(() => undefined);
    const view = render(<PdfDocumentViewer file={pdfFile()} />);
    await new Promise((resolve) => setTimeout(resolve, 20));
    view.unmount();
    await waitFor(() => expect(fake.destroy).toHaveBeenCalledTimes(1));
  });
});
