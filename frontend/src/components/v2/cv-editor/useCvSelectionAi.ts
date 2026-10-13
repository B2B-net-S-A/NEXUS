"use client";

/**
 * Sterowanie „AI na zaznaczeniu” w edytorze CV (Edytor CV 2, PR 3).
 *
 * Jeden stan dla dymka nad zaznaczeniem, menu „AI” w pasku i karty propozycji:
 * zaznaczenie → żądanie → propozycja → „Przyjmij / Jeszcze raz / Doprecyzuj /
 * Odrzuć”. Serwer zwraca PROPOZYCJĘ (albo powód, dla którego jej nie ma);
 * do CV trafia dopiero po „Przyjmij”, jedną cofalną zmianą.
 *
 * Szkic na zatwierdzonej wersji powstaje dopiero przy „Przyjmij” — samo
 * zamówienie propozycji niczego w CV nie zmienia.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { Editor } from "@tiptap/core";
import { useEditorState } from "@tiptap/react";

import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  networkAiApi,
  type CvAiAction,
  type CvAiRequest,
  type CvAiResponse,
  type CvEditorAiApi,
} from "@/lib/api/cvEditorAi";
import { acceptStep, clearPending, pendingTarget, selectionTarget, setPending } from "@/lib/cv-editor-ai";
import { clearIssueFocus, showIssueInCv } from "@/lib/cv-editor-issue-marks";

export type CvSelectionAiPhase = "idle" | "loading" | "proposal" | "message";

export interface CvSelectionAiController {
  /** Czy AI jest w tym edytorze dostępne (CV etapu, nie podgląd Word, nie trwający zapis). */
  enabled: boolean;
  /** Bieżące zaznaczenie: nadaje się, nie nadaje się z powodem, albo nie pokazuj AI wcale. */
  selection: { ok: boolean; reason: string | null; hidden: boolean };
  phase: CvSelectionAiPhase;
  action: CvAiAction | null;
  /** Zaznaczony tekst sprzed propozycji (`**pogrubienie**`). */
  before: string;
  response: CvAiResponse | null;
  /** Zdanie dla rekrutera, gdy propozycji nie ma. */
  message: string | null;
  canRetry: boolean;
  busy: boolean;
  start: (action: CvAiAction) => void;
  accept: () => void;
  again: () => void;
  refine: (instruction: string) => void;
  reject: () => void;
}

export interface UseCvSelectionAi {
  editor: Editor | null;
  /** Etap rekrutacji; bez niego (wynik generatora) AI na zaznaczeniu nie ma. */
  stageId?: number;
  /** Podgląd Word albo trwający zapis. */
  disabled: boolean;
  /** Zakłada szkic na zatwierdzonej wersji przed zmianą; `false` = nie udało się. */
  ensureDraft: () => Promise<boolean>;
  api?: CvEditorAiApi;
}

const MSG_CHANGED = "Zaznaczony tekst zmienił się, zanim propozycja była gotowa. Zaznacz go jeszcze raz.";
const MSG_FAILED = "Nie udało się pobrać propozycji AI. Spróbuj ponownie.";
/** Tyle ms wstawiony tekst zostaje wyróżniony po „Przyjmij”. */
const FOCUS_MS = 2600;
const PREVIOUS_MAX = 3;
const NO_SELECTION = { ok: false, reason: null, hidden: true } as const;

