"use client";

/**
 * Sterowanie „poleceniem dla całego CV” w edytorze (Edytor CV 2, PR 4).
 *
 * Polecenie → plan zmian z serwera → rekruter odznacza, czego nie chce →
 * „Zastosuj zaznaczone” jedną cofalną zmianą. Od zamówienia planu do decyzji
 * kartka jest tylko do odczytu (`locked`): plan odnosi się do wierszy z chwili
 * zamówienia, a podgląd pokazuje na kartce, co zniknie i co się zmieni.
 *
 * Szkic na zatwierdzonej wersji powstaje dopiero przy „Zastosuj” — samo
 * zamówienie i odrzucenie planu niczego w CV nie zmieniają.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Editor } from "@tiptap/core";

import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  networkCommandApi,
  type CvCommandPreset,
  type CvEditorCommandApi,
  type CvPlanOperation,
} from "@/lib/api/cvEditorCommand";
import {
  applyPlan,
  commandBlocker,
  commandLines,
  cvLines,
  planEffect,
  planMarks,
  setPlanMarks,
  type CvLine,
} from "@/lib/cv-editor-command";

export type CvCommandPhase = "idle" | "loading" | "plan" | "message";

export interface CvCommandInput {
  preset?: CvCommandPreset;
  command?: string;
}

export interface CvCommandController {
  /** Czy polecenie jest w tym edytorze dostępne (CV etapu, nie podgląd Word, nie trwający zapis). */
  enabled: boolean;
  phase: CvCommandPhase;
  /** Kartka tylko do odczytu: plan się liczy albo czeka na decyzję. */
  locked: boolean;
  operations: readonly CvPlanOperation[];
  /** Wiersze CV z chwili zamówienia planu. */
  lines: readonly CvLine[];
  selected: ReadonlySet<number>;
  /** Ile propozycji asystenta odrzuciła kontrola serwera. */
  dropped: number;
  /** Długość treści CV teraz i po zaznaczonych operacjach (znaki). */
  effect: { before: number; after: number };
  message: string | null;
  /** Trwa „Zastosuj” (zakładanie szkicu, nakładanie zmian). */
  busy: boolean;
  request: (input: CvCommandInput) => void;
  toggle: (id: number) => void;
  /** Pokazuje na kartce wiersze operacji. */
  show: (id: number) => void;
  apply: () => Promise<void>;
  discard: () => void;
}

interface Options {
  editor: Editor | null;
  /** Etap rekrutacji; `undefined` = edytor wyniku generatora (bez polecenia). */
  stageId: number | undefined;
  disabled: boolean;
  /** Zakłada szkic na zatwierdzonej wersji; `false` = nie udało się. */
  ensureDraft: () => Promise<boolean>;
  api?: CvEditorCommandApi;
}

const MSG_FAILED = "Nie udało się przygotować planu zmian. Spróbuj jeszcze raz.";
const MSG_CHANGED = "CV zmieniło się od przygotowania planu — przygotuj zmiany jeszcze raz.";
const NO_LINES: readonly CvLine[] = [];
const NO_OPERATIONS: readonly CvPlanOperation[] = [];

function changesLabel(count: number): string {
  const last = count % 10;
  const teen = count % 100 >= 12 && count % 100 <= 14;
  if (count === 1) return "1 zmianę";
  return `${count} ${last >= 2 && last <= 4 && !teen ? "zmiany" : "zmian"}`;
}

