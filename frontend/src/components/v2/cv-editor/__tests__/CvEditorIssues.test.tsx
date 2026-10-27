import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Editor } from "@tiptap/core";

import type { CvEditorIssuesApi, CvEditorIssuesData } from "@/lib/api/cvEditorIssues";
import { cvQcQueryKey, type QcCheck, type QcFixesResponse, type QcResult, type QcTransformBody, type QcTransformResult } from "@/lib/api/cvQc";
import { cvEditorExtensions, loadCvHtml } from "@/lib/cv-editor-structure";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
// Wgranie zrzutu ma własne testy (`ConsentAttachButton.test.tsx`); tu liczy się,
// dokąd panel go kieruje i że po nim QC liczy się od nowa.
vi.mock("@/components/v2/cv-generator/ConsentAttachButton", () => ({
  ConsentAttachButton: (props: { generatedId?: number; stageCopy?: { candidateId: number; stageId: number }; onAttached?: () => void }) => (
    <button
      type="button"
      data-generated={props.generatedId ?? ""}
      data-stage={props.stageCopy ? `${props.stageCopy.candidateId}:${props.stageCopy.stageId}` : ""}
      onClick={() => props.onAttached?.()}
    >
      Wgraj zrzut maila
    </button>
  ),
}));

// Miniatura zrzutu zgody pobiera obraz sama (`CvQcDialog.test.tsx`); tu liczy się,
// że stoi w wierszu uwagi i dla którego etapu.
vi.mock("@/components/v2/cv/ConsentScreenshotThumb", () => ({
  ConsentScreenshotThumb: (props: { stageId: number }) => (
    <button type="button" data-stage={props.stageId}>
      Pokaż zrzut zgody
    </button>
  ),
}));

import { CvEditorIssues, type CvIssueCount } from "../CvEditorIssues";

const STAGE = 901;
const CLAUSE = "Wyrażam zgodę na przetwarzanie moich danych osobowych.";
const CV =
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – 2024</p>' +
  '<p data-cv-section="employer">Bank Przykładowy</p>' +
  "<ul><li><p>Rozwój usług w Java i AWS.</p></li><li><p>Przeglądy kodu.</p></li></ul>" +
  `<p data-cv-section="rodo">${CLAUSE}</p>`;

function check(partial: Partial<QcCheck> & Pick<QcCheck, "key" | "label">): QcCheck {
  return { severity: "warning", status: "fail", summary: null, items: [], ...partial };
}

const CHECKS: QcCheck[] = [
  check({
    key: "no_unsupported",
    label: "Zgodność z oryginałem",
    severity: "blocking",
    items: [{ term: "AWS", fix: "remove_term", detail: "Nie ma tego w oryginale." }],
  }),
  check({
    key: "must_bolded",
    label: "Must-have pogrubione",
    items: [{ requirement: "Java", term: "Java", fix: "bold_all" }],
  }),
  check({ key: "dates", label: "Daty", status: "pass" }),
];

function qcResult(overrides: Partial<QcResult> = {}): QcResult {
  return {
    stage_id: STAGE,
    candidate_id: 101,
    candidate_name: "Anna Przykładowa",
    job_id: 201,
    job_title: "Senior Java Developer",
    client_name: "Bank Przykładowy",
    passed: false,
    blocking_failed: 1,
    warnings_count: 1,
    override: null,
    advisory: true,
    can_override: true,
    confirmations: [],
    run_id: null,
    computed_at: "2026-10-12T12:00:00Z",
    cv: {
      source: "branded_draft",
      editable: true,
      stage_id: STAGE,
      generated_document_id: 77,
      document_id: null,
      filename: null,
      bold_known: true,
      updated_at: null,
      edit_revision: 4,
      blocks: [],
    },
    original_cv: { source: "snapshot", filename: "cv.pdf", text: "" },
    client_request: { must: ["Java"], nice: [], critical: [], critical_source: "none" },
    checks: CHECKS,
    ...overrides,
  };
}

const ISSUES: CvEditorIssuesData = {
  generated_document_id: 77,
  generator_warnings: [
    "MUST-HAVE: brak Kafka w źródłach.",
    "Wyróżnienia: pogrubiono 4 terminy.",
  ],
  content_review: {
    status: "reviewed",
    version: 2,
    findings: [
      { text: "Przeglądy kodu.", status: "unsupported" },
      { text: "Linia, której już nie ma.", status: "contradicted" },
    ],
  },
};

function memoryApi(overrides: Partial<CvEditorIssuesApi> = {}): CvEditorIssuesApi {
  return {
    qc: vi.fn(async () => qcResult()),
    persistQc: vi.fn(async () => qcResult({ run_id: 5 })),
    issues: vi.fn(async () => ISSUES),
    fixes: vi.fn(async () => ({ status: "ok" as const, cached: false, fixes: [] })),
    transform: vi.fn(async (_stage: number, body: QcTransformBody): Promise<QcTransformResult> => ({
      content_html: body.content_html.replace("w Java i", "w <strong>Java</strong> i"),
      changed: true,
      applied: [{ action: "bold_all", count: 1 }],
      skipped: [],
    })),
    confirm: vi.fn(async () => qcResult({ blocking_failed: 0 })),
    dismiss: vi.fn(async () => qcResult()),
    restore: vi.fn(async () => qcResult()),
    dismissIssue: vi.fn(async () => ISSUES),
    restoreIssue: vi.fn(async () => ISSUES),
    ...overrides,
  };
}

const editors: Editor[] = [];

/** Wiersz listy (blokada, poprawka, uwaga) po swoim tekście. */
function itemOf(text: string | RegExp): HTMLElement {
  const item = screen.getByText(text).closest("li");
  if (!item) throw new Error(`brak pozycji: ${String(text)}`);
  return item as HTMLElement;
}

/** Rozwija wiersz (tytuł = przycisk) — szczegóły: „Pokaż w CV”, „To nieprawda”, dowód. */
function expand(row: HTMLElement): HTMLElement {
  const title = within(row).getAllByRole("button")[0];
  fireEvent.click(title);
  return row;
}

/** Nazwy grup listy w kolejności panelu. */
function regionOrder(names: readonly string[]): string[] {
  return screen
    .getAllByRole("region")
    .map((region) => region.getAttribute("aria-label") ?? "")
    .filter((name) => names.includes(name));
}

const GROUPS = ["Blokuje wysyłkę", "Do poprawy", "Poprawione", "Do decyzji · nie blokuje", "Pominięte", "Informacje", "W porządku"];

function openEditor(): Editor {
  const element = document.body.appendChild(document.createElement("div"));
  const editor = new Editor({ element, extensions: cvEditorExtensions(), content: "" });
  loadCvHtml(editor, CV);
  editors.push(editor);
  return editor;
}

interface Setup {
  api?: CvEditorIssuesApi;
  editor?: Editor;
  props?: Partial<Parameters<typeof CvEditorIssues>[0]>;
  client?: QueryClient;
}

function setup({
  api = memoryApi(),
  editor = openEditor(),
  props = {},
  // Jak w aplikacji: wynik zapytania żyje w pamięci 5 minut po odmontowaniu.
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
}: Setup = {}) {
  const counts: CvIssueCount[] = [];
  const onShowCv = vi.fn();
  const ensureDraft = vi.fn(async () => true);
  const element = (extra: Partial<Parameters<typeof CvEditorIssues>[0]> = {}) => (
    <QueryClientProvider client={client}>
      <CvEditorIssues
        editor={editor}
        stageId={STAGE}
        savedRevision={4}
        unsaved={false}
        readOnly={false}
        ensureDraft={ensureDraft}
        onShowCv={onShowCv}
        onCount={(count) => counts.push(count)}
        api={api}
        {...props}
        {...extra}
      />
    </QueryClientProvider>
  );
  const view = render(element());
  return { api, editor, client, counts, onShowCv, ensureDraft, view, rerender: (extra = {}) => view.rerender(element(extra)) };
}

beforeAll(() => {
  // ProseMirror z fokusem przewija do kursora; jsdom nie liczy układu.
  const noRects = () => [] as unknown as DOMRectList;
  Range.prototype.getClientRects = noRects;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
  Element.prototype.getClientRects = noRects;
  document.elementFromPoint = () => null;
});

