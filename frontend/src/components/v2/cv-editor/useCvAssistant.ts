"use client";

/**
 * Asystent w kolumnie edytora CV (Edytor CV 3, PR 4, decyzje D1–D6 Artura).
 *
 * Rekruter pisze jak do czatu („skróć logistykę do 3 punktów, pogrub Kafkę”)
 * albo wybiera podpowiedź. Serwer zwraca plan sprawdzony operacja po operacji
 * (`cv_command_ai`), a edytor nakłada go OD RAZU — jedną transakcją, jednym
 * „Cofnij” na wiadomość — i podświetla zmienioną treść na zielono.
 *
 * Pytamy tylko, gdy musimy (zasada 6): operacja z faktem spoza CV i źródeł
 * (`ask: "source"`) czeka na „Tak, dopisz”, które najpierw zapisuje fakt jako
 * notatkę pary, a usunięcie jedynego miejsca z wymaganiem klienta
 * (`ask: "loses"`) — na „Tak, zmień”. Wiersze takiej operacji odnajdujemy przy
 * odpowiedzi po treści: wcześniejsze zmiany z tej samej wiadomości przesuwają
 * numery wierszy.
 *
 * Do odpowiedzi serwera kartka jest tylko do odczytu (`locked`): plan odnosi
 * się do wierszy z chwili wysłania. Szkic na zatwierdzonej wersji powstaje
 * dopiero przy pierwszej nakładanej zmianie.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Editor } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";

import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CV_COMMAND_FOCUS_MAX,
  CV_COMMAND_HISTORY_MAX,
  CV_COMMAND_HISTORY_TEXT_MAX,
  networkCommandApi,
  type CvCommandPreset,
  type CvEditorCommandApi,
  type CvPlanOperation,
} from "@/lib/api/cvEditorCommand";
import {
  CV_COMMAND_MAX,
  applyChanges,
  canApply,
  commandBlocker,
  commandLines,
  cvLines,
  setAssistantHighlight,
  type CvLine,
} from "@/lib/cv-editor-command";

export interface AssistantQuestion {
  kind: "source" | "loses";
  /** O co pytamy: fakt („Terraform”) albo wymagania, które znikną. */
  subject: string;
  operation: CvPlanOperation;
  /** Wiersze CV z chwili wysłania wiadomości. */
  lines: readonly CvLine[];
  state: "open" | "busy" | "yes" | "no";
}

export interface AssistantMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
  /** Wiadomość rekrutera: zaznaczony fragment, którego dotyczyła. */
  selection?: string | null;
  /** Odpowiedź: co zmieniono (po jednym zdaniu na operację). */
  items?: string[];
  /** Słowa nowej treści do przeczytania (kontrola faktów ich nie ocenia). */
  words?: string[];
  question?: AssistantQuestion;
  /** „Cofnij”: dokument tuż po zmianie — cofnąć wolno, dopóki się nie zmienił. */
  undo?: { after: PMNode; state: "ready" | "done" };
  tone?: "info" | "error";
}

export interface CvAssistantController {
  /** Asystent działa w tym edytorze (CV etapu, nie „Jak u klienta”, nie trwający zapis). */
  enabled: boolean;
  messages: readonly AssistantMessage[];
  /** Serwer liczy odpowiedź albo trwa odpowiedź na pytanie. */
  busy: boolean;
  /** Kartka tylko do odczytu: plan odnosi się do wierszy z chwili wysłania. */
  locked: boolean;
  send: (input: { command?: string; preset?: CvCommandPreset; label?: string }) => void;
  /** „Napisz od nowa: …” trafia do karty (nowa generacja), nie do planu zmian. */
  canRewrite: boolean;
  answer: (messageId: number, yes: boolean) => Promise<void>;
  undo: (messageId: number) => void;
}

interface Options {
  editor: Editor | null;
  /** Etap rekrutacji; `undefined` = edytor wyniku generatora (bez asystenta). */
  stageId: number | undefined;
  disabled: boolean;
  /** Zakłada szkic na zatwierdzonej wersji; `false` = nie udało się. */
  ensureDraft: () => Promise<boolean>;
  api?: CvEditorCommandApi;
  /** „Napisz od nowa” (PR 5): edytor zapisuje szkic i oddaje uwagę karcie. */
  onRewrite?: (instruction: string) => void;
}

const MSG_FAILED = "Nie udało się przygotować zmian. Spróbuj jeszcze raz.";
const MSG_CHANGED = "CV zmieniło się w międzyczasie — napisz jeszcze raz, co zmienić.";
const MSG_NOTHING = "Nie znalazłem zmian, które da się zrobić w tym CV.";
const MSG_LATE = "Odpowiedź przyszła, gdy CV się zapisywało — nic nie zmieniłem. Napisz jeszcze raz.";
const MSG_REWRITE =
  "Piszę CV od nowa — zapisuję i zamykam edytor. Nowa wersja pojawi się w karcie za ok. 40 s; Twoje ręczne poprawki zostaną.";
