/**
 * Miniatura pierwszej strony CV (Edytor CV 3, „Ekran 5”, 14.10.2026): pdf.js
 * tylko przez `pdfjs-loader` (atrapa), liczba stron do karty, każda awaria =
 * ikona pliku bez komunikatu, klik otwiera okno stron.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  loadPdfJs: vi.fn(),
  getDocument: vi.fn(),
  render: vi.fn(),
  destroy: vi.fn(),
  cancel: vi.fn(),
}));

vi.mock("@/lib/pdfjs-loader", () => ({ loadPdfJs: () => mocks.loadPdfJs() }));

import { CvFirstPageThumb } from "../CvFirstPageThumb";

const pdfBlob = () => new Blob(["%PDF-1.7"], { type: "application/pdf" });

function fakePdf(numPages: number) {
  return {
    numPages,
    getPage: vi.fn(async () => ({
      getViewport: ({ scale }: { scale: number }) => ({ width: 595 * scale, height: 842 * scale }),
      render: (params: unknown) => {
        mocks.render(params);
        return { promise: Promise.resolve(), cancel: mocks.cancel };
      },
    })),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.destroy.mockResolvedValue(undefined);
  mocks.getDocument.mockImplementation(() => ({ promise: Promise.resolve(fakePdf(2)), destroy: mocks.destroy }));
  mocks.loadPdfJs.mockResolvedValue({
    lib: { getDocument: mocks.getDocument, AnnotationMode: { DISABLE: 0 } },
    viewer: {},
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CvFirstPageThumb", () => {
  it("rysuje pierwszą stronę i zgłasza liczbę stron", async () => {
    const onPages = vi.fn();
    const load = vi.fn().mockResolvedValue(pdfBlob());
    render(<CvFirstPageThumb load={load} onOpen={vi.fn()} onPages={onPages} />);

    const thumb = screen.getByRole("button", { name: "Otwórz strony CV" });
    await waitFor(() => expect(thumb).toHaveAttribute("data-state", "ready"));
    expect(onPages).toHaveBeenCalledWith(2);
    expect(load).toHaveBeenCalledTimes(1);
    // Tylko strona 1, bez adnotacji, do płótna miniatury.
    expect(mocks.render).toHaveBeenCalledTimes(1);
    expect(mocks.render.mock.calls[0][0]).toMatchObject({ annotationMode: 0 });
    expect((mocks.render.mock.calls[0][0] as { canvas: unknown }).canvas).toBeInstanceOf(HTMLCanvasElement);
    expect(screen.queryByTestId("cv-first-page-placeholder")).toBeNull();
  });

  it("awaria pliku (503, 409 bez zgody) daje ikonę pliku bez komunikatu i nie ładuje pdf.js", async () => {
    const onPages = vi.fn();
    render(
      <CvFirstPageThumb
        load={() => Promise.reject({ response: { status: 409 } })}
        onOpen={vi.fn()}
        onPages={onPages}
      />,
    );
    expect(await screen.findByTestId("cv-first-page-placeholder")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Otwórz strony CV" })).toHaveAttribute("data-state", "failed");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(onPages).not.toHaveBeenCalled();
    expect(mocks.loadPdfJs).not.toHaveBeenCalled();
  });

  it("błąd pdf.js też daje ikonę pliku", async () => {
    mocks.getDocument.mockImplementation(() => ({
      promise: Promise.reject(new Error("InvalidPDFException")),
      destroy: mocks.destroy,
    }));
    render(<CvFirstPageThumb load={() => Promise.resolve(pdfBlob())} onOpen={vi.fn()} />);
    expect(await screen.findByTestId("cv-first-page-placeholder")).toBeInTheDocument();
  });

  it("klik w miniaturę otwiera strony — także przy ikonie zamiast strony", async () => {
    const onOpen = vi.fn();
    render(
      <CvFirstPageThumb
        load={() => Promise.reject(new Error("503"))}
        onOpen={onOpen}
        label="Otwórz strony CV — Jan Kowalski"
      />,
    );
    await screen.findByTestId("cv-first-page-placeholder");
    await userEvent.click(screen.getByRole("button", { name: "Otwórz strony CV — Jan Kowalski" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("z IntersectionObserver pobiera PDF dopiero, gdy miniatura jest na ekranie", async () => {
    let notify: ((entries: Array<{ isIntersecting: boolean }>) => void) | null = null;
    const disconnect = vi.fn();
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(callback: (entries: Array<{ isIntersecting: boolean }>) => void) {
          notify = callback;
        }
        observe() {}
        disconnect = disconnect;
      },
    );
    const load = vi.fn().mockResolvedValue(pdfBlob());
    render(<CvFirstPageThumb load={load} onOpen={vi.fn()} />);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(load).not.toHaveBeenCalled();

    notify!([{ isIntersecting: true }]);
    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    expect(disconnect).toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Otwórz strony CV" })).toHaveAttribute("data-state", "ready"),
    );
  });

  it("odmontowanie w trakcie rysowania sprząta zadanie pdf.js i dokument", async () => {
    let finishRender: () => void = () => undefined;
    mocks.getDocument.mockImplementation(() => ({
      promise: Promise.resolve({
        numPages: 1,
        getPage: async () => ({
          getViewport: ({ scale }: { scale: number }) => ({ width: 595 * scale, height: 842 * scale }),
          render: () => ({ promise: new Promise<void>((resolve) => (finishRender = resolve)), cancel: mocks.cancel }),
        }),
      }),
      destroy: mocks.destroy,
    }));
    const view = render(<CvFirstPageThumb load={() => Promise.resolve(pdfBlob())} onOpen={vi.fn()} />);
    await waitFor(() => expect(mocks.getDocument).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));
    view.unmount();
    expect(mocks.cancel).toHaveBeenCalled();
    expect(mocks.destroy).toHaveBeenCalled();
    finishRender();
  });
});
