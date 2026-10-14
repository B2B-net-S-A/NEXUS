/**
 * Logika asystenta w kolumnie edytora CV (Edytor CV 3, PR 4) na prawdziwym
 * edytorze Tiptap, z podstawionym API. Przeklikanie w oknie edytora:
 * `app/preview/__tests__/cv-editor-harness.test.tsx`.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { Editor } from "@tiptap/core";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }));

import { useCvAssistant } from "@/components/v2/cv-editor/useCvAssistant";
import type { CvCommandResponse, CvEditorCommandApi } from "@/lib/api/cvEditorCommand";
import { cvEditorExtensions, loadCvHtml } from "@/lib/cv-editor-structure";

const CLAUSE = "Wyrażam zgodę na przetwarzanie moich danych osobowych przez Firmę Przykładową.";
const CV =
  "<h1>Dev – Anna Przykładowa</h1>" + // 0
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' + // 1
  '<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – 2024</p>' + // 2
  '<p data-cv-section="employer">Bank Przykładowy · Bankowość</p>' + // 3
  '<p data-cv-section="duties_label">Zakres zadań:</p>' + // 4
  "<ul><li><p>Rozwój usług w <strong>Java 17</strong>.</p></li>" + // 5
  "<li><p>Udział w planowaniu sprintów.</p></li></ul>" + // 6
  `<p data-cv-section="rodo">${CLAUSE}</p>`;

const editors: Editor[] = [];

function open(html = CV): Editor {
  const editor = new Editor({ extensions: cvEditorExtensions(), content: "" });
  loadCvHtml(editor, html);
  editors.push(editor);
  return editor;
}

afterEach(() => {
  while (editors.length) editors.pop()?.destroy();
});

/** Plan z jednym dopisaniem faktu spoza CV — asystent pyta o źródło. */
const TERRAFORM: CvCommandResponse = {
  status: "ok",
  operations: [
    {
      id: 0,
      type: "add",
      lines: [5],
      text: "Infrastruktura jako kod w **Terraform**.",
      why: "Dopisany punkt z rozmowy z kandydatem.",
      loses: [],
      new_words: [],
      ask: "source",
      problem: "Terraform",
    },
  ],
  dropped: [],
  message: null,
};

function api(): CvEditorCommandApi & { confirmFact: ReturnType<typeof vi.fn> } {
  return { plan: vi.fn(async () => TERRAFORM), confirmFact: vi.fn(async () => undefined) };
}

async function askTerraform(editor: Editor, commandApi: CvEditorCommandApi) {
  const hook = renderHook(() =>
    useCvAssistant({ editor, stageId: 7, disabled: false, ensureDraft: async () => true, api: commandApi }),
  );
  act(() => hook.result.current.send({ command: "dopisz terraform" }));
  await waitFor(() => expect(hook.result.current.messages.some((message) => message.question)).toBe(true));
  const question = hook.result.current.messages.find((message) => message.question);
  return { hook, id: question!.id };
}

describe("useCvAssistant — pytanie o źródło faktu", () => {
  it("„Tak, dopisz”: najpierw notatka, potem punkt w CV", async () => {
    const editor = open();
    const commandApi = api();
    const { hook, id } = await askTerraform(editor, commandApi);
    expect(editor.getHTML()).not.toContain("Terraform");

    await act(() => hook.result.current.answer(id, true));
    expect(commandApi.confirmFact).toHaveBeenCalledTimes(1);
    expect(commandApi.confirmFact).toHaveBeenCalledWith(7, {
      term: "Terraform",
      text: "Infrastruktura jako kod w **Terraform**.",
    });
    expect(editor.getHTML()).toContain("Infrastruktura jako kod w <strong>Terraform</strong>.");
    expect(hook.result.current.messages.find((message) => message.id === id)?.question?.state).toBe("yes");
  });

  it("wiersza już nie ma: bez notatki — powtórne „Tak” nie zapisze faktu dwa razy", async () => {
    const editor = open();
    const commandApi = api();
    const { hook, id } = await askTerraform(editor, commandApi);
    // Rekruter usuwa punkt, po którym asystent chciał dopisać fakt.
    act(() => loadCvHtml(editor, CV.replace("<li><p>Rozwój usług w <strong>Java 17</strong>.</p></li>", "")));

    await act(() => hook.result.current.answer(id, true));
    expect(commandApi.confirmFact).not.toHaveBeenCalled();
    expect(editor.getHTML()).not.toContain("Terraform");
    expect(hook.result.current.messages.at(-1)?.text).toBe(
      "CV zmieniło się w międzyczasie — napisz jeszcze raz, co zmienić.",
    );
    expect(hook.result.current.messages.find((message) => message.id === id)?.question?.state).toBe("open");
  });
});

