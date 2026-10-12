import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Editor } from "@tiptap/core";
import { useState } from "react";

import type { CvAiRequest, CvAiResponse, CvEditorAiApi } from "@/lib/api/cvEditorAi";
import { cvEditorExtensions, loadCvHtml } from "@/lib/cv-editor-structure";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

import { CvEditorSelectionAi } from "../CvEditorSelectionAi";
import { CvEditorToolbar } from "../CvEditorToolbar";
import { useCvSelectionAi } from "../useCvSelectionAi";

const CLAUSE = "Wyrażam zgodę na przetwarzanie moich danych osobowych.";
const CV =
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – 2024</p>' +
  '<p data-cv-section="employer">Bank Przykładowy · Bankowość</p>' +
  "<ul><li><p>Rozwój usług w <strong>Java 17</strong> i Spring Boot.</p></li><li><p>Przeglądy kodu.</p></li></ul>" +
  `<p data-cv-section="rodo">${CLAUSE}</p>`;

function reply(overrides: Partial<CvAiResponse> = {}): CvAiResponse {
  return {
    status: "ok",
    action: "shorten",
    proposed_text: "Usługi w **Java 17**",
    verified: false,
    sources: [],
    cautions: [],
    reason: null,
    problem: null,
    message: null,
    ...overrides,
  };
}

const editors: Editor[] = [];

function openEditor(): Editor {
  const element = document.body.appendChild(document.createElement("div"));
  const editor = new Editor({ element, extensions: cvEditorExtensions(), content: "" });
  loadCvHtml(editor, CV);
  editors.push(editor);
  return editor;
}

function select(editor: Editor, text: string): void {
  let from = -1;
  editor.state.doc.descendants((node, position) => {
    if (from >= 0 || !node.isTextblock) return from < 0;
    const offset = node.textContent.indexOf(text);
    if (offset >= 0) from = position + 1 + offset;
    return false;
  });
  expect(from).toBeGreaterThan(0);
  act(() => {
    editor.commands.setTextSelection({ from, to: from + text.length });
  });
}

interface HostProps {
  editor: Editor;
  api: CvEditorAiApi;
  ensureDraft: () => Promise<boolean>;
  /** Edytor wyniku generatora: bez etapu rekrutacji. */
  noStage?: boolean;
  disabled?: boolean;
  onShowSource?: (quote: string) => void;
}

function Host({ editor, api, ensureDraft, noStage = false, disabled = false, onShowSource }: HostProps) {
  const [container, setContainer] = useState<HTMLElement | null>(null);
  const ai = useCvSelectionAi({ editor, stageId: noStage ? undefined : 5, disabled, ensureDraft, api });
  return (
    <div>
      <CvEditorToolbar editor={editor} language="pl" ai={ai} />
      <div ref={setContainer} data-testid="paper" />
      <CvEditorSelectionAi editor={editor} controller={ai} container={container} cvLanguage="pl" onShowSource={onShowSource} />
    </div>
  );
}

function setup(overrides: Partial<HostProps> = {}) {
  const editor = overrides.editor ?? openEditor();
  const propose = vi.fn<CvEditorAiApi["propose"]>(async () => reply());
  const ensureDraft = vi.fn(async () => true);
  const props: HostProps = { editor, api: { propose }, ensureDraft, ...overrides };
  const view = render(<Host {...props} />);
  return { editor, propose: (props.api.propose as typeof propose) ?? propose, ensureDraft: props.ensureDraft as typeof ensureDraft, view };
}

const bubble = () => screen.queryByRole("toolbar", { name: "Zaznaczony tekst" });
/** Tekst oznaczony jako czekający na propozycję (dekoracja dzieli się na znacznikach). */
const pendingText = (editor: Editor) =>
  [...editor.view.dom.querySelectorAll(".cv-ai-pending")].map((node) => node.textContent).join("");
const card = () => screen.getByRole("dialog", { name: "Propozycja AI" });

beforeAll(() => {
  // ProseMirror z fokusem przewija do kursora; jsdom nie liczy układu.
  const noRects = () => [] as unknown as DOMRectList;
  Range.prototype.getClientRects = noRects;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
  Element.prototype.getClientRects = noRects;
  Element.prototype.scrollIntoView = vi.fn();
  document.elementFromPoint = () => null;
});

beforeEach(() => {
  toast.showError.mockClear();
});

