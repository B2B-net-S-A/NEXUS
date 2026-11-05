/**
 * Powiększenie startowe PDF-a. pdf.js nie działa w jsdom, więc atrapa `PDFViewer`
 * liczy skalę jak prawdziwy: `page-width` = szerokość okna do szerokości strony,
 * `page-actual` = 100%.
 */
import * as React from "react";
import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  PdfDocumentViewer,
  type PdfFitMode,
  type PdfViewerHandle,
} from "@/components/v2/files/PdfDocumentViewer";

const fake = vi.hoisted(() => ({
  pageWidthScale: 1,
  viewer: null as null | { currentScale: number; currentScaleValue: string },
  emit: (_name: string) => {},
}));

vi.mock("@/lib/pdfjs-loader", () => {
  class EventBus {
    private handlers = new Map<string, () => void>();
    on(name: string, handler: () => void) {
      this.handlers.set(name, handler);
    }
    dispatch() {}
    fire(name: string) {
      this.handlers.get(name)?.();
    }
  }
  class PDFViewer {
    currentScale = 1;
    currentPageNumber = 1;
    pagesCount = 1;
    private value = "";
    private bus: EventBus;
    constructor({ eventBus }: { eventBus: EventBus }) {
      this.bus = eventBus;
      fake.viewer = this;
      fake.emit = (name) => this.bus.fire(name);
    }
    get currentScaleValue() {
      return this.value;
    }
    set currentScaleValue(value: string) {
      this.value = value;
      this.currentScale = value === "page-actual" ? 1 : fake.pageWidthScale;
    }
    setDocument() {}
    increaseScale() {
      this.currentScale += 0.1;
    }
    decreaseScale() {
      this.currentScale -= 0.1;
    }
  }
  const modules = {
    lib: {
      AnnotationMode: { DISABLE: 0 },
      getDocument: () => ({
        promise: Promise.resolve({
          numPages: 0,
          getPage: () => Promise.reject(new Error("bez stron")),
        }),
        destroy: () => Promise.resolve(),
      }),
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

let resizeContainer: () => void = () => {};

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        resizeContainer = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal("requestAnimationFrame", () => 0);
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(
    () => fake.pageWidthScale * 800,
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function open(fit: PdfFitMode, pageWidthScale: number) {
  fake.pageWidthScale = pageWidthScale;
  fake.viewer = null;
  const handleRef = React.createRef<PdfViewerHandle>();
  const file = new Blob(["%PDF"], { type: "application/pdf" });
  // Blob z jsdom nie ma `arrayBuffer`.
  file.arrayBuffer = () => Promise.resolve(new ArrayBuffer(4));
  const onLoaded = vi.fn();
  render(
    <PdfDocumentViewer file={file} fit={fit} handleRef={handleRef} onLoaded={onLoaded} />,
  );
  await waitFor(() => expect(onLoaded).toHaveBeenCalled());
  act(() => fake.emit("pagesinit"));
  return { handle: handleRef, viewer: fake.viewer! };
}

describe("PdfDocumentViewer: powiększenie startowe", () => {
  it("tryb 100% na szerokim monitorze daje 100%, nie 300%", async () => {
    const { viewer } = await open("actual", 3);
    expect(viewer.currentScale).toBe(1);
  });

  it("tryb 100% w wąskim oknie zmniejsza stronę, żeby nie wychodziła poza okno", async () => {
    const { viewer } = await open("actual", 0.5);
    expect(viewer.currentScale).toBe(0.5);
  });

  it("zmiana rozmiaru okna przelicza tryb 100% i nie wraca do 300%", async () => {
    const { viewer } = await open("actual", 0.5);
    fake.pageWidthScale = 3;
    act(() => resizeContainer());
    expect(viewer.currentScale).toBe(1);
  });

  it("przycisk „Dopasuj do szerokości” w trybie 100% wypełnia szerokość i to zostaje", async () => {
    const { handle, viewer } = await open("actual", 3);
    act(() => handle.current?.fitWidth());
    expect(viewer.currentScale).toBe(3);
    fake.pageWidthScale = 2;
    act(() => resizeContainer());
    expect(viewer.currentScale).toBe(2);
  });

  it("ręczne powiększenie nie jest nadpisywane przy zmianie rozmiaru okna", async () => {
    const { handle, viewer } = await open("actual", 3);
    act(() => handle.current?.zoomIn());
    fake.pageWidthScale = 2;
    act(() => resizeContainer());
    expect(viewer.currentScale).toBeCloseTo(1.1);
  });

  it("domyślny `page-width` i `auto` działają jak dotąd", async () => {
    const pageWidth = await open("page-width", 3);
    expect(pageWidth.viewer.currentScaleValue).toBe("page-width");
    const auto = await open("auto", 3);
    expect(auto.viewer.currentScaleValue).toBe("auto");
  });
});
