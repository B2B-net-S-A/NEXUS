import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Editor } from "@tiptap/core";
import { useState } from "react";

import type { CvCommandResponse, CvEditorCommandApi, CvPlanOperation } from "@/lib/api/cvEditorCommand";
import { cvLines } from "@/lib/cv-editor-command";
import { cvEditorExtensions, loadCvHtml } from "@/lib/cv-editor-structure";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

import { CvEditorCommandBar } from "../CvEditorCommandBar";
import { CvEditorPlan, operationTitle } from "../CvEditorPlan";
import { useCvCommandPlan } from "../useCvCommandPlan";

const CLAUSE = "Wyrażam zgodę na przetwarzanie moich danych osobowych.";
const CV =
  "<h1>Dev – Anna Przykładowa</h1>" + // 0
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' + // 1
  '<p data-cv-section="role"><strong>Senior Developer</strong> 2021 – 2024</p>' + // 2
  '<p data-cv-section="employer">Bank Przykładowy · Bankowość</p>' + // 3
  "<ul><li><p>Rozwój usług w <strong>Java 17</strong>.</p></li>" + // 4
  "<li><p>Integracje przez kolejki <strong>Kafka</strong>.</p></li>" + // 5
  "<li><p>Udział w spotkaniach zespołu.</p></li></ul>" + // 6
  "<h2>ZAINTERESOWANIA</h2>" + // 7
  "<p>Żeglarstwo, fotografia.</p>" + // 8
  `<p data-cv-section="rodo">${CLAUSE}</p>`;

function op(id: number, type: CvPlanOperation["type"], lines: number[], extra: Partial<CvPlanOperation> = {}): CvPlanOperation {
  return { id, type, lines, text: null, why: "", loses: [], ...extra };
}

const OPERATIONS = [
  op(0, "remove", [6], { why: "Ogólnik." }),
  op(1, "replace", [4], { text: "Rozwijała usługi w **Java 17**." }),
  op(2, "remove", [5], { loses: ["Kafka"] }),
  op(3, "remove_section", [7, 8]),
];

function reply(overrides: Partial<CvCommandResponse> = {}): CvCommandResponse {
  return { status: "ok", operations: OPERATIONS, dropped: [], message: null, ...overrides };
}

const editors: Editor[] = [];

function openEditor(): Editor {
  const element = document.body.appendChild(document.createElement("div"));
  const editor = new Editor({ element, extensions: cvEditorExtensions(), content: "" });
  loadCvHtml(editor, CV);
  editors.push(editor);
  return editor;
}

interface HostProps {
  editor: Editor;
  api: CvEditorCommandApi;
  ensureDraft: () => Promise<boolean>;
  disabled?: boolean;
  noStage?: boolean;
}

function Host({ editor, api, ensureDraft, disabled = false, noStage = false }: HostProps) {
  const [open, setOpen] = useState(true);
  const command = useCvCommandPlan({ editor, stageId: noStage ? undefined : 5, disabled, ensureDraft, api });
  return (
    <div data-locked={command.locked}>
      {open ? <CvEditorCommandBar controller={command} onClose={() => setOpen(false)} /> : null}
      {command.phase !== "idle" ? <CvEditorPlan controller={command} /> : null}
    </div>
  );
}

function setup(overrides: Partial<HostProps> = {}) {
  const editor = overrides.editor ?? openEditor();
  const plan = vi.fn<CvEditorCommandApi["plan"]>(async () => reply());
  const ensureDraft = vi.fn(async () => true);
  const props: HostProps = { editor, api: { plan }, ensureDraft, ...overrides };
  const view = render(<Host {...props} />);
  return { editor, plan: props.api.plan as typeof plan, ensureDraft: props.ensureDraft as typeof ensureDraft, view };
}

const bar = () => screen.getByRole("form", { name: "Polecenie dla całego CV" });
const field = () => within(bar()).getByRole("textbox");
const panel = () => screen.getByRole("region", { name: "Plan zmian" });
const operation = (id: number) => screen.getByTestId(`plan-operation-${id}`);

async function order(text = "Skróć CV, zostaw wszystko o Kafce") {
  fireEvent.change(field(), { target: { value: text } });
  fireEvent.click(within(bar()).getByRole("button", { name: "Przygotuj zmiany" }));
  await screen.findByRole("button", { name: /Zastosuj zaznaczone/ });
}

beforeAll(() => {
  const noRects = () => [] as unknown as DOMRectList;
  Range.prototype.getClientRects = noRects;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
  Element.prototype.getClientRects = noRects;
  Element.prototype.scrollIntoView = vi.fn();
  document.elementFromPoint = () => null;
});

beforeEach(() => {
  toast.showError.mockClear();
  toast.showSuccess.mockClear();
});

afterEach(() => {
  while (editors.length) {
    const editor = editors.pop()!;
    const mount = editor.view.dom.parentElement;
    editor.destroy();
    mount?.remove();
  }
});