/** „napisz od nowa: krócej…”, „Napisz CV od nowa — więcej o Kafce”. */
const REWRITE_COMMAND = /^\s*napisz\s+(?:cv\s+)?od\s+nowa\b[\s:,.;–—-]*/i;

const DEFAULT_WHY: Record<CvPlanOperation["type"], string> = {
  remove: "Usunięte",
  replace: "Przeredagowane",
  merge: "Połączone punkty",
  reorder: "Nowa kolejność punktów",
  remove_role: "Usunięte stanowisko",
  remove_section: "Usunięta sekcja",
  add: "Dopisany punkt",
  bold: "Pogrubione",
  unbold: "Bez pogrubienia",
  considered_for: "Nowe stanowisko w „Rozważany na stanowisko”",
};

/** Odmiana po liczbie: 1 → `one`, 2–4 (poza 12–14) → `few`, reszta → `many`. */
function plural(count: number, one: string, few: string, many: string): string {
  const last = count % 10;
  const teen = count % 100 >= 12 && count % 100 <= 14;
  if (count === 1) return one;
  return last >= 2 && last <= 4 && !teen ? few : many;
}

function changesLabel(count: number): string {
  return `${count} ${plural(count, "zmiana", "zmiany", "zmian")}`;
}

function proposalsLabel(count: number): string {
  return plural(count, "propozycję", "propozycje", "propozycji");
}

function describe(operation: CvPlanOperation): string {
  if (operation.type === "bold" || operation.type === "unbold") {
    return `${DEFAULT_WHY[operation.type]}: ${(operation.terms ?? []).join(", ")}`;
  }
  return operation.why.trim() || DEFAULT_WHY[operation.type];
}

function sameLines(a: readonly CvLine[], b: readonly CvLine[]): boolean {
  return a.length === b.length && a.every((line, index) => line.kind === b[index].kind && line.text === b[index].text);
}

function twins(line: CvLine, other: CvLine): boolean {
  return line.kind === other.kind && line.text === other.text && line.section === other.section;
}

/**
 * Wiersze operacji w bieżącym CV — po treści, bo numery mogły się przesunąć.
 * Ten sam tekst w kilku miejscach (np. „Code review.” w dwóch stanowiskach):
 * wiersz po kolejności wystąpienia; gdy liczba wystąpień się zmieniła — `null`,
 * bez zgadywania.
 */
function remap(operation: CvPlanOperation, before: readonly CvLine[], current: readonly CvLine[]): CvPlanOperation | null {
  const used = new Set<number>();
  const lines: number[] = [];
  for (const id of operation.lines) {
    const old = before[id];
    if (!old) return null;
    const was = before.filter((line) => twins(line, old));
    const now = current.filter((line) => twins(line, old));
    const match = now.length === was.length ? now[was.indexOf(old)] : undefined;
    if (!match || used.has(match.id)) return null;
    used.add(match.id);
    lines.push(match.id);
  }
  return { ...operation, lines };
}