afterEach(() => {
  while (editors.length) {
    const editor = editors.pop()!;
    const mount = editor.view.dom.parentElement;
    editor.destroy();
    mount?.remove();
  }
});

describe("AI na zaznaczonym fragmencie", () => {
  it("dymek pojawia się przy zaznaczeniu; do serwera idzie tekst, nie HTML ani pozycje", async () => {
    const { editor, propose } = setup();
    expect(bubble()).toBeNull();
    select(editor, "usług w Java 17");
    fireEvent.click(within(bubble()!).getByRole("button", { name: "Skróć" }));

    await waitFor(() => expect(propose).toHaveBeenCalledTimes(1));
    expect(propose).toHaveBeenCalledWith(5, {
      action: "shorten",
      fragment: "usług w **Java 17**",
      block_text: "Rozwój usług w **Java 17** i Spring Boot.",
      block_kind: "li",
      section: "experience",
      role: { title: "Senior Developer 2021 – 2024", employer: "Bank Przykładowy · Bankowość", points: ["Przeglądy kodu."] },
    } satisfies CvAiRequest);
    const proposal = await screen.findByRole("dialog", { name: "Propozycja AI" });
    expect(proposal).toHaveTextContent("Propozycja: skróć");
    expect(proposal).toHaveTextContent("Usługi w Java 17");
    // Dymek ustępuje karcie; zaznaczony fragment jest oznaczony na kartce.
    expect(bubble()).toBeNull();
    expect(pendingText(editor)).toBe("usług w Java 17");
    // Samo zamówienie propozycji niczego w CV nie zmienia.
    expect(editor.getHTML()).toContain("Rozwój usług w <strong>Java 17</strong> i Spring Boot.");
  });

  it("„Przyjmij” to jedna cofalna zmiana; szkic powstaje dopiero wtedy", async () => {
    const { editor, ensureDraft } = setup();
    const before = editor.getHTML();
    select(editor, "usług w Java 17");
    fireEvent.click(within(bubble()!).getByRole("button", { name: "Skróć" }));
    await screen.findByRole("button", { name: "Przyjmij" });
    expect(ensureDraft).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Przyjmij" }));
    await waitFor(() => expect(editor.getHTML()).toContain("Rozwój Usługi w <strong>Java 17</strong> i Spring Boot."));
    expect(ensureDraft).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog", { name: "Propozycja AI" })).toBeNull();
    expect(editor.view.dom.querySelector(".cv-ai-pending")).toBeNull();
    await waitFor(() => expect(editor.view.dom).toHaveFocus());
    act(() => {
      editor.commands.undo();
    });
    expect(editor.getHTML()).toBe(before);
  });

  it("nie udało się założyć szkicu — treść zostaje, propozycja też", async () => {
    const { editor, ensureDraft } = setup();
    const before = editor.getHTML();
    ensureDraft.mockResolvedValueOnce(false);
    select(editor, "Przeglądy kodu");
    fireEvent.click(within(bubble()!).getByRole("button", { name: "Przeredaguj" }));
    fireEvent.click(await screen.findByRole("button", { name: "Przyjmij" }));
    await waitFor(() => expect(ensureDraft).toHaveBeenCalled());
    expect(editor.getHTML()).toBe(before);
    expect(card()).toBeInTheDocument();
  });

  it("fragment zmieniony w trakcie liczenia: propozycja nie trafia w miejsce, którego już nie ma", async () => {
    let release: (value: CvAiResponse) => void = () => undefined;
    const propose = vi.fn(() => new Promise<CvAiResponse>((resolve) => (release = resolve)));
    const { editor } = setup({ api: { propose } });
    select(editor, "Przeglądy kodu");
    fireEvent.click(within(bubble()!).getByRole("button", { name: "Skróć" }));
    await waitFor(() => expect(propose).toHaveBeenCalled());
    expect(card()).toHaveTextContent("AI przygotowuje propozycję");
    act(() => {
      editor.commands.insertContentAt(editor.state.selection.from + 2, "!");
    });
    await act(async () => release(reply({ proposed_text: "Review" })));
    expect(card()).toHaveTextContent("Zaznaczony tekst zmienił się");
    expect(screen.queryByRole("button", { name: "Przyjmij" })).toBeNull();
    expect(editor.getHTML()).not.toContain("Review");
  });

  it("odpowiedź, która przyszła po „Anuluj”, jest ignorowana", async () => {
    let release: (value: CvAiResponse) => void = () => undefined;
    const propose = vi.fn(() => new Promise<CvAiResponse>((resolve) => (release = resolve)));
    const { editor } = setup({ api: { propose } });
    select(editor, "Przeglądy kodu");
    fireEvent.click(within(bubble()!).getByRole("button", { name: "Skróć" }));
    fireEvent.click(await screen.findByRole("button", { name: "Anuluj" }));
    await act(async () => release(reply()));
    expect(screen.queryByRole("dialog", { name: "Propozycja AI" })).toBeNull();
    expect(editor.view.dom.querySelector(".cv-ai-pending")).toBeNull();
  });

  it("odmowa kontroli pokazuje powód z serwera i pozwala spróbować jeszcze raz", async () => {
    const propose = vi
      .fn<CvEditorAiApi["propose"]>()
      .mockResolvedValueOnce(
        reply({ status: "rejected", proposed_text: null, reason: "new_fact", problem: "21", message: "Propozycja dodawała „21”, czego nie ma w zaznaczonym tekście." }),
      )
      .mockResolvedValue(reply());
    const { editor } = setup({ api: { propose } });
    select(editor, "usług w Java 17");
    fireEvent.click(within(bubble()!).getByRole("button", { name: "Skróć" }));
    expect(await screen.findByText(/Propozycja dodawała „21”/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Przyjmij" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Jeszcze raz" }));
    await screen.findByRole("button", { name: "Przyjmij" });
    // Odrzuconej propozycji nikt nie widział — nie ma jej w „previous”.
    expect(propose.mock.calls[1][1]).not.toHaveProperty("previous");
  });

  it("awaria żądania to komunikat z „Jeszcze raz”, edytor działa dalej", async () => {
    const propose = vi.fn<CvEditorAiApi["propose"]>().mockRejectedValue({ response: { status: 500, data: {} } });
    const { editor } = setup({ api: { propose } });
    select(editor, "Przeglądy kodu");
    fireEvent.click(within(bubble()!).getByRole("button", { name: "Skróć" }));
    expect(await screen.findByText("Nie udało się pobrać propozycji AI. Spróbuj ponownie.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Jeszcze raz" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Zamknij" }));
    expect(screen.queryByRole("dialog", { name: "Propozycja AI" })).toBeNull();
  });

  it("„Jeszcze raz” wysyła pokazane propozycje, „Doprecyzuj” — wskazówkę i bieżącą propozycję", async () => {
    const propose = vi
      .fn<CvEditorAiApi["propose"]>()
      .mockResolvedValueOnce(reply({ proposed_text: "Pierwsza wersja" }))
      .mockResolvedValueOnce(reply({ proposed_text: "Druga wersja" }))
      .mockResolvedValue(reply({ proposed_text: "Trzecia wersja" }));
    const { editor } = setup({ api: { propose } });
    select(editor, "Przeglądy kodu");
    fireEvent.click(within(bubble()!).getByRole("button", { name: "Przeredaguj" }));
    await screen.findByText("Pierwsza wersja");
    fireEvent.click(screen.getByRole("button", { name: "Jeszcze raz" }));
    await screen.findByText("Druga wersja");
    expect(propose.mock.calls[1][1].previous).toEqual(["Pierwsza wersja"]);
    expect(propose.mock.calls[1][1]).not.toHaveProperty("instruction");

    fireEvent.click(screen.getByRole("button", { name: "Doprecyzuj" }));
    fireEvent.change(screen.getByLabelText("Co zmienić w tej propozycji?"), { target: { value: "krócej" } });
    fireEvent.click(screen.getByRole("button", { name: "Wyślij" }));
    await screen.findByText("Trzecia wersja");
    expect(propose.mock.calls[2][1]).toMatchObject({ instruction: "krócej", previous: ["Druga wersja"] });
    // Zakres zostaje ten sam przez wszystkie próby.
    expect(pendingText(editor)).toBe("Przeglądy kodu");
  });

  it("rozwinięcie z cytatem: plakietka, źródło i „Pokaż w oryginale”", async () => {
    const onShowSource = vi.fn();
    const propose = vi.fn<CvEditorAiApi["propose"]>().mockResolvedValue(
      reply({
        action: "expand",
        proposed_text: "Przeglądy kodu dla 2 mln klientów.",
        verified: true,
        sources: [
          { kind: "original", quote: "przelewy natychmiastowe dla 2 mln klientów" },
          { kind: "notes", quote: "Kafka w projekcie płatności przez około 3 lata" },
        ],
      }),
    );
    const { editor } = setup({ api: { propose }, onShowSource });
    select(editor, "Przeglądy kodu.");
    fireEvent.click(within(bubble()!).getByRole("button", { name: "Rozwiń z oryginału" }));
    const proposal = await screen.findByRole("dialog", { name: "Propozycja AI" });
    expect(within(proposal).getByText("Zgodne ze źródłem")).toBeInTheDocument();
    expect(proposal).toHaveTextContent("Źródło: oryginalne CV");
    expect(proposal).toHaveTextContent("Źródło: notatka rekrutera");
    // Podświetlić da się tylko w oryginale — notatki nie mają wyszukiwania.
    const jumps = within(proposal).getAllByRole("button", { name: "Pokaż w oryginale" });
    expect(jumps).toHaveLength(1);
    fireEvent.click(jumps[0]);
    expect(onShowSource).toHaveBeenCalledWith("przelewy natychmiastowe dla 2 mln klientów");
  });

  it("tłumaczenie w polskim CV mówi, co zostaje po polsku, i pokazuje nazwy do sprawdzenia", async () => {
    const propose = vi.fn<CvEditorAiApi["propose"]>().mockResolvedValue(
      reply({ action: "translate", proposed_text: "Code reviews by the Project Manager.", cautions: ["Project", "Manager"] }),
    );
    const { editor } = setup({ api: { propose } });
    select(editor, "Przeglądy kodu.");
    fireEvent.click(within(bubble()!).getByRole("button", { name: "Na angielski" }));
    const proposal = await screen.findByRole("dialog", { name: "Propozycja AI" });
    expect(proposal).toHaveTextContent("etykiety szablonu i klauzula zgody zostają po polsku");
    expect(proposal).toHaveTextContent("Sprawdź nazwy, których nie było w zaznaczonym tekście: Project, Manager.");
  });

  it("Escape w karcie odrzuca propozycję i nie wychodzi poza kartę", async () => {
    const { editor } = setup();
    const outer = vi.fn();
    document.body.addEventListener("keydown", outer);
    select(editor, "Przeglądy kodu");
    fireEvent.click(within(bubble()!).getByRole("button", { name: "Skróć" }));
    fireEvent.keyDown(await screen.findByRole("dialog", { name: "Propozycja AI" }), { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Propozycja AI" })).toBeNull();
    expect(outer).not.toHaveBeenCalled();
    document.body.removeEventListener("keydown", outer);
  });

  it("zaznaczenie, którego AI nie zmienia: przyciski wyłączone z powodem, pogrubienie działa", () => {
    const { editor } = setup();
    select(editor, "Senior Developer");
    const menu = bubble()!;
    expect(within(menu).getByRole("button", { name: "Skróć" })).toBeDisabled();
    expect(menu).toHaveTextContent("Stanowisko, firmę i listę technologii popraw ręcznie");
    expect(within(menu).getByRole("button", { name: "Pogrubienie" })).toBeEnabled();
  });

  it("klauzula zgody, podgląd Word i edytor bez etapu nie mają dymka", () => {
    const first = setup();
    select(first.editor, "Wyrażam zgodę");
    expect(bubble()).toBeNull();
    first.view.unmount();

    const word = setup({ disabled: true });
    select(word.editor, "Przeglądy kodu");
    expect(bubble()).toBeNull();
    word.view.unmount();

    const generated = setup({ noStage: true });
    select(generated.editor, "Przeglądy kodu");
    expect(bubble()).toBeNull();
    expect(screen.queryByRole("button", { name: "AI na zaznaczonym tekście" })).toBeNull();
  });

  it("menu „AI” w pasku: to samo wejście dla klawiatury, z powodem, gdy nie ma czego zaznaczyć", async () => {
    const { editor, propose } = setup();
    const trigger = screen.getByRole("button", { name: "AI na zaznaczonym tekście" });
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(await screen.findByText("Zaznacz fragment w akapicie albo punkcie.")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Skróć" })).toHaveAttribute("aria-disabled", "true");
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });

    select(editor, "Przeglądy kodu");
    fireEvent.keyDown(screen.getByRole("button", { name: "AI na zaznaczonym tekście" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Popraw język" }));
    await waitFor(() => expect(propose).toHaveBeenCalledWith(5, expect.objectContaining({ action: "proofread", fragment: "Przeglądy kodu" })));
  });
});