describe("useCvAssistant — odpowiedź na pytanie po innych zmianach", () => {
  // Przegląd PR 4: ten sam punkt w dwóch stanowiskach — po przesunięciu
  // numerów wierszy zmiana trafiała w pierwsze stanowisko zamiast w drugie.
  const TWINS =
    "<h1>Dev – Anna Przykładowa</h1>" + // 0
    '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' + // 1
    '<p data-cv-section="role"><strong>Developer</strong> 2021 – 2024</p>' + // 2
    '<p data-cv-section="employer">Bank Przykładowy · Bankowość</p>' + // 3
    "<ul><li><p>Code review.</p></li><li><p>Udział w planowaniu sprintów.</p></li></ul>" + // 4, 5
    '<p data-cv-section="role"><strong>Junior Developer</strong> 2018 – 2021</p>' + // 6
    '<p data-cv-section="employer">Software House Przykład · IT</p>' + // 7
    "<ul><li><p>Code review.</p></li></ul>" + // 8
    `<p data-cv-section="rodo">${CLAUSE}</p>`;

  const twinPlan: CvCommandResponse = {
    status: "ok",
    operations: [
      {
        id: 0,
        type: "replace",
        lines: [8],
        text: "Code review w **Terraform**.",
        why: "",
        loses: [],
        new_words: [],
        ask: "source",
        problem: "Terraform",
      },
    ],
    dropped: [],
    message: null,
  };

  it("ten sam tekst w dwóch stanowiskach: zmiana trafia w to, o które pytaliśmy", async () => {
    const editor = open(TWINS);
    const commandApi = { plan: vi.fn(async () => twinPlan), confirmFact: vi.fn(async () => undefined) };
    const { hook, id } = await askTerraform(editor, commandApi);
    // Inna zmiana w CV przed odpowiedzią — numery wierszy liczymy od nowa.
    act(() => loadCvHtml(editor, TWINS.replace("Udział w planowaniu sprintów.", "Planowanie sprintów.")));

    await act(() => hook.result.current.answer(id, true));
    const html = editor.getHTML();
    expect(html.indexOf("Code review.")).toBeGreaterThan(-1);
    expect(html.indexOf("Code review.")).toBeLessThan(html.indexOf("Junior Developer"));
    expect(html.indexOf("Terraform")).toBeGreaterThan(html.indexOf("Junior Developer"));
  });

  it("odpowiedź serwera po zablokowaniu edytora (zapis, przekazanie) nie zmienia CV", async () => {
    const editor = open();
    const before = editor.getHTML();
    let resolve: (value: CvCommandResponse) => void = () => undefined;
    const commandApi = {
      plan: vi.fn(() => new Promise<CvCommandResponse>((done) => (resolve = done))),
      confirmFact: vi.fn(async () => undefined),
    };
    const hook = renderHook(
      ({ disabled }) =>
        useCvAssistant({ editor, stageId: 7, disabled, ensureDraft: async () => true, api: commandApi }),
      { initialProps: { disabled: false } },
    );
    act(() => hook.result.current.send({ command: "skróć rolę w banku" }));
    hook.rerender({ disabled: true });
    await act(async () => {
      resolve({
        status: "ok",
        operations: [{ id: 0, type: "remove", lines: [6], text: null, why: "", loses: [], new_words: [] }],
        dropped: [],
        message: null,
      });
    });
    expect(editor.getHTML()).toBe(before);
    expect(hook.result.current.locked).toBe(false);
    expect(hook.result.current.messages.at(-1)?.text).toBe(
      "Odpowiedź przyszła, gdy CV się zapisywało — nic nie zmieniłem. Napisz jeszcze raz.",
    );
  });
});

describe("useCvAssistant — „Napisz od nowa” (PR 5)", () => {
  it("zdanie „napisz od nowa: …” idzie do karty, nie do planu zmian", () => {
    const editor = open();
    const commandApi = api();
    const onRewrite = vi.fn();
    const hook = renderHook(() =>
      useCvAssistant({ editor, stageId: 7, disabled: false, ensureDraft: async () => true, api: commandApi, onRewrite }),
    );
    expect(hook.result.current.canRewrite).toBe(true);
    act(() => hook.result.current.send({ command: "Napisz CV od nowa — krócej, więcej o Kafce" }));
    expect(onRewrite).toHaveBeenCalledWith("krócej, więcej o Kafce");
    expect(commandApi.plan).not.toHaveBeenCalled();
    expect(hook.result.current.messages.at(-1)?.text).toMatch(/^Piszę CV od nowa/);
  });

  it("bez karty (edytor wyniku generatora) zdanie idzie do asystenta jak każde inne", async () => {
    const editor = open();
    const commandApi = api();
    const hook = renderHook(() =>
      useCvAssistant({ editor, stageId: 7, disabled: false, ensureDraft: async () => true, api: commandApi }),
    );
    expect(hook.result.current.canRewrite).toBe(false);
    act(() => hook.result.current.send({ command: "napisz od nowa: krócej" }));
    await waitFor(() => expect(commandApi.plan).toHaveBeenCalledTimes(1));
  });
});
