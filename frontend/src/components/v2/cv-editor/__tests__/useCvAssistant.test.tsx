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
