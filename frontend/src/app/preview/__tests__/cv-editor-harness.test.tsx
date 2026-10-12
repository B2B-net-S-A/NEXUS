/**
 * Harness `/preview/cv-editor` (Edytor CV 2, 12.10.2026).
 *
 * Test montuje CAŁĄ stronę z prawdziwym edytorem (bez atrapy Tiptapa, którą
 * mają testy okna) i sprawdza to, czego atrapa nie pokaże: żadne żądanie nie
 * idzie do sieci, „Dodaj → Stanowisko” zatrzymuje „Zapisz” do wypełnienia pól,
 * a „Zapisz” na zatwierdzonej wersji bez zmian nie zakłada nowego szkicu.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import {
  Axios,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from "axios";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

// pdf.js i podgląd DOCX nie działają w jsdom; panel źródeł ma własny test.
vi.mock("@/components/v2/cv-editor/CvEditorSources", () => ({
  CvEditorSources: (props: { stageId?: number; context?: unknown }) => (
    <div data-testid="sources">{props.context === null ? "bez rekrutacji" : `etap ${props.stageId}`}</div>
  ),
}));
vi.mock("@/components/v2/cv-editor/CvEditorWordPreview", () => ({
  CvEditorWordPreview: () => <div data-testid="word-preview" />,
}));

import { api } from "@/lib/api";
import CvEditorPreviewPage from "../cv-editor/page";

const sent: InternalAxiosRequestConfig[] = [];
const attempts = vi.spyOn(Axios.prototype, "request");

beforeAll(() => {
  const adapter: AxiosAdapter = async (config) => {
    sent.push(config);
    return { data: {}, status: 200, statusText: "OK", headers: {}, config } as AxiosResponse;
  };
  api.defaults.adapter = adapter;
  // ProseMirror przewija do kursora po każdej zmianie; jsdom nie liczy układu.
  const noRects = () => [] as unknown as DOMRectList;
  Range.prototype.getClientRects = noRects;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
  Element.prototype.getClientRects = noRects;
  Element.prototype.scrollIntoView = () => undefined;
  document.elementFromPoint = () => null;
});

beforeEach(() => {
  window.history.replaceState(null, "", "/preview/cv-editor");
});

afterEach(() => {
  sent.length = 0;
  attempts.mockClear();
});

async function openEditor(state?: string): Promise<HTMLElement> {
  if (state) window.history.replaceState(null, "", `/preview/cv-editor?state=${state}`);
  render(<CvEditorPreviewPage />);
  const dialog = await screen.findByRole("dialog", { name: "Edytor CV do klienta" });
  await waitFor(() => expect(dialog.querySelector(".ProseMirror h1")).not.toBeNull());
  return dialog;
}

const noNetwork = () => {
  expect(sent).toEqual([]);
  expect(attempts).not.toHaveBeenCalled();
};

it("otwiera szkic z kartką CV i nie wysyła żadnego żądania", async () => {
  const dialog = await openEditor();
  const paper = dialog.querySelector(".cv-paper") as HTMLElement;
  expect(paper).toHaveAttribute("data-cv-lang", "pl");
  expect(within(paper).getByText("Senior Java Developer – Anna Przykładowa")).toBeInTheDocument();
  expect(paper.querySelectorAll('[data-cv-section="role"]')).toHaveLength(2);
  expect(paper.querySelector(".cv-rodo-locked")).toHaveAttribute("contenteditable", "false");
  expect(within(dialog).getByRole("button", { name: "Cofnij" })).toBeDisabled();

  fireEvent.click(within(dialog).getByRole("button", { name: "Podgląd Word" }));
  expect(await within(dialog).findByTestId("word-preview")).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Edycja" }));
  noNetwork();
});

it("nowe stanowisko zatrzymuje „Zapisz”, dopóki zostały pola w nawiasach", async () => {
  const dialog = await openEditor();
  fireEvent.keyDown(within(dialog).getByRole("button", { name: "Dodaj" }), { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "Stanowisko" }));
  await waitFor(() =>
    expect(dialog.querySelectorAll('.cv-paper [data-cv-section="role"]')).toHaveLength(3),
  );

  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  const alert = await within(dialog).findByText(/Uzupełnij albo usuń pola w nawiasach/);
  expect(alert).toHaveTextContent("[Stanowisko]");
  expect(alert).toHaveTextContent("Szkic jest zapisany.");
  // Okno zostaje otwarte: CV z „[Stanowisko]” nie może pójść do klienta.
  expect(screen.getByRole("dialog", { name: "Edytor CV do klienta" })).toBeInTheDocument();
  noNetwork();
});

it("„Zapisz” na zatwierdzonej wersji bez zmian zamyka okno i nie zakłada szkicu", async () => {
  const dialog = await openEditor("finalized");
  expect(within(dialog).getByRole("button", { name: /Pobierz zatwierdzony DOCX/ })).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edytor CV do klienta" })).toBeNull());

  fireEvent.click(screen.getByRole("button", { name: "Otwórz edytor" }));
  const reopened = await screen.findByRole("dialog", { name: "Edytor CV do klienta" });
  // Nowy szkic zmieniłby przycisk na „Pobierz szkic DOCX”.
  expect(await within(reopened).findByRole("button", { name: /Pobierz zatwierdzony DOCX/ })).toBeInTheDocument();
  noNetwork();
});

it("wynik generatora bez rekrutacji mówi panelowi źródeł, że nie ma czego pokazać", async () => {
  const dialog = await openEditor("nosources");
  fireEvent.click(within(dialog).getByRole("button", { name: "Źródła" }));
  expect(await within(dialog).findByTestId("sources")).toHaveTextContent("bez rekrutacji");
  noNetwork();
});
