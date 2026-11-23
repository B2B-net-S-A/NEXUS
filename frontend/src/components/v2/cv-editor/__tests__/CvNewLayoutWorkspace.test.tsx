import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import { CvEditorSection } from "@/lib/cv-editor-section";
import { PREVIEW_DEBOUNCE_MS } from "@/lib/cv-new-preview";

// pdf.js nie działa w jsdom — strona PDF ma własny kod rysowania; tu liczy się,
// co dostaje (strona, szukane teksty) i co pokazuje chip.
const placed = vi.hoisted(() => ({ page: 1, pages: 3, outlined: true }));
vi.mock("../CvPdfPageView", () => ({
  CvPdfPageView: ({
    page,
    needles,
    onPlaced,
  }: {
    page?: number;
    needles: readonly string[];
    onPlaced?: (placement: { page: number; pages: number; outlined: boolean }) => void;
  }) => {
    const key = needles.join("|");
    // Jak prawdziwy widok: położenie zgłasza po narysowaniu, raz na stronę i teksty.
    useEffect(() => {
      onPlaced?.({ ...placed, page: page ?? placed.page });
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [page, key]);
    return <div data-testid="pdf-page" data-page={page ?? "find"} data-needles={key} />;
  },
}));

import { CvNewLayoutWorkspace } from "../CvNewLayoutWorkspace";

const CV =
  '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>' +
  "<ul><li><p>Ponad 7 lat w Javie.</p></li><li><p>Spring Boot.</p></li></ul>" +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Java Developer</strong> 01.2017 – 02.2021</p>' +
  '<p data-cv-section="employer">Software House Przykład · IT</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p><ul><li><p>Usługi REST.</p></li></ul>';

const editors: Editor[] = [];

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
  vi.useRealTimers();
});

function pdf(headers: Record<string, string> = { "X-CV-Page1-Fits": "1", "X-CV-Page1-Font": "10" }) {
  return { blob: new Blob(["%PDF"]), filename: "SZKIC.pdf", headers: new Headers(headers) };
}

function setup(props: Partial<Parameters<typeof CvNewLayoutWorkspace>[0]> = {}) {
  const editor = new Editor({ extensions: [StarterKit, CvEditorSection], content: CV });
  editors.push(editor);
  const loadPreview = vi.fn(async () => pdf());
  const all = {
    editor,
    tab: "page1" as const,
    lang: "pl" as const,
    extras: null,
    disabled: false,
    active: true,
    loadPreview,
    onTab: vi.fn(),
    onOpenText: vi.fn(),
    ...props,
  };
  const view = render(<CvNewLayoutWorkspace {...all} />);
  return { editor, loadPreview: all.loadPreview, view, props: all };
}

describe("podgląd obok formularza", () => {
  it("strona 1 z ramką punktów „Dlaczego” i chipem z nagłówków renderu", async () => {
    const { loadPreview } = setup();
    expect(await screen.findByText("Strona 1 z 3 · mieści się · pismo 10 pt")).toHaveAttribute(
      "data-testid",
      "cv-new-preview-chip",
    );
    expect(loadPreview).toHaveBeenCalledTimes(1);
    const page = screen.getByTestId("pdf-page");
    expect(page).toHaveAttribute("data-page", "1");
    expect(page.getAttribute("data-needles")).toContain("Ponad 7 lat w Javie.");
  });

  it("„nie mieści się” z nagłówka renderu", async () => {
    setup({ loadPreview: vi.fn(async () => pdf({ "X-CV-Page1-Fits": "0", "X-CV-Page1-Font": "9" })) });
    expect(await screen.findByText("Strona 1 z 3 · nie mieści się · pismo 9 pt")).toBeInTheDocument();
  });

  it("stanowiska: strona szukana po tekście stanowiska", async () => {
    placed.page = 2;
    setup({ tab: "positions" });
    const page = await screen.findByTestId("pdf-page");
    expect(page).toHaveAttribute("data-page", "find");
    expect(page.getAttribute("data-needles")).toBe("Software House Przykład|Java Developer|01.2017 – 02.2021|Usługi REST.|");
    expect(await screen.findByText("Strona 2 z 3")).toBeInTheDocument();
    placed.page = 1;
  });

  it("zmiana treści odświeża podgląd dopiero 4 s po ostatniej zmianie, stary obraz zostaje", async () => {
    vi.useFakeTimers();
    const { editor, loadPreview } = setup();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(loadPreview).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("pdf-page")).toBeInTheDocument();
    act(() => {
      editor.commands.insertContentAt(2, "X");
    });
    act(() => {
      vi.advanceTimersByTime(PREVIEW_DEBOUNCE_MS - 100);
    });
    expect(loadPreview).toHaveBeenCalledTimes(1);
    act(() => {
      editor.commands.insertContentAt(2, "Y");
    });
    act(() => {
      vi.advanceTimersByTime(PREVIEW_DEBOUNCE_MS - 100);
    });
    expect(loadPreview).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("pdf-page")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(loadPreview).toHaveBeenCalledTimes(2);
  });

  it("ukryta zakładka nie prosi o PDF", () => {
    const { loadPreview } = setup({ active: false });
    expect(loadPreview).not.toHaveBeenCalled();
  });

  it("błąd podglądu po polsku, z „Ponów”; ten sam stan nie ponawia się sam", async () => {
    const loadPreview = vi
      .fn()
      .mockRejectedValueOnce({ response: { status: 503, data: { detail: "Nie udało się przygotować PDF w układzie „Nowe CV”." } } })
      .mockResolvedValueOnce(pdf());
    setup({ loadPreview });
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się przygotować PDF");
    expect(loadPreview).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
    await screen.findByTestId("pdf-page");
    expect(loadPreview).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