export function useCvSelectionAi({
  editor,
  stageId,
  disabled,
  ensureDraft,
  api = networkAiApi,
}: UseCvSelectionAi): CvSelectionAiController {
  const { showError } = useToast();
  const enabled = stageId != null && !disabled && editor != null;
  const selection =
    useEditorState({
      editor,
      selector: ({ editor: current }) => {
        if (!current || current.isDestroyed) return NO_SELECTION;
        const found = selectionTarget(current.state);
        return found.ok
          ? { ok: true, reason: null, hidden: false }
          : { ok: false, reason: found.reason, hidden: found.hidden === true };
      },
    }) ?? NO_SELECTION;

  const [phase, setPhase] = useState<CvSelectionAiPhase>("idle");
  const [action, setAction] = useState<CvAiAction | null>(null);
  const [before, setBefore] = useState("");
  const [response, setResponse] = useState<CvAiResponse | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [canRetry, setCanRetry] = useState(false);
  const [busy, setBusy] = useState(false);
  const request = useRef<CvAiRequest | null>(null);
  const shown = useRef<string[]>([]);
  // Numer żądania: odpowiedź po „Odrzuć” albo po nowym żądaniu jest ignorowana.
  const ticket = useRef(0);
  const focusTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(
    () => () => {
      ticket.current += 1;
      clearTimeout(focusTimer.current);
    },
    [],
  );

  const reset = useCallback(() => {
    ticket.current += 1;
    request.current = null;
    shown.current = [];
    if (editor) clearPending(editor);
    setPhase("idle");
    setAction(null);
    setResponse(null);
    setMessage(null);
    setBusy(false);
  }, [editor]);

  // Podgląd Word, zapis albo zamknięcie edytora w trakcie — propozycja nie ma już
  // dokąd trafić. Nie w trakcie „Przyjmij”: okno na chwilę wyłącza edycję, gdy
  // zakłada szkic na zatwierdzonej wersji, a to właśnie krok przyjmowania.
  useEffect(() => {
    if (!enabled && phase !== "idle" && !busy) reset();
  }, [enabled, phase, busy, reset]);

  const fail = (text: string, retry: boolean) => {
    setResponse(null);
    setMessage(text);
    setCanRetry(retry);
    setPhase("message");
  };

  const send = async (body: CvAiRequest) => {
    if (!editor || stageId == null) return;
    const mine = (ticket.current += 1);
    request.current = body;
    setAction(body.action);
    setResponse(null);
    setMessage(null);
    setPhase("loading");
    try {
      const result = await api.propose(stageId, body);
      if (ticket.current !== mine || editor.isDestroyed) return;
      if (!pendingTarget(editor.state)) return fail(MSG_CHANGED, false);
      if (result.status === "ok" && result.proposed_text) {
        shown.current = [...shown.current, result.proposed_text].slice(-PREVIOUS_MAX);
        setResponse(result);
        setPhase("proposal");
        return;
      }
      // „Jeszcze raz” ma sens po odmowie kontroli i po chwilowej awarii modelu.
      fail(result.message ?? MSG_FAILED, result.status === "rejected" || result.status === "unavailable");
    } catch (error) {
      if (ticket.current !== mine) return;
      fail(apiErrorMessage(error, MSG_FAILED), true);
    }
  };

  const start = (next: CvAiAction) => {
    if (!enabled || !editor) return;
    const found = selectionTarget(editor.state);
    if (!found.ok) {
      if (found.reason) showError(found.reason);
      return;
    }
    const { target } = found;
    setPending(editor, target);
    shown.current = [];
    setBefore(target.fragment);
    void send({
      action: next,
      fragment: target.fragment,
      block_text: target.blockText,
      block_kind: target.blockKind,
      section: target.section,
      ...(target.role ? { role: target.role } : {}),
    });
  };

  const again = () => {
    const last = request.current;
    if (!last || !editor || busy) return;
    if (!pendingTarget(editor.state)) return fail(MSG_CHANGED, false);
    const { instruction: _dropped, ...rest } = last;
    void send({ ...rest, ...(shown.current.length ? { previous: shown.current } : {}) });
  };

  const refine = (instruction: string) => {
    const last = request.current;
    const hint = instruction.trim();
    if (!last || !editor || !hint || busy) return;
    if (!pendingTarget(editor.state)) return fail(MSG_CHANGED, false);
    const current = response?.proposed_text;
    void send({ ...last, instruction: hint, ...(current ? { previous: [current] } : {}) });
  };

  const accept = async () => {
    const proposed = response?.proposed_text;
    if (!editor || !proposed || busy) return;
    if (!acceptStep(editor.state, proposed)) return fail(MSG_CHANGED, false);
    const mine = ticket.current;
    setBusy(true);
    try {
      // Szkic dopiero teraz: nowy szkic zdejmuje z CV stan „zatwierdzone”.
      if (!(await ensureDraft()) || editor.isDestroyed) return;
      // Propozycja mogła zostać zastąpiona, zanim szkic powstał — ta już nie obowiązuje.
      if (ticket.current !== mine) return;
      const step = acceptStep(editor.state, proposed);
      if (!step) return fail(MSG_CHANGED, false);
      editor.view.dispatch(step.transaction);
      showIssueInCv(editor, step.changed);
      clearTimeout(focusTimer.current);
      focusTimer.current = setTimeout(() => clearIssueFocus(editor), FOCUS_MS);
      // Klawiatura wraca do tekstu (Ctrl+Z cofa od razu); nie na ekranie dotykowym.
      if (!window.matchMedia?.("(pointer: coarse)").matches) editor.view.dom.focus({ preventScroll: true });
      reset();
    } finally {
      setBusy(false);
    }
  };

  return {
    enabled,
    selection,
    phase,
    action,
    before,
    response,
    message,
    canRetry,
    busy,
    start,
    accept: () => void accept(),
    again,
    refine,
    // W trakcie przyjmowania nie ma czego odrzucać — zmiana jest w drodze do CV.
    reject: () => {
      if (!busy) reset();
    },
  };
}
