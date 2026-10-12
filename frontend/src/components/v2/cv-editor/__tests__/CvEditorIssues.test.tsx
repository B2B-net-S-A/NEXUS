import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Editor } from "@tiptap/core";

import type { CvEditorIssuesApi, CvEditorIssuesData } from "@/lib/api/cvEditorIssues";
import type { QcCheck, QcResult, QcTransformBody, QcTransformResult } from "@/lib/api/cvQc";
import { cvEditorExtensions, loadCvHtml } from "@/lib/cv-editor-structure";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

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

describe("panel „Do poprawy” w edytorze CV", () => {
  it("zbiera QC, uwagi generatora i kontrolę AI oraz podaje licznik do paska", async () => {
    const { counts, editor } = setup();
    expect(await screen.findByText("Blokuje wysyłkę: 1")).toBeInTheDocument();

    const tasks = screen.getByRole("region", { name: "Zalecane poprawki przed wysłaniem" });
    expect(within(tasks).getByText("AWS — jest w CV, a nie ma tego w oryginale")).toBeInTheDocument();
    expect(within(tasks).getByRole("button", { name: "Usuń „AWS” z CV" })).toBeEnabled();
    expect(screen.getByRole("region", { name: "Warto poprawić — nie blokuje" })).toHaveTextContent("Must-have pogrubione");

    const generator = await screen.findByRole("region", { name: "Uwagi generatora" });
    expect(generator).toHaveTextContent("MUST-HAVE: brak Kafka w źródłach.");
    // „Wyróżnienia: …” to informacja o tym, co generator zrobił — zwinięta.
    expect(generator).not.toHaveTextContent("pogrubiono 4 terminy");
    expect(within(generator).getByRole("button", { name: /Informacje \(1\)/ })).toHaveAttribute("aria-expanded", "false");

    // Kontrola AI: tylko linia, która nadal stoi w CV.
    const review = screen.getByRole("region", { name: "Kontrola AI" });
    expect(review).toHaveTextContent("Kontrola AI zatwierdzonej wersji v2 (1)");
    expect(review).toHaveTextContent("„Przeglądy kodu.”");
    expect(review).toHaveTextContent("bez pokrycia w źródłach");
    expect(review).not.toHaveTextContent("Linia, której już nie ma.");
    expect(review).toHaveTextContent("1 uwaga dotyczyła linii, której już nie ma w CV.");

    // 1 blokująca + 1 uwaga QC + 1 uwaga generatora + 1 linia kontroli AI.
    await waitFor(() => expect(counts.at(-1)).toEqual({ total: 4, blocking: 1, state: "ready" }));
    // Miejsca uwag są zaznaczone na kartce.
    await waitFor(() => expect(editor.view.dom.querySelector(".cv-issue-term.cv-issue--blocking")?.textContent).toBe("AWS"));
    // Panel nie ma obejścia QC ani ruchu karty.
    expect(screen.queryByRole("button", { name: /Przesuń|Przepuść/ })).not.toBeInTheDocument();
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
    expect(screen.queryByText(/Blokuje wysyłkę/)).not.toBeInTheDocument();
    expect(editor.view.dom.querySelector(".cv-issue-term")).toBeNull();
    // Uwagi generatora i kontroli AI należą do TEGO wiersza etapu — zostają.
    expect(await screen.findByRole("region", { name: "Uwagi generatora" })).toBeInTheDocument();
  });

  it("„Pokaż w CV” pokazuje kartkę i wyróżnia linię", async () => {
    const { editor, onShowCv } = setup();
    const review = await screen.findByRole("region", { name: "Kontrola AI" });
    fireEvent.click(within(review).getByRole("button", { name: "Pokaż w CV" }));
    expect(onShowCv).toHaveBeenCalled();
    await waitFor(() => expect(editor.view.dom.querySelector(".cv-issue-focus")?.textContent).toBe("Przeglądy kodu."));
    // Samo wskazanie miejsca nie zabiera fokusu z listy.
    expect(editor.view.dom).not.toHaveFocus();
  });

  it("miejsce, którego już nie ma, daje komunikat zamiast cichego niczego", async () => {
    const { editor } = setup();
    const tasks = await screen.findByRole("region", { name: "Zalecane poprawki przed wysłaniem" });
    const html = editor.getHTML().replace(" i AWS", "");
    loadCvHtml(editor, html);
    fireEvent.click(within(tasks).getByRole("button", { name: "Pokaż w CV" }));
    expect(toast.showError).toHaveBeenCalledWith(expect.stringContaining("Tego miejsca nie ma już w treści CV"));
  });

  it("poprawka: serwer liczy na treści z edytora, edytor nakłada ją jednym cofalnym krokiem", async () => {
    const { api, editor, ensureDraft } = setup();
    const before = editor.getHTML();
    const updates = vi.fn();
    editor.on("update", updates);
    const notes = await screen.findByRole("region", { name: "Warto poprawić — nie blokuje" });
    fireEvent.click(within(notes).getByRole("button", { name: /Must-have pogrubione/ }));
    fireEvent.click(within(notes).getByRole("button", { name: "Pogrub wszystkie" }));

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
    editor.commands.undo();
    expect(editor.getHTML()).toBe(before);
  });

  it("„Popraw wszystko” bierze tylko poprawki formalne i daje „Cofnij”", async () => {
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
    const bulk = await screen.findByRole("region", { name: "Popraw wszystko" });
    expect(bulk).toHaveTextContent("Jednym kliknięciem: pogrubienie 1 wymagania must-have.");
    fireEvent.click(within(bulk).getByRole("button", { name: "Popraw wszystko (1)" }));

    const outcome = await screen.findByRole("region", { name: "Wynik poprawek" });
    // Usunięcie „AWS” (treść) nie wchodzi do hurtu — zostaje na karcie.
    expect(api.transform).toHaveBeenCalledWith(STAGE, {
      content_html: before,
      actions: [{ action: "bold_all", scope: "must" }],
      bulk: true,
    });
    expect(outcome).toHaveTextContent("Nałożono: 1 poprawkę.");
    expect(outcome).toHaveTextContent("Pominięto: Nie ma pisowni do poprawienia.");
    expect(editor.getHTML()).toContain("<strong>Java</strong>");

    fireEvent.click(within(outcome).getByRole("button", { name: "Cofnij" }));
    expect(editor.getHTML()).toBe(before);
    expect(screen.queryByRole("region", { name: "Wynik poprawek" })).not.toBeInTheDocument();
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
    fireEvent.click(await screen.findByRole("button", { name: "Usuń „AWS” z CV" }));
    await waitFor(() =>
      expect(toast.showError).toHaveBeenCalledWith("„AWS” nie stoi na liście technologii — usuń je w edytorze CV."),
    );
    expect(editor.getHTML()).toBe(before);
    expect(editor.can().undo()).toBe(false);
  });

  it("nie udało się założyć szkicu na zatwierdzonej wersji — poprawka nie rusza treści", async () => {
    const { editor, ensureDraft } = setup();
    const before = editor.getHTML();
    ensureDraft.mockResolvedValueOnce(false);
    const notes = await screen.findByRole("region", { name: "Warto poprawić — nie blokuje" });
    fireEvent.click(within(notes).getByRole("button", { name: /Must-have pogrubione/ }));
    fireEvent.click(within(notes).getByRole("button", { name: "Pogrub wszystkie" }));
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
    fireEvent.click(await screen.findByRole("button", { name: "Usuń „AWS” z CV" }));
    await waitFor(() => expect(toast.showError).toHaveBeenCalledWith("Nie ma czego usunąć."));
    expect(order).toEqual(["transform"]);
  });

  it("pusta treść z serwera nie zastępuje CV", async () => {
    const api = memoryApi({
      transform: vi.fn(async () => ({ content_html: "  ", changed: true, applied: [{ action: "spelling" }], skipped: [] })),
    });
    const { editor, ensureDraft } = setup({ api });
    const before = editor.getHTML();
    fireEvent.click(await screen.findByRole("button", { name: "Usuń „AWS” z CV" }));
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
    fireEvent.click(await screen.findByRole("button", { name: "Usuń „AWS” z CV" }));
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
    expect(await screen.findByRole("button", { name: "Usuń „AWS” z CV" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Popraw wszystko (1)" })).toBeDisabled();
  });

  it("po autozapisie liczy QC od nowa, a przy niezapisanych zmianach mówi, czego dotyczy lista", async () => {
    const { api, rerender } = setup();
    await screen.findByText("Blokuje wysyłkę: 1");
    expect(api.qc).toHaveBeenCalledTimes(1);

    vi.useFakeTimers();
    rerender({ unsaved: true });
    expect(screen.getByRole("status")).toHaveTextContent("Lista dotyczy ostatnio zapisanej treści");
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
    await screen.findByText("Blokuje wysyłkę: 1");
    untouched.view.unmount();
    expect(untouched.api.persistQc).not.toHaveBeenCalled();

    const edited = setup();
    await screen.findByText("Blokuje wysyłkę: 1");
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
    await screen.findByText("Blokuje wysyłkę: 1");
    first.view.unmount();

    setup({ api, client });
    expect(await screen.findByText("Nic nie blokuje wysyłki")).toBeInTheDocument();
    expect(screen.queryByText("Blokuje wysyłkę: 1")).not.toBeInTheDocument();
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
    await waitFor(() => expect(down.counts.at(-1)).toEqual({ total: 0, blocking: 0, state: "failed" }));
    down.view.unmount();

    const fine = setup();
    await waitFor(() => expect(fine.counts.at(-1)).toEqual({ total: 4, blocking: 1, state: "ready" }));
  });

  it("nieudany zapis przebiegu QC przy zamknięciu trafia do zgłaszania błędów zapytań", async () => {
    const failures: unknown[] = [];
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
      queryCache: new QueryCache({ onError: (error) => failures.push(error) }),
    });
    const boom = new Error("500");
    const { view, rerender } = setup({ client, api: memoryApi({ persistQc: vi.fn(async () => Promise.reject(boom)) }) });
    await screen.findByText("Blokuje wysyłkę: 1");
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
    await waitFor(() => expect(counts.at(-1)).toEqual({ total: 1, blocking: 0, state: "ready" }));
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