export function useCvCommandPlan({ editor, stageId, disabled, ensureDraft, api = networkCommandApi }: Options): CvCommandController {
  const { showError, showSuccess } = useToast();
  const enabled = !!editor && stageId != null && !disabled;
  const [phase, setPhase] = useState<CvCommandPhase>("idle");
  const [operations, setOperations] = useState<readonly CvPlanOperation[]>(NO_OPERATIONS);
  const [lines, setLines] = useState<readonly CvLine[]>(NO_LINES);
  const [selected, setSelected] = useState<ReadonlySet<number>>(() => new Set());
  const [dropped, setDropped] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Numer żądania: odpowiedź po „Odrzuć plan” albo po nowym żądaniu jest ignorowana.
  const ticket = useRef(0);
  useEffect(
    () => () => {
      ticket.current += 1;
    },
    [],
  );

  const reset = useCallback(() => {
    ticket.current += 1;
    setPhase("idle");
    setOperations(NO_OPERATIONS);
    setLines(NO_LINES);
    setSelected(new Set());
    setDropped(0);
    setMessage(null);
    setBusy(false);
  }, []);

  // Podgląd Word, zapis albo zamknięcie edytora w trakcie — plan nie ma już dokąd
  // trafić. Nie w trakcie „Zastosuj”: zakładanie szkicu to właśnie krok nakładania.
  useEffect(() => {
    if (!enabled && phase !== "idle" && !busy) reset();
  }, [enabled, phase, busy, reset]);

  // Podgląd na kartce idzie za zaznaczeniem operacji; bez planu kartka jest czysta.
  useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    setPlanMarks(editor, phase === "plan" ? planMarks(lines, operations, selected) : []);
  }, [editor, phase, lines, operations, selected]);
  useEffect(
    () => () => {
      if (editor && !editor.isDestroyed) setPlanMarks(editor, []);
    },
    [editor],
  );

  const fail = useCallback((text: string) => {
    setOperations(NO_OPERATIONS);
    setMessage(text);
    setPhase("message");
  }, []);

  const request = (input: CvCommandInput) => {
    if (!editor || stageId == null || !enabled || busy) return;
    const command = (input.command ?? "").trim();
    if (!input.preset && command.length < 3) return;
    const snapshot = cvLines(editor.state.doc);
    const blocker = commandBlocker(snapshot);
    if (blocker) return fail(blocker);
    ticket.current += 1;
    const mine = ticket.current;
    setLines(snapshot);
    setOperations(NO_OPERATIONS);
    setMessage(null);
    setPhase("loading");
    api
      .plan(stageId, { ...(input.preset ? { preset: input.preset } : { command }), lines: commandLines(snapshot) })
      .then((result) => {
        if (ticket.current !== mine) return;
        if (result.status !== "ok" || result.operations.length === 0) return fail(result.message ?? MSG_FAILED);
        setOperations(result.operations);
        setDropped(result.dropped.length);
        // Operacja, po której z CV znika wymaganie klienta, czeka na świadome zaznaczenie.
        setSelected(new Set(result.operations.filter((operation) => operation.loses.length === 0).map((operation) => operation.id)));
        setPhase("plan");
      })
      .catch((error: unknown) => {
        if (ticket.current !== mine) return;
        const text = apiErrorMessage(error, MSG_FAILED);
        showError(text);
        fail(text);
      });
  };

  const toggle = (id: number) => {
    if (phase !== "plan" || busy) return;
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  };

  const show = (id: number) => {
    const operation = operations.find((item) => item.id === id);
    const line = lines.find((item) => item.id === operation?.lines[0]);
    if (!editor || editor.isDestroyed || !line) return;
    const at = editor.view.domAtPos(Math.min(line.innerFrom, editor.state.doc.content.size)).node;
    const element = at instanceof Element ? at : at.parentElement;
    element?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  };

  const apply = async () => {
    const chosen = operations.filter((operation) => selected.has(operation.id));
    if (!editor || phase !== "plan" || busy || chosen.length === 0) return;
    if (!applyPlan(editor.state, lines, chosen)) return fail(MSG_CHANGED);
    const mine = ticket.current;
    setBusy(true);
    try {
      // Szkic dopiero teraz: nowy szkic zdejmuje z CV stan „zatwierdzone”.
      if (!(await ensureDraft()) || editor.isDestroyed) return;
      if (ticket.current !== mine) return;
      const transaction = applyPlan(editor.state, lines, chosen);
      if (!transaction) return fail(MSG_CHANGED);
      editor.view.dispatch(transaction);
      showSuccess(`Zastosowano ${changesLabel(chosen.length)}. Wszystko cofniesz jednym „Cofnij”.`);
      reset();
      // Klawiatura wraca do tekstu (Ctrl+Z cofa od razu); nie na ekranie dotykowym.
      if (!window.matchMedia?.("(pointer: coarse)").matches) editor.view.dom.focus({ preventScroll: true });
    } finally {
      setBusy(false);
    }
  };

  const discard = () => {
    if (busy) return;
    reset();
  };

  const effect = useMemo(() => planEffect(lines, operations, selected), [lines, operations, selected]);

  return {
    enabled,
    phase,
    locked: phase === "loading" || phase === "plan",
    operations,
    lines,
    selected,
    dropped,
    effect,
    message,
    busy,
    request,
    toggle,
    show,
    apply,
    discard,
  };
}