beforeEach(() => {
  toast.showSuccess.mockClear();
  toast.showError.mockClear();
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  vi.useRealTimers();
  while (editors.length) {
    const editor = editors.pop()!;
    const mount = editor.view.dom.parentElement;
    editor.destroy();
    mount?.remove();
  }
});

describe("panel „Do poprawy” w edytorze CV (wariant A, 17.10.2026)", () => {
  it("grupy po wadze: blokady, poprawki jednym przyciskiem, rzeczy do decyzji — i licznik do paska", async () => {
    const { counts, editor } = setup();
    expect(await screen.findByText("1 blokuje wysyłkę")).toBeInTheDocument();

    const blocking = await screen.findByRole("region", { name: "Blokuje wysyłkę" });
    const task = within(blocking).getByRole("listitem");
    expect(task).toHaveTextContent("AWS — jest w CV, a nie ma tego w oryginale");
    expect(task).toHaveTextContent("zgodność z oryginałem");
    // Treść spoza oryginału: trzy odpowiedzi jednym kliknięciem (D5).
    expect(within(task).getByRole("button", { name: "Usuń z CV: AWS" })).toBeEnabled();
    expect(within(task).getByRole("button", { name: "Kandydat to ma" })).toBeInTheDocument();
    // „Jest w oryginale” to pominięcie — pozycja bez klucza (przebieg sprzed 13.10) go nie ma.
    expect(within(task).queryByRole("button", { name: "Jest w oryginale" })).not.toBeInTheDocument();

    // Pogrubienie: jeden wiersz z przyciskiem i „Popraw wszystkie” w nagłówku grupy.
    const fixable = screen.getByRole("region", { name: "Do poprawy" });
    expect(within(fixable).getByRole("listitem")).toHaveTextContent("Pogrub: Java");
    expect(within(fixable).getByRole("button", { name: "Pogrub wszystkie: Java" })).toBeEnabled();
    expect(within(fixable).getByRole("button", { name: /Popraw wszystkie \(1\)/ })).toBeEnabled();

    // Generator i kontrola AI: do decyzji, z jednym przyciskiem „OK” / „Zostaw”.
    const decide = screen.getByRole("region", { name: "Do decyzji · nie blokuje" });
    await within(decide).findByText("„Przeglądy kodu.”");
    expect(itemOf("„Przeglądy kodu.”")).toHaveTextContent("kontrola AI v2 · bez pokrycia w źródłach");
    expect(within(itemOf("„Przeglądy kodu.”")).getByRole("button", { name: "Zostaw: „Przeglądy kodu.”" })).toBeInTheDocument();
    expect(itemOf("MUST-HAVE: brak Kafka w źródłach.")).toHaveTextContent("Uwaga generatora");
    // Kontrola AI: tylko linia, która nadal stoi w CV.
    expect(screen.queryByText("„Linia, której już nie ma.”")).not.toBeInTheDocument();

    // „Wyróżnienia: …” to informacja o tym, co generator zrobił — zwinięta w „Informacjach”.
    const info = screen.getByRole("region", { name: "Informacje" });
    expect(info).not.toHaveTextContent("pogrubiono 4 terminy");
    expect(within(info).getByRole("button", { name: /Od generatora \(1\)/ })).toHaveAttribute("aria-expanded", "false");
    expect(info).toHaveTextContent("1 uwaga kontroli AI dotyczyła linii, której już nie ma w CV.");

    expect(regionOrder(GROUPS)).toEqual(["Blokuje wysyłkę", "Do poprawy", "Do decyzji · nie blokuje", "Informacje", "W porządku"]);
    // Zdania AI nie mają już osobnej sekcji pod listą.
    expect(screen.queryByRole("region", { name: "Propozycje AI" })).not.toBeInTheDocument();

    // 1 blokująca + 1 uwaga QC + 1 uwaga generatora + 1 linia kontroli AI.
    await waitFor(() => expect(counts.at(-1)).toMatchObject({ total: 4, blocking: 1, state: "ready" }));
    await waitFor(() => expect(editor.view.dom.querySelector(".cv-issue-term.cv-issue--blocking")?.textContent).toBe("AWS"));
    // Bez `onOverride` (karta nie na „Zweryfikowany”) panel nie przepuszcza.
    expect(screen.queryByRole("button", { name: /Przekaż mimo uwag|Przesuń|Przepuść/ })).not.toBeInTheDocument();
  });

  it("„Przekaż mimo uwag…” w nagłówku blokad woła tę samą akcję co stopka", async () => {
    const onOverride = vi.fn();
    setup({ props: { onOverride } });
    const blocking = await screen.findByRole("region", { name: "Blokuje wysyłkę" });
    fireEvent.click(within(blocking).getByRole("button", { name: "Przekaż mimo uwag…" }));
    expect(onOverride).toHaveBeenCalledTimes(1);
  });

  it("asystent rozwinięty: zostaje pasek z liczbami, „Pokaż listę” wraca, znaczniki zostają", async () => {
    const onShowList = vi.fn();
    const { editor, counts } = setup({ props: { summary: true, onShowList } });
    const bar = await screen.findByRole("group", { name: "Do poprawy" });
    await within(bar).findByText("1 blokuje");
    expect(bar).toHaveTextContent("3 do decyzji");
    expect(screen.queryByRole("region", { name: "Blokuje wysyłkę" })).not.toBeInTheDocument();
    fireEvent.click(within(bar).getByRole("button", { name: "Pokaż listę" }));
    expect(onShowList).toHaveBeenCalled();
    await waitFor(() => expect(editor.view.dom.querySelector(".cv-issue-term")).not.toBeNull());
    await waitFor(() => expect(counts.at(-1)).toMatchObject({ total: 4, blocking: 1, state: "ready" }));
  });

  it("awaria QC nie wygląda jak CV bez uwag", async () => {
    const api = memoryApi({ qc: vi.fn(async () => Promise.reject({ response: { status: 500 } })) });
    setup({ api });
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się policzyć QC — to nie znaczy, że CV jest bez uwag.");
    expect(screen.queryByText("Nic nie blokuje wysyłki tego CV.")).not.toBeInTheDocument();
    expect(screen.queryByText("Nic nie blokuje wysyłki")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
    await waitFor(() => expect(api.qc).toHaveBeenCalledTimes(2));
  });

  it("brak dostępu do QC mówi o dostępie i nie daje „Ponów”", async () => {
    setup({ api: memoryApi({ qc: vi.fn(async () => Promise.reject({ response: { status: 403 } })) }) });
    expect(await screen.findByText("Nie masz dostępu do QC tej rekrutacji.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ponów" })).not.toBeInTheDocument();
  });

  it("QC innego CV pary: komunikat zamiast listy, która nie dotyczy tej treści", async () => {
    const other = qcResult();
    other.cv = { ...other.cv!, stage_id: 555 };
    const { editor } = setup({ api: memoryApi({ qc: vi.fn(async () => other) }) });
    expect(await screen.findByText(/sprawdza inne CV tej osoby/)).toBeInTheDocument();
    expect(screen.queryByText("AWS — jest w CV, a nie ma tego w oryginale")).not.toBeInTheDocument();
    expect(screen.queryByText(/blokuje wysyłkę/)).not.toBeInTheDocument();
    expect(editor.view.dom.querySelector(".cv-issue-term")).toBeNull();
    // Uwagi generatora i kontroli AI należą do TEGO wiersza etapu — zostają.
    const decide = await screen.findByRole("region", { name: "Do decyzji · nie blokuje" });
    expect(decide).toHaveTextContent("MUST-HAVE: brak Kafka");
    expect(await screen.findByText("„Przeglądy kodu.”")).toBeInTheDocument();
  });

  it("klik w wiersz pokazuje miejsce na kartce, „Pokaż w CV” w szczegółach też", async () => {
    const { editor, onShowCv } = setup();
    await screen.findByText("„Przeglądy kodu.”");
    const row = expand(itemOf("„Przeglądy kodu.”"));
    expect(onShowCv).toHaveBeenCalled();
    await waitFor(() => expect(editor.view.dom.querySelector(".cv-issue-focus")?.textContent).toBe("Przeglądy kodu."));
    // Samo wskazanie miejsca nie zabiera fokusu z listy.
    expect(editor.view.dom).not.toHaveFocus();
    fireEvent.click(within(row).getByRole("button", { name: "Pokaż w CV" }));
    expect(onShowCv).toHaveBeenCalledTimes(2);
  });

  it("miejsce, którego już nie ma: rozwinięcie milczy, „Pokaż w CV” mówi wprost", async () => {
    const { editor } = setup();
    await screen.findByText("AWS — jest w CV, a nie ma tego w oryginale");
    const task = itemOf("AWS — jest w CV, a nie ma tego w oryginale");
    loadCvHtml(editor, editor.getHTML().replace(" i AWS", ""));
    expand(task);
    expect(toast.showError).not.toHaveBeenCalled();
    fireEvent.click(within(task).getByRole("button", { name: "Pokaż w CV" }));
    expect(toast.showError).toHaveBeenCalledWith(expect.stringContaining("Tego miejsca nie ma już w treści CV"));
  });

  it("poprawka: serwer liczy na treści z edytora, edytor nakłada ją jednym cofalnym krokiem, wiersz w „Poprawione”", async () => {
    const { api, editor, ensureDraft } = setup();
    const before = editor.getHTML();
    const updates = vi.fn();
    editor.on("update", updates);
    fireEvent.click(await screen.findByRole("button", { name: "Pogrub wszystkie: Java" }));

    await waitFor(() => expect(editor.getHTML()).toContain("<strong>Java</strong>"));
    expect(ensureDraft).toHaveBeenCalledTimes(1);
    expect(api.transform).toHaveBeenCalledWith(STAGE, {
      content_html: before,
      actions: [{ action: "bold_all", scope: "must" }],
      bulk: false,
    });
    // Zmiana idzie zwykłą drogą edytora — autozapis utrwali ją sam.
    expect(updates).toHaveBeenCalledTimes(1);
    expect(toast.showSuccess).toHaveBeenCalledWith("Pogrubiono wszystkie wystąpienia. Ctrl+Z cofa.");
    // Klawiatura wraca do tekstu — Ctrl+Z cofa poprawkę bez klikania w kartkę.
    await waitFor(() => expect(editor.view.dom).toHaveFocus());

    const done = await screen.findByRole("region", { name: "Poprawione" });
    expect(done).toHaveTextContent("Pogrubiono: Java");
    fireEvent.click(within(done).getByRole("button", { name: "Cofnij" }));
    expect(editor.getHTML()).toBe(before);
    expect(screen.queryByRole("region", { name: "Poprawione" })).not.toBeInTheDocument();
  });

  it("„Cofnij” znika, gdy CV zmieniło się po poprawce (wtedy Ctrl+Z)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { editor } = setup();
    fireEvent.click(await screen.findByRole("button", { name: "Pogrub wszystkie: Java" }));
    const done = await screen.findByRole("region", { name: "Poprawione" });
    expect(within(done).getByRole("button", { name: "Cofnij" })).toBeInTheDocument();
    act(() => {
      editor.commands.insertContentAt(1, "PISZĘ ");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(within(done).queryByRole("button", { name: "Cofnij" })).not.toBeInTheDocument();
    expect(done).toHaveTextContent("Pogrubiono: Java");
  });

  it("„Popraw wszystkie” bierze tylko poprawki formalne, mówi, co pominięto, i cofa się jednym kliknięciem", async () => {
    const api = memoryApi({
      transform: vi.fn(async (_stage: number, body: QcTransformBody) => ({
        content_html: body.content_html.replace("w Java i", "w <strong>Java</strong> i"),
        changed: true,
        applied: [{ action: "bold_all", count: 1 }],
        skipped: [{ action: "spelling", code: "nothing_to_do", message: "Nie ma pisowni do poprawienia." }],
      })),
    });
    const { editor } = setup({ api });
    const before = editor.getHTML();
    const bulk = await screen.findByRole("button", { name: /Popraw wszystkie \(1\)/ });
    expect(bulk).toHaveAttribute("title", expect.stringContaining("Jednym kliknięciem: pogrubienie 1 wymagania must-have."));
    fireEvent.click(bulk);

    const done = await screen.findByRole("region", { name: "Poprawione" });
    // Usunięcie „AWS” (treść) nie wchodzi do hurtu — zostaje w wierszu blokady.
    expect(api.transform).toHaveBeenCalledWith(STAGE, {
      content_html: before,
      actions: [{ action: "bold_all", scope: "must" }],
      bulk: true,
    });
    expect(done).toHaveTextContent("Pogrubiono: Java");
    expect(done).toHaveTextContent("Pominięto: Nie ma pisowni do poprawienia.");
    expect(editor.getHTML()).toContain("<strong>Java</strong>");

    fireEvent.click(within(done).getByRole("button", { name: "Cofnij wszystkie" }));
    expect(editor.getHTML()).toBe(before);
    expect(screen.queryByRole("region", { name: "Poprawione" })).not.toBeInTheDocument();
  });

  it("poprawka, której nie da się nałożyć, mówi dlaczego i nie rusza treści", async () => {
    const api = memoryApi({
      transform: vi.fn(async (_stage: number, body: QcTransformBody) => ({
        content_html: body.content_html,
        changed: false,
        applied: [],
        skipped: [{ action: "remove_term", code: "nothing_to_do", message: "„AWS” nie stoi na liście technologii — usuń je w edytorze CV." }],
      })),
    });
    const { editor } = setup({ api });
    const before = editor.getHTML();
    fireEvent.click(await screen.findByRole("button", { name: "Usuń z CV: AWS" }));
    await waitFor(() =>
      expect(toast.showError).toHaveBeenCalledWith("„AWS” nie stoi na liście technologii — usuń je w edytorze CV."),
    );
    expect(editor.getHTML()).toBe(before);
    expect(editor.can().undo()).toBe(false);
    expect(screen.queryByRole("region", { name: "Poprawione" })).not.toBeInTheDocument();
  });

  it("„Usuń z CV” przy terminie w zdaniu: serwer go nie usuwa, więc prośba idzie do asystenta (PR 3)", async () => {
    const api = memoryApi({
      transform: vi.fn(async (_stage: number, body: QcTransformBody) => ({
        content_html: body.content_html,
        changed: false,
        applied: [],
        skipped: [{ action: "remove_term", code: "nothing_to_do", message: "„AWS” nie stoi na liście technologii — usuń je w edytorze CV." }],
      })),
    });
    const onAskAssistant = vi.fn();
    const { editor } = setup({ api, props: { onAskAssistant } });
    const before = editor.getHTML();
    fireEvent.click(await screen.findByRole("button", { name: "Usuń z CV: AWS" }));
    await waitFor(() => expect(onAskAssistant).toHaveBeenCalledTimes(1));
    expect(onAskAssistant.mock.calls[0][0]).toContain("Usuń „AWS” z CV");
    expect(onAskAssistant.mock.calls[0][0]).toContain("Nie dopisuj nowych faktów");
    expect(toast.showSuccess).toHaveBeenCalledWith("„AWS” stoi w zdaniu — asystent przeredaguje je bez tego słowa.");
    expect(toast.showError).not.toHaveBeenCalled();
    expect(editor.getHTML()).toBe(before);
  });

  it("nie udało się założyć szkicu na zatwierdzonej wersji — poprawka nie rusza treści", async () => {
    const { editor, ensureDraft } = setup();
    const before = editor.getHTML();
    ensureDraft.mockResolvedValueOnce(false);
    fireEvent.click(await screen.findByRole("button", { name: "Pogrub wszystkie: Java" }));
    await waitFor(() => expect(ensureDraft).toHaveBeenCalled());
    expect(editor.getHTML()).toBe(before);
    expect(toast.showSuccess).not.toHaveBeenCalled();
  });

  it("szkic powstaje dopiero, gdy serwer potwierdzi, że poprawka coś zmienia", async () => {
    // Nowy szkic zdejmuje z CV stan „zatwierdzone” (linki, wysyłka). Poprawka,
    // której nie da się nałożyć, nie może kosztować ponownego zatwierdzania.
    const order: string[] = [];
    const api = memoryApi({
      transform: vi.fn(async (_stage: number, body: QcTransformBody) => {
        order.push("transform");
        return {
          content_html: body.content_html,
          changed: false,
          applied: [],
          skipped: [{ action: "remove_term", code: "nothing_to_do", message: "Nie ma czego usunąć." }],
        };
      }),
    });
    const { ensureDraft } = setup({ api });
    ensureDraft.mockImplementation(async () => {
      order.push("ensureDraft");
      return true;
    });
    fireEvent.click(await screen.findByRole("button", { name: "Usuń z CV: AWS" }));
    await waitFor(() => expect(toast.showError).toHaveBeenCalledWith("Nie ma czego usunąć."));
    expect(order).toEqual(["transform"]);
  });

  it("pusta treść z serwera nie zastępuje CV", async () => {
    const api = memoryApi({
      transform: vi.fn(async () => ({ content_html: "  ", changed: true, applied: [{ action: "spelling" }], skipped: [] })),
    });
    const { editor, ensureDraft } = setup({ api });
    const before = editor.getHTML();
    fireEvent.click(await screen.findByRole("button", { name: "Usuń z CV: AWS" }));
    await waitFor(() => expect(toast.showError).toHaveBeenCalled());
    expect(editor.getHTML()).toBe(before);
    expect(ensureDraft).not.toHaveBeenCalled();
  });

  it("treść zmieniona w trakcie liczenia: wynik nie nadpisuje tego, co rekruter wpisał", async () => {
    let release: (value: QcTransformResult) => void = () => undefined;
    const api = memoryApi({
      transform: vi.fn(
        () =>
          new Promise<QcTransformResult>((resolve) => {
            release = resolve;
          }),
      ),
    });
    const { editor } = setup({ api });
    fireEvent.click(await screen.findByRole("button", { name: "Usuń z CV: AWS" }));
    await waitFor(() => expect(api.transform).toHaveBeenCalled());
    editor.commands.insertContentAt(1, "PISZĘ ");
    const typed = editor.getHTML();
    await act(async () => {
      release({ content_html: "<p>Stara treść po poprawce.</p>", changed: true, applied: [{ action: "remove_term" }], skipped: [] });
    });
    await waitFor(() => expect(toast.showError).toHaveBeenCalledWith(expect.stringContaining("Treść CV zmieniła się")));
    expect(editor.getHTML()).toBe(typed);
  });

  it("podgląd Word albo trwający zapis wyłącza poprawki", async () => {
    setup({ props: { readOnly: true } });
    expect(await screen.findByRole("button", { name: "Usuń z CV: AWS" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Pogrub wszystkie: Java" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Popraw wszystkie \(1\)/ })).toBeDisabled();
  });

  it("po autozapisie liczy QC od nowa, a przy niezapisanych zmianach mówi, czego dotyczy lista", async () => {
    const { api, rerender } = setup();
    await screen.findByText("1 blokuje wysyłkę");
    expect(api.qc).toHaveBeenCalledTimes(1);

    vi.useFakeTimers();
    rerender({ unsaved: true });
    expect(screen.getByRole("status", { name: "" }) ?? screen.getAllByRole("status")[0]).toBeTruthy();
    expect(screen.getByText(/Lista dotyczy ostatnio zapisanej treści/)).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(api.qc).toHaveBeenCalledTimes(1);

    rerender({ unsaved: false, savedRevision: 5 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    expect(api.qc).toHaveBeenCalledTimes(2);
  });

  it("przebieg QC dla Tablicy zapisuje raz, przy zamknięciu, i tylko po zmianie treści", async () => {
    const untouched = setup();
    await screen.findByText("1 blokuje wysyłkę");
    untouched.view.unmount();
    expect(untouched.api.persistQc).not.toHaveBeenCalled();

    const edited = setup();
    await screen.findByText("1 blokuje wysyłkę");
    edited.rerender({ savedRevision: 5 });
    edited.view.unmount();
    expect(edited.api.persistQc).toHaveBeenCalledTimes(1);
    expect(edited.api.persistQc).toHaveBeenCalledWith(STAGE);
  });

  it("ponowne otwarcie edytora liczy QC od nowa, zamiast pokazać wynik z poprzedniej sesji", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const qc = vi
      .fn<CvEditorIssuesApi["qc"]>()
      .mockResolvedValueOnce(qcResult())
      .mockResolvedValue(qcResult({ blocking_failed: 0, passed: true, checks: [] }));
    const api = memoryApi({ qc });
    const first = setup({ api, client });
    await screen.findByText("1 blokuje wysyłkę");
    first.view.unmount();

    setup({ api, client });
    expect(await screen.findByText("Nic nie blokuje wysyłki")).toBeInTheDocument();
    expect(screen.queryByText("1 blokuje wysyłkę")).not.toBeInTheDocument();
    expect(qc).toHaveBeenCalledTimes(2);
    expect(api.issues).toHaveBeenCalledTimes(2);
  });

  it("licznik w pasku nie udaje zera, gdy QC jeszcze się liczy albo nie odpowiada", async () => {
    const down = setup({
      api: memoryApi({
        qc: vi.fn(async () => Promise.reject({ response: { status: 500 } })),
        issues: vi.fn(async () => ({ ...ISSUES, generator_warnings: [], content_review: { status: null, version: null, findings: [] } })),
      }),
    });
    expect(down.counts[0]).toMatchObject({ state: "loading" });
    await screen.findByText(/Nie udało się policzyć QC/);
    await waitFor(() => expect(down.counts.at(-1)).toMatchObject({ total: 0, blocking: 0, state: "failed" }));
    down.view.unmount();

    const fine = setup();
    await waitFor(() => expect(fine.counts.at(-1)).toMatchObject({ total: 4, blocking: 1, state: "ready" }));
  });

  it("nieudany zapis przebiegu QC przy zamknięciu trafia do zgłaszania błędów zapytań", async () => {
    const failures: unknown[] = [];
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
      queryCache: new QueryCache({ onError: (error) => failures.push(error) }),
    });
    const boom = new Error("500");
    const { view, rerender } = setup({ client, api: memoryApi({ persistQc: vi.fn(async () => Promise.reject(boom)) }) });
    await screen.findByText("1 blokuje wysyłkę");
    rerender({ savedRevision: 5 });
    view.unmount();
    await waitFor(() => expect(failures).toContain(boom));
  });

  it("edytor wyniku generatora: same uwagi generatora, bez zapytań o QC", async () => {
    const { api, counts } = setup({
      props: { stageId: undefined, generatorWarnings: ["MUST-HAVE: brak Kafka w źródłach."] },
    });
    expect(screen.getByText(/nie jest jeszcze na etapie rekrutacji/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Uwagi generatora" })).toHaveTextContent("MUST-HAVE: brak Kafka");
    await waitFor(() => expect(counts.at(-1)).toMatchObject({ total: 1, blocking: 0, state: "ready" }));
    expect(api.qc).not.toHaveBeenCalled();
    expect(api.issues).not.toHaveBeenCalled();
  });

  it("zamknięcie panelu zdejmuje znaczniki z kartki", async () => {
    const { editor, view } = setup();
    await waitFor(() => expect(editor.view.dom.querySelector(".cv-issue-term")).not.toBeNull());
    view.unmount();
    expect(editor.view.dom.querySelector("[class*=cv-issue]")).toBeNull();
  });
});

describe("odpowiedzi jednym kliknięciem i „To nieprawda” (D5)", () => {
  const SUBMIT = "Oznacz jako nieprawdę";
  const DISMISSAL = {
    id: 41,
    reason: "in_cv",
    reason_label: "Jest w CV — QC tego nie znalazło",
    note: null,
    by_name: "Marta Przykładowa",
    at: "2026-10-13T08:30:00Z",
  };
  /** Pozycje z kluczami — jak z serwera od 13.10.2026. */
  const KEYED: QcCheck[] = CHECKS.map((c) => ({
    ...c,
    items: c.items.map((item) => ({ ...item, key: `${c.key}|${(item.term ?? "").toLowerCase()}|cv` })),
  }));

  it("„OK” przy uwadze generatora i „Zostaw” przy kontroli AI: pominięcie z powodem `kept`, bez formularza", async () => {
    const after: CvEditorIssuesData = {
      ...ISSUES,
      generator_warnings: ["Wyróżnienia: pogrubiono 4 terminy."],
      dismissed: [
        {
          source: "generator",
          text: "MUST-HAVE: brak Kafka w źródłach.",
          status: null,
          dismissal: { ...DISMISSAL, id: 52, reason: "kept", reason_label: "Sprawdzone — zostaje w CV" },
        },
      ],
    };
    const api = memoryApi({ dismissIssue: vi.fn(async () => after) });
    const { counts } = setup({ api });
    fireEvent.click(await screen.findByRole("button", { name: "OK, sprawdzone: MUST-HAVE: brak Kafka w źródłach." }));
    await waitFor(() =>
      expect(api.dismissIssue).toHaveBeenCalledWith(STAGE, {
        source: "generator",
        text: "MUST-HAVE: brak Kafka w źródłach.",
        status: null,
        reason: "kept",
      }),
    );
    expect(toast.showSuccess).toHaveBeenCalledWith("Zostaje w CV — uwaga zeszła z listy.");
    await waitFor(() => expect(screen.queryByText("MUST-HAVE: brak Kafka w źródłach.")).not.toBeInTheDocument());
    expect(screen.getByRole("region", { name: "Pominięte" })).toHaveTextContent("Pominięte (1)");
    await waitFor(() => expect(counts.at(-1)).toMatchObject({ total: 3, blocking: 1, state: "ready" }));

    fireEvent.click(screen.getByRole("button", { name: "Zostaw: „Przeglądy kodu.”" }));
    await waitFor(() =>
      expect(api.dismissIssue).toHaveBeenLastCalledWith(STAGE, {
        source: "review",
        text: "Przeglądy kodu.",
        status: "unsupported",
        reason: "kept",
      }),
    );
  });

  // 18.10.2026 (Kalwala, 789131): rekruter czytał w „Do decyzji” surowy angielski strażnik lat.
  it("uwaga generatora po angielsku: w wierszu zdanie po polsku, „OK” wysyła surowy tekst", async () => {
    const raw = "NOT IN SOURCE: '32 year' (why_points) follows neither from the source nor from the dates — „32 years”";
    const api = memoryApi({
      issues: vi.fn(async () => ({ ...ISSUES, generator_warnings: [raw] })),
      dismissIssue: vi.fn(async () => ISSUES),
    });
    setup({ api });
    const shown =
      "Sprawdź „32 year” w sekcji „Dlaczego nasz kandydat”: tej liczby lat nie ma w oryginale i nie wynika ona z dat stanowisk.";
    expect(await screen.findByText(shown)).toBeInTheDocument();
    expect(screen.queryByText(raw)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: `OK, sprawdzone: ${shown}` }));
    await waitFor(() =>
      expect(api.dismissIssue).toHaveBeenCalledWith(STAGE, { source: "generator", text: raw, status: null, reason: "kept" }),
    );
  });

  it("„Kandydat to ma”: notatka z tym, co powiedział, i świeże QC", async () => {
    const api = memoryApi({ qc: vi.fn(async () => qcResult({ checks: KEYED })) });
    setup({ api });
    fireEvent.click(await screen.findByRole("button", { name: "Kandydat to ma" }));
    const field = screen.getByLabelText("Co powiedział kandydat? (opcjonalnie)");
    fireEvent.change(field, { target: { value: " AWS w projekcie migracji " } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz w notatkach" }));
    await waitFor(() => expect(api.confirm).toHaveBeenCalledWith(STAGE, { term: "AWS", text: "AWS w projekcie migracji" }));
    expect(toast.showSuccess).toHaveBeenCalledWith("Potwierdzenie zapisane w notatkach kandydata.");
    expect(await screen.findByText("Nic nie blokuje wysyłki")).toBeInTheDocument();
  });

  it("„Jest w oryginale”: pominięcie „pod inną nazwą” z fragmentem, który sprawdzi serwer", async () => {
    const api = memoryApi({ qc: vi.fn(async () => qcResult({ checks: KEYED })) });
    setup({ api });
    fireEvent.click(await screen.findByRole("button", { name: "Jest w oryginale" }));
    fireEvent.click(screen.getByRole("button", { name: "Pomiń uwagę" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Wklej fragment");
    expect(api.dismiss).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Jak to brzmi w oryginale? Wklej fragment"), {
      target: { value: "Amazon Web Services (EC2, S3)" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Pomiń uwagę" }));
    await waitFor(() =>
      expect(api.dismiss).toHaveBeenCalledWith(STAGE, {
        check_key: "no_unsupported",
        key: "no_unsupported|aws|cv",
        reason: "other_name",
        quote: "Amazon Web Services (EC2, S3)",
      }),
    );
  });

  it("„To nieprawda” przy uwadze generatora: powód bez fragmentu źródła, świeża lista, wpis w „Pominięte”", async () => {
    const after: CvEditorIssuesData = {
      ...ISSUES,
      generator_warnings: ["Wyróżnienia: pogrubiono 4 terminy."],
      dismissed: [{ source: "generator", text: "MUST-HAVE: brak Kafka w źródłach.", status: null, dismissal: { ...DISMISSAL, id: 52 } }],
    };
    const api = memoryApi({ dismissIssue: vi.fn(async () => after) });
    setup({ api });
    await screen.findByText("MUST-HAVE: brak Kafka w źródłach.");
    const row = expand(itemOf("MUST-HAVE: brak Kafka w źródłach."));
    fireEvent.click(within(row).getByRole("button", { name: "To nieprawda" }));
    const form = within(row).getByRole("form", { name: "To nieprawda: MUST-HAVE: brak Kafka w źródłach." });
    fireEvent.click(within(form).getByRole("radio", { name: "Jest w źródłach pod inną nazwą" }));
    // Fragment źródła dotyczy tylko QC — uwaga generatora go nie potrzebuje.
    expect(within(form).queryByLabelText("Fragment źródła")).toBeNull();
    fireEvent.change(within(form).getByLabelText("Opis (opcjonalnie)"), {
      target: { value: " w notatce jako Apache Kafka " },
    });
    fireEvent.click(within(form).getByRole("button", { name: SUBMIT }));
    await waitFor(() =>
      expect(api.dismissIssue).toHaveBeenCalledWith(STAGE, {
        source: "generator",
        text: "MUST-HAVE: brak Kafka w źródłach.",
        status: null,
        reason: "other_name",
        note: "w notatce jako Apache Kafka",
      }),
    );
    expect(toast.showSuccess).toHaveBeenCalledWith("Oznaczono jako nieprawdę.");
    await waitFor(() => expect(screen.queryByText("MUST-HAVE: brak Kafka w źródłach.")).not.toBeInTheDocument());
  });

  it("„To nieprawda” przy kontroli AI: tekst linii i status idą do serwera; „Inny powód” wymaga opisu", async () => {
    const api = memoryApi();
    setup({ api });
    await screen.findByText("„Przeglądy kodu.”");
    const review = expand(itemOf("„Przeglądy kodu.”"));
    fireEvent.click(within(review).getByRole("button", { name: "To nieprawda" }));
    const form = within(review).getByRole("form", { name: "To nieprawda: „Przeglądy kodu.”" });
    fireEvent.click(within(form).getByRole("radio", { name: "Inny powód" }));
    fireEvent.click(within(form).getByRole("button", { name: SUBMIT }));
    expect(within(form).getByRole("alert")).toHaveTextContent("Przy „Inny powód” opisz");
    expect(api.dismissIssue).not.toHaveBeenCalled();
    fireEvent.change(within(form).getByLabelText("Opis (wymagany)"), { target: { value: "Robił to w Banku Przykładowym" } });
    fireEvent.click(within(form).getByRole("button", { name: SUBMIT }));
    await waitFor(() =>
      expect(api.dismissIssue).toHaveBeenCalledWith(STAGE, {
        source: "review",
        text: "Przeglądy kodu.",
        status: "unsupported",
        reason: "other",
        note: "Robił to w Banku Przykładowym",
      }),
    );
  });

  it("odmowa serwera przy uwadze — komunikat serwera", async () => {
    const api = memoryApi({
      dismissIssue: vi.fn(async () =>
        Promise.reject({
          response: { status: 422, data: { detail: { code: "CV_ISSUE_DISMISS_FAILED", message: "Tej uwagi już nie ma — odśwież panel." } } },
        }),
      ),
    });
    setup({ api });
    fireEvent.click(await screen.findByRole("button", { name: "OK, sprawdzone: MUST-HAVE: brak Kafka w źródłach." }));
    await waitFor(() => expect(toast.showError).toHaveBeenCalledWith("Tej uwagi już nie ma — odśwież panel."));
    expect(screen.getByText("MUST-HAVE: brak Kafka w źródłach.")).toBeInTheDocument();
  });

  it("pozycja QC: pominięcie trafia do panelu i do okna QC, „Przywróć” wraca", async () => {
    const afterChecks: QcCheck[] = [
      { ...KEYED[0], status: "pass", items: [], dismissed_items: [{ ...KEYED[0].items[0], dismissal: DISMISSAL }] },
      KEYED[1],
      KEYED[2],
    ];
    const api = memoryApi({
      qc: vi.fn(async () => qcResult({ checks: KEYED })),
      dismiss: vi.fn(async () => qcResult({ blocking_failed: 0, checks: afterChecks })),
      restore: vi.fn(async () => qcResult({ checks: KEYED })),
    });
    const { client } = setup({ api });
    await screen.findByText("AWS — jest w CV, a nie ma tego w oryginale");
    const task = expand(itemOf("AWS — jest w CV, a nie ma tego w oryginale"));
    fireEvent.click(within(task).getByRole("button", { name: "To nieprawda" }));
    const form = within(task).getByRole("form", { name: "To nieprawda: AWS" });
    fireEvent.click(within(form).getByRole("radio", { name: "Jest w CV — QC tego nie znalazło" }));
    fireEvent.click(within(form).getByRole("button", { name: SUBMIT }));
    await waitFor(() =>
      expect(api.dismiss).toHaveBeenCalledWith(STAGE, { check_key: "no_unsupported", key: "no_unsupported|aws|cv", reason: "in_cv" }),
    );
    expect(await screen.findByText("Nic nie blokuje wysyłki")).toBeInTheDocument();
    expect(client.getQueryData<QcResult>(cvQcQueryKey(STAGE))?.blocking_failed).toBe(0);

    const dismissed = screen.getByRole("region", { name: "Pominięte" });
    fireEvent.click(within(dismissed).getByRole("button", { name: /Pominięte \(1\)/ }));
    const entry = within(dismissed).getByRole("listitem");
    expect(entry).toHaveTextContent("AWS");
    expect(entry).toHaveTextContent("Zgodność z oryginałem");
    fireEvent.click(within(entry).getByRole("button", { name: "Przywróć" }));
    await waitFor(() => expect(api.restore).toHaveBeenCalledWith(STAGE, 41));
    expect(await screen.findByText("1 blokuje wysyłkę")).toBeInTheDocument();
  });

  it("bez prawa obejścia blokady nie da się pominąć ani „Jest w oryginale” — uwagę tak", async () => {
    setup({ api: memoryApi({ qc: vi.fn(async () => qcResult({ can_override: false, checks: KEYED })) }) });
    await screen.findByText("AWS — jest w CV, a nie ma tego w oryginale");
    const task = expand(itemOf("AWS — jest w CV, a nie ma tego w oryginale"));
    expect(within(task).queryByRole("button", { name: "To nieprawda" })).not.toBeInTheDocument();
    expect(within(task).queryByRole("button", { name: "Jest w oryginale" })).not.toBeInTheDocument();
    expect(within(task).getByRole("button", { name: "Kandydat to ma" })).toBeInTheDocument();
    const bold = expand(itemOf("Pogrub: Java"));
    expect(within(bold).getByRole("button", { name: "To nieprawda" })).toBeInTheDocument();
  });

  it("blokada w kilku rolach: „To nieprawda” przy każdej roli osobno (przegląd 17.10)", async () => {
    const critical = check({
      key: "critical_skills",
      label: "Umiejętności krytyczne",
      severity: "blocking",
      items: [
        { key: "critical_skills|java|alfa", requirement: "Java", role: "Alfa — Developer", role_index: 0, evidence_kind: "technologies" },
        { key: "critical_skills|java|beta", requirement: "Java", role: "Beta — Developer", role_index: 1, evidence_kind: "technologies" },
      ],
    });
    const api = memoryApi({ qc: vi.fn(async () => qcResult({ checks: [critical, ...KEYED.slice(1)] })) });
    setup({ api });
    await screen.findByText("Java — brak opisu w 2 rolach");
    const task = expand(itemOf("Java — brak opisu w 2 rolach"));
    const dismissButtons = within(task).getAllByRole("button", { name: "To nieprawda" });
    expect(dismissButtons).toHaveLength(2);
    fireEvent.click(dismissButtons[1]);
    const form = within(task).getByRole("form", { name: "To nieprawda: Java · Beta — Developer" });
    fireEvent.click(within(form).getByRole("radio", { name: "Dotyczy innej roli albo sekcji" }));
    fireEvent.click(within(form).getByRole("button", { name: SUBMIT }));
    await waitFor(() =>
      expect(api.dismiss).toHaveBeenCalledWith(STAGE, {
        check_key: "critical_skills",
        key: "critical_skills|java|beta",
        reason: "wrong_place",
      }),
    );
  });

  it("„Przywróć” przy uwadze kontroli AI woła trasę edytora z id pominięcia", async () => {
    const api = memoryApi({
      issues: vi.fn(async () => ({
        ...ISSUES,
        dismissed: [
          {
            source: "review" as const,
            text: "Mentoring zespołu.",
            status: "contradicted",
            dismissal: { ...DISMISSAL, id: 52, reason: "other", reason_label: "Inny powód", note: "potwierdzone w rozmowie" },
          },
        ],
      })),
    });
    setup({ api });
    const dismissed = await screen.findByRole("region", { name: "Pominięte" });
    fireEvent.click(within(dismissed).getByRole("button", { name: /Pominięte \(1\)/ }));
    const entry = within(dismissed).getByRole("listitem");
    expect(entry).toHaveTextContent("Mentoring zespołu.");
    expect(entry).toHaveTextContent("Kontrola AI");
    expect(entry).toHaveTextContent("Inny powód — „potwierdzone w rozmowie”");
    fireEvent.click(within(entry).getByRole("button", { name: "Przywróć" }));
    await waitFor(() => expect(api.restoreIssue).toHaveBeenCalledWith(STAGE, 52));
    await waitFor(() => expect(toast.showSuccess).toHaveBeenCalledWith("Uwaga przywrócona."));
  });

  it("uwaga wyciszona w „Jakość QC” nie liczy się do paska i stoi jako informacja", async () => {
    const muted = KEYED.map((c) => (c.key === "must_bolded" ? { ...c, muted: true } : c));
    const { counts } = setup({ api: memoryApi({ qc: vi.fn(async () => qcResult({ checks: muted })) }) });
    expect(await screen.findByRole("region", { name: "Informacje — wyciszone w „Jakość QC”" })).toHaveTextContent(
      "Must-have pogrubione",
    );
    expect(screen.queryByRole("region", { name: "Do poprawy" })).not.toBeInTheDocument();
    // 1 blokująca + 1 uwaga generatora + 1 linia kontroli AI — bez wyciszonej.
    await waitFor(() => expect(counts.at(-1)).toMatchObject({ total: 3, blocking: 1, state: "ready" }));
  });

  it("edytor wyniku generatora (bez rekrutacji) nie ma „To nieprawda” — nie ma pary", async () => {
    setup({ props: { stageId: undefined, generatorWarnings: ["MUST-HAVE: brak Kafka w źródłach."] } });
    expect(screen.getByRole("region", { name: "Uwagi generatora" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "To nieprawda" })).not.toBeInTheDocument();
  });
});

describe("lata, tytuł, stawka i zdanie z kontroli AI jednym kliknięciem (PR 2, 17.10.2026)", () => {
  const PR2_CHECKS: QcCheck[] = [
    check({
      key: "client_rules",
      label: "Reguły klienta",
      severity: "blocking",
      items: [{ detail: "Stawka w CV: „150 zł/h”. Usuń — stawek w CV nie wysyłamy." }],
    }),
    check({
      key: "years_header",
      label: "Lata doświadczenia zgodne z historią",
      items: [{ term: "Ponad 10 lat", detail: "Nagłówek mówi „Ponad 10 lat”, a z dat historii wychodzi 7." }],
    }),
    check({
      key: "title_matches_role",
      label: "Tytuł CV zgodny ze stanowiskiem",
      items: [{ term: "Senior Java Developer", detail: "Początek CV nie mówi „Senior Java Developer” — sprawdź tytuł w nagłówku." }],
    }),
  ];

  it("każda uwaga ma swój przycisk, a serwer dostaje akcję bez tekstu od klienta (poza linią kontroli AI)", async () => {
    const api = memoryApi({ qc: vi.fn(async () => qcResult({ checks: PR2_CHECKS })) });
    const { editor } = setup({ api });
    const before = editor.getHTML();

    const rate = await screen.findByRole("button", { name: "Usuń stawkę" });
    fireEvent.click(rate);
    await waitFor(() => expect(api.transform).toHaveBeenLastCalledWith(STAGE, { content_html: before, actions: [{ action: "strip_client_rules" }], bulk: false }));

    const fixable = screen.getByRole("region", { name: "Do poprawy" });
    expect(fixable).toHaveTextContent("Ponad 10 lat Ponad 7 lat");
    expect(fixable).toHaveTextContent("Tytuł CV: Senior Java Developer");
    expect(within(fixable).getByRole("button", { name: /Popraw wszystkie \(2\)/ })).toBeInTheDocument();

    await waitFor(() => expect(within(fixable).getByRole("button", { name: "Zmień lata według historii" })).toBeEnabled());
    fireEvent.click(within(fixable).getByRole("button", { name: "Zmień lata według historii" }));
    await waitFor(() => expect(api.transform).toHaveBeenLastCalledWith(STAGE, expect.objectContaining({ actions: [{ action: "years" }] })));
    await waitFor(() => expect(within(fixable).getByRole("button", { name: "Wpisz tytuł: Senior Java Developer" })).toBeEnabled());
    fireEvent.click(within(fixable).getByRole("button", { name: "Wpisz tytuł: Senior Java Developer" }));
    await waitFor(() => expect(api.transform).toHaveBeenLastCalledWith(STAGE, expect.objectContaining({ actions: [{ action: "title" }] })));
  });

  it("„prawie to samo jest w źródłach” (D1-A): bez „Usuń zdanie”, tylko „Zostaw”", async () => {
    const api = memoryApi({
      issues: vi.fn(
        async (): Promise<CvEditorIssuesData> => ({
          ...ISSUES,
          content_review: { status: "reviewed", version: 2, findings: [{ text: "Przeglądy kodu.", status: "weak" }] },
        }),
      ),
    });
    setup({ api });
    await screen.findByText("„Przeglądy kodu.”");
    const row = itemOf("„Przeglądy kodu.”");
    expect(row).toHaveTextContent("prawie to samo jest w źródłach — sprawdź brzmienie");
    expect(within(row).queryByRole("button", { name: /Usuń zdanie/ })).toBeNull();
    expect(within(row).getByRole("button", { name: "Zostaw: „Przeglądy kodu.”" })).toBeInTheDocument();
  });

  it("luki kandydata (D2): jedna linia w „Informacje”, bez pozycji do poprawy", async () => {
    const gaps = check({
      key: "must_in_cv",
      label: "Pozostałe wymagania",
      status: "pass",
      items: [],
      info: [
        { requirement: "Terraform", detail: "Luka kandydata — nie ma tego w CV, w oryginale ani w rozmowie.", fix: "ask_candidate" },
        { requirement: "Ansible", detail: "Luka kandydata — nie ma tego w CV, w oryginale ani w rozmowie.", fix: "ask_candidate" },
      ],
    });
    const api = memoryApi({ qc: vi.fn(async () => qcResult({ checks: [gaps] })) });
    setup({ api });
    const info = await screen.findByRole("region", { name: "Informacje" });
    expect(info).toHaveTextContent("Luki kandydata (2): Terraform, Ansible — nie ma tego w CV, w oryginale ani w rozmowie.");
    expect(screen.queryByText(/Terraform/, { selector: "button" })).toBeNull();
  });

  it("„Usuń zdanie” przy kontroli AI usuwa tę linię", async () => {
    const api = memoryApi();
    setup({ api });
    fireEvent.click(await screen.findByRole("button", { name: "Usuń zdanie: „Przeglądy kodu.”" }));
    await waitFor(() =>
      expect(api.transform).toHaveBeenCalledWith(STAGE, expect.objectContaining({ actions: [{ action: "remove_line", text: "Przeglądy kodu." }], bulk: false })),
    );
  });
});

describe("zgoda RODO i rola bez dat w panelu (PR 4, 17.10.2026)", () => {
  const CONSENT: QcCheck = check({
    key: "client_rules",
    label: "Reguły klienta",
    severity: "blocking",
    items: [{ detail: "Brak zrzutu zgody RODO (wymóg klienta).", fix: "upload_consent" }],
  });

  it("brak zgody: zrzut wgrywa się w wierszu blokady, a po nim QC liczy się od nowa", async () => {
    const qc = vi
      .fn()
      .mockResolvedValueOnce(qcResult({ checks: [CONSENT] }))
      .mockResolvedValue(qcResult({ checks: [], blocking_failed: 0, passed: true }));
    setup({ api: memoryApi({ qc }) });
    const blocking = await screen.findByRole("region", { name: "Blokuje wysyłkę" });
    const upload = within(blocking).getByRole("button", { name: "Wgraj zrzut maila" });
    // CV z generatora: zgoda idzie do dokumentu generatora (serwer odświeża kopię etapu).
    expect(upload).toHaveAttribute("data-generated", "77");
    expect(within(blocking).queryByText(/otwórz generator/)).not.toBeInTheDocument();

    fireEvent.click(upload);
    await waitFor(() => expect(qc).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Blokuje wysyłkę" })).not.toBeInTheDocument());
  });

  it("kopia bez generatora: zgoda na etapie, na którym leży CV", async () => {
    const base = qcResult();
    const api = memoryApi({
      qc: vi.fn(async () => qcResult({ checks: [CONSENT], cv: { ...base.cv!, generated_document_id: null } })),
    });
    setup({ api });
    const upload = await screen.findByRole("button", { name: "Wgraj zrzut maila" });
    expect(upload).toHaveAttribute("data-generated", "");
    expect(upload).toHaveAttribute("data-stage", `101:${STAGE}`);
  });

  it("rola bez dat mówi, o którą rolę chodzi", async () => {
    const api = memoryApi({
      qc: vi.fn(async () =>
        qcResult({
          checks: [check({ key: "dates", label: "Każda rola ma daty", items: [{ role: "Analityk · Bank Przykładowy", detail: "Rola bez dat.", role_index: 1 }] })],
        }),
      ),
    });
    setup({ api });
    expect(await screen.findByText("Analityk · Bank Przykładowy: brak dat")).toBeInTheDocument();
    expect(screen.queryByText("Rola bez dat.")).not.toBeInTheDocument();
  });
});

describe("zdania AI w wierszu swojej uwagi (D5, 14.10.2026 → wariant A)", () => {
  const AI_CHECKS: QcCheck[] = [
    ...CHECKS,
    check({
      key: "must_in_roles",
      label: "Wymagania opisane w rolach",
      items: [{ requirement: "Kafka", role: "Bank Przykładowy — Senior Developer", fix: "ai", role_index: 0 }],
    }),
  ];
  const KAFKA_FIX = {
    id: "f-kafka",
    check_key: "must_in_roles",
    requirement: "Kafka",
    role: "Bank Przykładowy — Senior Developer",
    role_index: 0,
    current_text: "Przeglądy kodu.",
    proposed_text: "Przeglądy kodu i integracje przez **Kafka**.",
    source: "original" as const,
    source_quote: "Integracje przez Kafkę w banku",
  };

  it("bez klikania: zdanie stoi w wierszu uwagi, „Dopisz” nakłada je, a „Popraw wszystkie” bierze je od razu", async () => {
    const api = memoryApi({
      qc: vi.fn(async () => qcResult({ checks: AI_CHECKS })),
      fixes: vi.fn(async () => ({ status: "ok" as const, cached: true, fixes: [KAFKA_FIX] })),
    });
    const { editor } = setup({ api });
    // QC, potem propozycje — dwa zapytania po kolei.
    const dopisz = await screen.findByRole("button", { name: "Dopisz: Kafka" }, { timeout: 5000 });
    const row = dopisz.closest("li") as HTMLElement;
    expect(row).toHaveTextContent("Kafka · Bank Przykładowy — Senior Developer");
    expect(row).toHaveTextContent("Przeglądy kodu i integracje przez Kafka.");
    expect(row).toHaveTextContent("z oryginalnego CV");
    expect(api.fixes).toHaveBeenCalledWith(STAGE);

    fireEvent.click(screen.getByRole("button", { name: /Popraw wszystkie \(2\)/ }));
    await waitFor(() =>
      expect(api.transform).toHaveBeenCalledWith(STAGE, {
        content_html: editor.getHTML(),
        actions: [{ action: "ai_fix", fix_id: "f-kafka" }, { action: "bold_all", scope: "must" }],
        bulk: true,
      }),
    );
  });

  it("„Edytuj zdanie” w szczegółach dopisuje własny tekst pojedynczo", async () => {
    const api = memoryApi({
      qc: vi.fn(async () => qcResult({ checks: AI_CHECKS })),
      fixes: vi.fn(async () => ({ status: "ok" as const, cached: true, fixes: [KAFKA_FIX] })),
    });
    const { editor } = setup({ api });
    const row = (await screen.findByRole("button", { name: "Dopisz: Kafka" }, { timeout: 5000 })).closest("li") as HTMLElement;
    expand(row);
    fireEvent.click(within(row).getByRole("button", { name: "Edytuj zdanie" }));
    fireEvent.change(within(row).getByLabelText("Treść zdania"), { target: { value: "Przeglądy kodu; kolejki **Kafka**." } });
    fireEvent.click(within(row).getByRole("button", { name: "Dopisz edytowane" }));
    await waitFor(() =>
      expect(api.transform).toHaveBeenCalledWith(STAGE, {
        content_html: editor.getHTML(),
        actions: [{ action: "ai_fix", fix_id: "f-kafka", text: "Przeglądy kodu; kolejki **Kafka**." }],
        bulk: false,
      }),
    );
  });

  it("bez pozycji z poprawką AI nic nie pobiera", async () => {
    const api = memoryApi();
    setup({ api });
    expect(await screen.findByText("1 blokuje wysyłkę")).toBeInTheDocument();
    await screen.findByRole("button", { name: /Popraw wszystkie/ });
    expect(api.fixes).not.toHaveBeenCalled();
  });

  it("w trakcie mówi „Przygotowuję zdanie…”, po awarii daje „Ponów” w wierszu", async () => {
    let fail = true;
    let release: () => void = () => undefined;
    const api = memoryApi({
      qc: vi.fn(async () => qcResult({ checks: AI_CHECKS })),
      fixes: vi.fn(
        () =>
          new Promise<QcFixesResponse>((resolve, reject) => {
            release = () => (fail ? reject(new Error("model niedostępny")) : resolve({ status: "ok", cached: false, fixes: [KAFKA_FIX] }));
          }),
      ),
    });
    setup({ api });
    expect(await screen.findByText("Przygotowuję zdanie…")).toBeInTheDocument();
    await act(async () => release());
    expect(await screen.findByText(/Propozycje AI są chwilowo niedostępne/)).toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
    await waitFor(() => expect(api.fixes).toHaveBeenCalledTimes(2));
    await act(async () => release());
    expect(await screen.findByRole("button", { name: "Dopisz: Kafka" }, { timeout: 5000 })).toBeInTheDocument();
  });

  it("kilka zdań AI do jednej blokady: każde ma „Odrzuć”, odrzucone wypada z „Popraw wszystkie” (przegląd 17.10)", async () => {
    const critical = check({
      key: "critical_skills",
      label: "Umiejętności krytyczne",
      severity: "blocking",
      items: [
        { key: "critical_skills|kafka|alfa", requirement: "Kafka", role: "Alfa — Developer", role_index: 0, fix: "ai", evidence_kind: "description" },
        { key: "critical_skills|kafka|beta", requirement: "Kafka", role: "Beta — Developer", role_index: 1, fix: "ai", evidence_kind: "description" },
      ],
    });
    const fix = (id: string, roleIndex: number, role: string) => ({
      id,
      check_key: "critical_skills",
      requirement: "Kafka",
      role,
      role_index: roleIndex,
      cv_role_label: role,
      current_text: null,
      proposed_text: `Kolejki **Kafka** w ${role}.`,
      source: "original" as const,
      source_quote: "Kafka",
    });
    const api = memoryApi({
      qc: vi.fn(async () => qcResult({ checks: [critical, ...CHECKS.slice(1)] })),
      fixes: vi.fn(async () => ({
        status: "ok" as const,
        cached: true,
        fixes: [fix("f-alfa", 0, "Alfa — Developer"), fix("f-beta", 1, "Beta — Developer")],
      })),
    });
    setup({ api });
    expect(await screen.findByRole("button", { name: /Popraw wszystkie \(3\)/ }, { timeout: 5000 })).toBeInTheDocument();
    const proposals = screen.getByLabelText("Propozycje: Kafka");
    const lines = within(proposals).getAllByRole("listitem");
    expect(lines).toHaveLength(2);
    for (const line of lines) {
      expect(within(line).getByRole("button", { name: /^Dopisz/ })).toBeInTheDocument();
      expect(within(line).getByRole("button", { name: "Odrzuć propozycję" })).toBeInTheDocument();
      expect(within(line).getByRole("button", { name: "Edytuj zdanie" })).toBeInTheDocument();
    }
    fireEvent.click(within(lines[1]).getByRole("button", { name: "Odrzuć propozycję" }));
    expect(await screen.findByRole("button", { name: /Popraw wszystkie \(2\)/ })).toBeInTheDocument();
    // Jedna propozycja zostaje — wiersz pokazuje ją jak pojedynczą, z „Dopisz” po prawej.
    expect(screen.queryByLabelText("Propozycje: Kafka")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Dopisz: Kafka/ })).toHaveLength(1);
  });

  it("licznik do paska niesie wynik QC tej treści (stopka przekazania czyta z niego obejście)", async () => {
    const { counts } = setup();
    await waitFor(() =>
      expect(counts.at(-1)).toMatchObject({ state: "ready", qc: expect.objectContaining({ blocking_failed: 1, advisory: true }) }),
    );
  });
});

describe("zrzut zgody, którego AI nie potwierdziło (F37, 27.10.2026)", () => {
  it("uwaga ma miniaturę zrzutu i wymianę obok", async () => {
    const mismatch = check({
      key: "consent_matches",
      label: "Zrzut zgody RODO pasuje do kandydata i rekrutacji",
      items: [{ key: "consent_matches||cv", detail: "AI: Nadawca to nie kandydat.", fix: "replace_consent" }],
    });
    setup({ api: memoryApi({ qc: vi.fn(async () => qcResult({ checks: [mismatch] })) }) });
    const thumb = await screen.findByRole("button", { name: "Pokaż zrzut zgody" });
    expect(thumb).toHaveAttribute("data-stage", String(qcResult().stage_id));
    expect(screen.getByRole("button", { name: "Wgraj zrzut maila" })).toBeInTheDocument();
  });
});