export function useCvAssistant({
  editor,
  stageId,
  disabled,
  ensureDraft,
  api = networkCommandApi,
  onRewrite,
}: Options): CvAssistantController {
  const { showError } = useToast();
  const enabled = !!editor && stageId != null && !disabled;
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [pending, setPending] = useState(false);
  const [answering, setAnswering] = useState(false);
  const nextId = useRef(1);
  // Stan z chwili odpowiedzi serwera: zapis albo przekazanie mogły zablokować
  // edytor, gdy asystent liczył — wtedy zmiana nie wchodzi.
  const enabledNow = useRef(enabled);
  useEffect(() => {
    enabledNow.current = enabled;
  }, [enabled]);
  // Numer żądania: odpowiedź po zamknięciu edytora albo po nowym żądaniu jest ignorowana.
  const ticket = useRef(0);
  useEffect(
    () => () => {
      ticket.current += 1;
    },
    [],
  );
  useEffect(
    () => () => {
      if (editor && !editor.isDestroyed) setAssistantHighlight(editor, []);
    },
    [editor],
  );

  const push = useCallback((message: Omit<AssistantMessage, "id">) => {
    const id = nextId.current++;
    setMessages((current) => [...current, { ...message, id }]);
    return id;
  }, []);
  const update = useCallback((id: number, change: (message: AssistantMessage) => AssistantMessage) => {
    setMessages((current) => current.map((message) => (message.id === id ? change(message) : message)));
  }, []);

  /** Operacje na wierszach bieżącego CV — `null`, gdy któregoś wiersza już nie ma. */
  const prepare = (lines: readonly CvLine[], operations: readonly CvPlanOperation[]) => {
    if (!editor || editor.isDestroyed) return null;
    const current = cvLines(editor.state.doc);
    // CV bez zmian od wysłania: numery wierszy są dobre (dwa identyczne punkty
    // nie zamienią się miejscami przy dopasowaniu po treści).
    if (sameLines(lines, current)) return { current, operations: [...operations] };
    const remapped = operations.map((operation) =>
      operation.type === "bold" || operation.type === "unbold" ? operation : remap(operation, lines, current),
    );
    if (remapped.some((operation) => operation == null)) return null;
    return { current, operations: remapped as CvPlanOperation[] };
  };

  /** Operacje dadzą się nałożyć na bieżące CV (wiersze są, kod je przyjmie). */
  const applicable = (lines: readonly CvLine[], operations: readonly CvPlanOperation[]): boolean => {
    if (!editor || editor.isDestroyed || operations.length === 0) return false;
    const check = prepare(lines, operations);
    return !!check && !!applyChanges(editor.state, check.current, check.operations);
  };

  /** Nakłada operacje jedną transakcją; zwraca dokument po zmianie albo `null`. */
  const applyNow = async (lines: readonly CvLine[], operations: readonly CvPlanOperation[]): Promise<PMNode | null> => {
    if (!editor || !applicable(lines, operations)) return null;
    // Szkic dopiero teraz: nowy szkic zdejmuje z CV stan „zatwierdzone”.
    if (!(await ensureDraft()) || editor.isDestroyed) return null;
    // Szkic wczytany z serwera ma tę samą treść, ale nowe węzły — liczymy od nowa.
    const ready = prepare(lines, operations);
    const result = ready ? applyChanges(editor.state, ready.current, ready.operations) : null;
    if (!result) return null;
    editor.view.dispatch(result.transaction);
    setAssistantHighlight(editor, result.changed);
    return editor.state.doc;
  };

  const history = (current: readonly AssistantMessage[]) =>
    current
      .filter((message) => message.text.trim())
      .slice(-CV_COMMAND_HISTORY_MAX)
      .map((message) => ({
        role: message.role,
        text: [message.text, ...(message.items ?? [])].join(" ").slice(0, CV_COMMAND_HISTORY_TEXT_MAX),
      }));

  const send: CvAssistantController["send"] = (input) => {
    if (!editor || stageId == null || !enabled || pending || answering) return;
    const command = (input.command ?? "").trim().slice(0, CV_COMMAND_MAX);
    if (!input.preset && command.length < 3) return;
    const snapshot = cvLines(editor.state.doc);
    const blocker = commandBlocker(snapshot);
    const { from, to, empty } = editor.state.selection;
    const focus = empty
      ? []
      : snapshot.filter((line) => line.to > from && line.from < to).map((line) => line.id).slice(0, CV_COMMAND_FOCUS_MAX);
    const quote = empty ? null : editor.state.doc.textBetween(from, to, " ").replace(/\s+/g, " ").trim().slice(0, 120) || null;
    const previous = history(messages);
    push({ role: "user", text: input.preset ? (input.label ?? command) : command, selection: quote });
    const rewrite = !input.preset && onRewrite ? REWRITE_COMMAND.exec(command) : null;
    if (rewrite && onRewrite) {
      push({ role: "assistant", text: MSG_REWRITE, tone: "info" });
      onRewrite(command.slice(rewrite[0].length));
      return;
    }
    if (blocker) {
      push({ role: "assistant", text: blocker, tone: "info" });
      return;
    }
    // Poprzednie podświetlenie gaśnie — nowa wiadomość, nowe zmiany.
    setAssistantHighlight(editor, []);
    ticket.current += 1;
    const mine = ticket.current;
    setPending(true);
    api
      .plan(stageId, {
        ...(input.preset ? { preset: input.preset } : { command }),
        lines: commandLines(snapshot),
        ...(previous.length > 0 ? { history: previous } : {}),
        ...(focus.length > 0 ? { focus } : {}),
      })
      .then(async (result) => {
        if (ticket.current !== mine) return;
        if (!enabledNow.current) {
          push({ role: "assistant", text: MSG_LATE, tone: "info" });
          return;
        }
        if (result.status !== "ok") {
          push({ role: "assistant", text: result.message ?? MSG_FAILED, tone: "info" });
          return;
        }
        // Operacja, której edytor nie umie nałożyć, nie przepada po cichu.
        const usable = result.operations.filter((operation) => canApply(operation, snapshot));
        const skipped = result.dropped.length + result.operations.length - usable.length;
        const now = usable.filter((operation) => !operation.ask);
        const asks = usable.filter((operation) => operation.ask);
        if (usable.length === 0) {
          push({ role: "assistant", text: result.message ?? MSG_NOTHING, tone: "info" });
          return;
        }
        if (now.length > 0) {
          const after = await applyNow(snapshot, now);
          if (ticket.current !== mine) return;
          if (!after) {
            push({ role: "assistant", text: MSG_CHANGED, tone: "error" });
            return;
          }
          const words = [...new Set(now.flatMap((operation) => operation.new_words))];
          push({
            role: "assistant",
            text:
              `Zrobione — ${changesLabel(now.length)}, na kartce na zielono.` +
              (skipped > 0 ? ` ${skipped} ${proposalsLabel(skipped)} odrzuciła kontrola (ruszały układ szablonu albo kwoty).` : ""),
            items: now.map(describe),
            ...(words.length > 0 ? { words } : {}),
            undo: { after, state: "ready" },
          });
        }
        for (const operation of asks) {
          const kind = operation.ask === "source" ? "source" : "loses";
          const subject = kind === "source" ? (operation.problem ?? "") : operation.loses.join(", ");
          push({
            role: "assistant",
            text:
              kind === "source"
                ? `Nie widzę „${subject}” w CV ani w notatkach. Kandydat mówił o tym na rozmowie?`
                : `Po tej zmianie w CV nie będzie „${subject}” — to wymaganie klienta. Zmienić mimo to?`,
            items: [describe(operation)],
            question: { kind, subject, operation, lines: snapshot, state: "open" },
          });
        }
      })
      .catch((error: unknown) => {
        if (ticket.current !== mine) return;
        const text = apiErrorMessage(error, MSG_FAILED);
        showError(text);
        push({ role: "assistant", text, tone: "error" });
      })
      .finally(() => {
        if (ticket.current === mine) setPending(false);
      });
  };

  const answer: CvAssistantController["answer"] = async (messageId, yes) => {
    const message = messages.find((item) => item.id === messageId);
    const question = message?.question;
    if (!question || question.state !== "open" || !enabled || pending || answering || !editor || stageId == null) return;
    if (!yes) {
      update(messageId, (current) => ({ ...current, question: { ...question, state: "no" } }));
      return;
    }
    // Wiersza już nie ma — bez notatki, bo powtórne „Tak” zapisałoby fakt drugi raz.
    if (!applicable(question.lines, [question.operation])) {
      push({ role: "assistant", text: MSG_CHANGED, tone: "error" });
      return;
    }
    setAnswering(true);
    update(messageId, (current) => ({ ...current, question: { ...question, state: "busy" } }));
    try {
      if (question.kind === "source") {
        // Najpierw źródło: notatka pary z autorem i datą, potem zmiana w CV.
        await api.confirmFact(stageId, { term: question.subject, text: question.operation.text ?? "" });
      }
      if (!enabledNow.current) {
        update(messageId, (current) => ({ ...current, question: { ...question, state: "open" } }));
        push({ role: "assistant", text: MSG_LATE, tone: "info" });
        return;
      }
      const after = await applyNow(question.lines, [question.operation]);
      if (!after) {
        update(messageId, (current) => ({ ...current, question: { ...question, state: "open" } }));
        push({ role: "assistant", text: MSG_CHANGED, tone: "error" });
        return;
      }
      update(messageId, (current) => ({
        ...current,
        question: { ...question, state: "yes" },
        undo: { after, state: "ready" },
      }));
    } catch (error) {
      update(messageId, (current) => ({ ...current, question: { ...question, state: "open" } }));
      showError(apiErrorMessage(error, "Nie udało się zapisać notatki. Spróbuj jeszcze raz."));
    } finally {
      setAnswering(false);
    }
  };

  const undo: CvAssistantController["undo"] = (messageId) => {
    const message = messages.find((item) => item.id === messageId);
    if (!editor || editor.isDestroyed || !message?.undo || message.undo.state !== "ready") return;
    // Tylko gdy po zmianie nic się nie stało — inaczej cofnęlibyśmy cudzą edycję.
    if (editor.state.doc !== message.undo.after) return;
    editor.commands.undo();
    setAssistantHighlight(editor, []);
    update(messageId, (current) => ({ ...current, undo: current.undo ? { ...current.undo, state: "done" } : undefined }));
  };

  return {
    enabled,
    canRewrite: enabled && onRewrite != null,
    messages,
    busy: pending || answering,
    locked: pending,
    send,
    answer,
    undo,
  };
}