describe("polecenie dla całego CV", () => {
  it("do serwera idą wiersze CV jako tekst; plan pokazuje operacje i podgląd na kartce", async () => {
    const { editor, plan, ensureDraft, view } = setup();
    const before = editor.getHTML();
    expect(within(bar()).getByRole("button", { name: "Przygotuj zmiany" })).toBeDisabled();
    await order();

    expect(plan).toHaveBeenCalledTimes(1);
    const [stage, body] = plan.mock.calls[0];
    expect(stage).toBe(5);
    expect(body.command).toBe("Skróć CV, zostaw wszystko o Kafce");
    expect(body.preset).toBeUndefined();
    expect(body.lines[4]).toEqual({ id: 4, kind: "bullet", text: "Rozwój usług w **Java 17**.", section: "experience", role: 0 });
    // Klauzula zgody nie jest wierszem; nie ma HTML-a ani pozycji.
    expect(JSON.stringify(body)).not.toMatch(/Wyrażam zgodę|<p>|"from"/);

    expect(panel()).toHaveTextContent("4 zmiany · odznacz te, których nie chcesz");
    expect(operation(0)).toHaveTextContent("Usuń punkt");
    expect(operation(0)).toHaveTextContent("Senior Developer 2021 – 2024");
    expect(operation(0)).toHaveTextContent("Asystent: Ogólnik.");
    expect(operation(1)).toHaveTextContent("Przeredaguj punkt");
    expect(operation(1).querySelector("strong")).toHaveTextContent("Java 17");
    expect(operation(3)).toHaveTextContent("Usuń sekcję");
    expect(operation(3)).toHaveTextContent("ZAINTERESOWANIA");
    // Kartka czeka na decyzję: nic się nie zmieniło, szkic nie powstał.
    expect(view.container.firstElementChild).toHaveAttribute("data-locked", "true");
    expect(editor.getHTML()).toBe(before);
    expect(ensureDraft).not.toHaveBeenCalled();
    // Podgląd: usuwany punkt, zmieniany punkt z nową treścią, sekcja (nagłówek i akapit).
    expect(editor.view.dom.querySelectorAll(".cv-plan-remove")).toHaveLength(3);
    expect(editor.view.dom.querySelector(".cv-plan-new")).toHaveTextContent("Rozwijała usługi w Java 17.");
  });

  it("operacja, po której znika wymaganie klienta, czeka na świadome zaznaczenie", async () => {
    const { editor } = setup();
    await order();
    const risky = within(operation(2)).getByRole("checkbox");
    expect(risky).not.toBeChecked();
    expect(operation(2)).toHaveTextContent("Po tej zmianie z CV znika wymaganie klienta: Kafka.");
    expect(screen.getByRole("button", { name: "Zastosuj zaznaczone (3)" })).toBeEnabled();

    fireEvent.click(risky);
    expect(screen.getByRole("button", { name: "Zastosuj zaznaczone (4)" })).toBeEnabled();
    expect(editor.view.dom.querySelectorAll(".cv-plan-remove")).toHaveLength(4);
    for (const id of [0, 1, 2, 3]) fireEvent.click(within(operation(id)).getByRole("checkbox"));
    expect(screen.getByRole("button", { name: "Zastosuj zaznaczone (0)" })).toBeDisabled();
    expect(editor.view.dom.querySelector("[class*='cv-plan-']")).toBeNull();
  });

  it("„Zastosuj zaznaczone” to jedna cofalna zmiana; szkic powstaje dopiero wtedy", async () => {
    const { editor, ensureDraft, view } = setup();
    const before = editor.getHTML();
    await order();
    fireEvent.click(screen.getByRole("button", { name: "Zastosuj zaznaczone (3)" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Plan zmian" })).toBeNull());

    expect(ensureDraft).toHaveBeenCalledTimes(1);
    const html = editor.getHTML();
    expect(html).toContain("<li><p>Rozwijała usługi w <strong>Java 17</strong>.</p></li>");
    expect(html).toContain("Kafka"); // niezaznaczona operacja została w spokoju
    expect(html).not.toContain("spotkaniach zespołu");
    expect(html).not.toContain("ZAINTERESOWANIA");
    expect(html).toContain(CLAUSE);
    expect(toast.showSuccess).toHaveBeenCalledWith("Zastosowano 3 zmiany. Wszystko cofniesz jednym „Cofnij”.");
    expect(view.container.firstElementChild).toHaveAttribute("data-locked", "false");
    expect(editor.view.dom.querySelector("[class*='cv-plan-']")).toBeNull();

    act(() => {
      editor.commands.undo();
    });
    expect(editor.getHTML()).toBe(before);
  });

  it("„Odrzuć plan” niczego nie zmienia i nie zakłada szkicu", async () => {
    const { editor, ensureDraft } = setup();
    const before = editor.getHTML();
    await order();
    fireEvent.click(screen.getByRole("button", { name: "Odrzuć plan" }));
    expect(screen.queryByRole("region", { name: "Plan zmian" })).toBeNull();
    expect(editor.getHTML()).toBe(before);
    expect(editor.view.dom.querySelector("[class*='cv-plan-']")).toBeNull();
    expect(ensureDraft).not.toHaveBeenCalled();
  });

  it("gotowe polecenie idzie jako nazwa — treść trzyma serwer", async () => {
    const { plan } = setup();
    fireEvent.click(within(bar()).getByRole("button", { name: "Ujednolić formę zdań" }));
    await screen.findByRole("button", { name: /Zastosuj zaznaczone/ });
    const body = plan.mock.calls[0][1];
    expect(body.preset).toBe("unify_sentences");
    expect(body.command).toBeUndefined();
  });

  it("brak zmian i niedostępny asystent to zdanie w panelu, nie pusty plan", async () => {
    const plan = vi
      .fn<CvEditorCommandApi["plan"]>()
      .mockResolvedValueOnce(reply({ status: "empty", operations: [], message: "Asystent nie znalazł zmian." }))
      .mockRejectedValueOnce(new Error("sieć"));
    const { editor } = setup({ api: { plan } });
    fireEvent.change(field(), { target: { value: "Zrób coś dziwnego" } });
    fireEvent.click(within(bar()).getByRole("button", { name: "Przygotuj zmiany" }));
    expect(await within(panel()).findByText("Asystent nie znalazł zmian.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zastosuj/ })).toBeNull();
    expect(editor.view.dom.querySelector("[class*='cv-plan-']")).toBeNull();

    fireEvent.click(within(bar()).getByRole("button", { name: "Przygotuj zmiany" }));
    await waitFor(() => expect(toast.showError).toHaveBeenCalledTimes(1));
    expect(within(panel()).getByRole("status")).toHaveTextContent("Nie udało się przygotować planu zmian");
    fireEvent.click(within(panel()).getByRole("button", { name: "Zamknij" }));
    expect(screen.queryByRole("region", { name: "Plan zmian" })).toBeNull();
  });

  it("kontrola serwera odrzuciła część propozycji — panel mówi ile", async () => {
    const plan = vi.fn<CvEditorCommandApi["plan"]>(async () =>
      reply({ dropped: [{ type: "replace", reason: "new_fact", problem: "AWS" }, { type: "remove", reason: "not_editable", problem: null }] }),
    );
    setup({ api: { plan } });
    await order();
    expect(panel()).toHaveTextContent("Odrzuciła 2 propozycje asystenta");
    expect(panel()).toHaveTextContent(/krótsza o około \d+%/);
  });

  it("plan dla treści, która się zmieniła, nie jest nakładany", async () => {
    const { editor, ensureDraft } = setup();
    await order();
    act(() => {
      editor.commands.insertContentAt(cvLines(editor.state.doc)[4].innerFrom, "Aktywny ");
    });
    const changed = editor.getHTML();
    fireEvent.click(screen.getByRole("button", { name: /Zastosuj zaznaczone/ }));
    expect(await within(panel()).findByText(/CV zmieniło się od przygotowania planu/)).toBeInTheDocument();
    expect(editor.getHTML()).toBe(changed);
    expect(ensureDraft).not.toHaveBeenCalled();
  });

  it("nieudane założenie szkicu zostawia plan do ponowienia", async () => {
    const ensureDraft = vi.fn(async () => false);
    const { editor } = setup({ ensureDraft });
    const before = editor.getHTML();
    await order();
    fireEvent.click(screen.getByRole("button", { name: "Zastosuj zaznaczone (3)" }));
    await waitFor(() => expect(ensureDraft).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("button", { name: "Zastosuj zaznaczone (3)" })).toBeEnabled();
    expect(editor.getHTML()).toBe(before);
  });

  it("edytor wyniku generatora i podgląd Word nie mają polecenia", () => {
    const { plan } = setup({ noStage: true });
    expect(field()).toBeDisabled();
    fireEvent.click(within(bar()).getByRole("button", { name: "Skróć do 2 stron" }));
    expect(plan).not.toHaveBeenCalled();
  });

  it("Escape w pasku zamyka pasek i nie wychodzi poza niego", () => {
    setup();
    const outside = vi.fn();
    document.addEventListener("keydown", outside);
    try {
      fireEvent.keyDown(field(), { key: "Escape" });
    } finally {
      document.removeEventListener("keydown", outside);
    }
    expect(screen.queryByRole("form", { name: "Polecenie dla całego CV" })).toBeNull();
    expect(outside).not.toHaveBeenCalled();
  });
});

describe("tytuł operacji", () => {
  it("składa go kod z rodzaju operacji i wierszy", () => {
    const lines = cvLines(openEditor().state.doc);
    expect(operationTitle(op(0, "remove", [5, 6]), lines)).toBe("Usuń 2 punkty");
    expect(operationTitle(op(0, "remove", [8]), lines)).toBe("Usuń akapit");
    expect(operationTitle(op(0, "merge", [4, 5, 6], { text: "x" }), lines)).toBe("Połącz 3 punkty w jeden");
    expect(operationTitle(op(0, "reorder", [5, 4, 6]), lines)).toBe("Zmień kolejność punktów");
    expect(operationTitle(op(0, "remove_role", [2, 3, 4, 5, 6]), lines)).toBe("Usuń stanowisko");
  });
});
