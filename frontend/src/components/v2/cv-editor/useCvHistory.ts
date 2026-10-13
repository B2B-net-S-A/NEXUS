"use client";

/**
 * Sterowanie panelem „Historia wersji” w edytorze CV (Edytor CV 2, PR 5).
 *
 * Dwie drogi, jeden obieg: treść starszej zatwierdzonej wersji albo treść
 * z poprawionego pliku Word → lista różnic z BIEŻĄCĄ treścią edytora → jedna
 * cofalna zmiana. Utrwala ją zwykły autozapis; serwer niczego tu nie zapisuje.
 *
 * Otwarcie panelu, porównanie i wgranie pliku niczego w CV nie zmieniają.
 * Szkic na zatwierdzonej wersji powstaje dopiero przy „Przywróć” / „Wstaw”.
 * Kartka zostaje do edycji — lista różnic liczy się od nowa po każdej zmianie
 * treści, więc zawsze mówi o tym, co jest w edytorze teraz.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Editor } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";

import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  networkHistoryApi,
  type CvEditorHistoryApi,
  type CvVersionSummary,
  type CvVersionsResponse,
} from "@/lib/api/cvEditorHistory";
import {
  contentDiffers,
  contentLines,
  diffLines,
  htmlToDoc,
  replaceContentStep,
  type CvDiffItem,
  type CvDiffLine,
} from "@/lib/cv-editor-diff";

export const cvEditorVersionsQueryKey = (stageId: number) => ["cv-editor-versions", stageId] as const;

/** Limit pliku Word — ten sam, co przy wgrywaniu CV. */
export const CV_WORD_IMPORT_MAX_BYTES = 10 * 1024 * 1024;

/** Skąd pochodzi porównywana treść. */
export type CvHistorySource = { kind: "version"; version: number } | { kind: "word"; filename: string };

export interface CvHistoryComparison {
  source: CvHistorySource;
  /** Różnice z bieżącą treścią edytora; `null` = za dużo wierszy, żeby porównać. */
  diff: readonly CvDiffItem[] | null;
}

export interface CvHistoryController {
  /** Czy historia jest w tym edytorze dostępna (CV etapu, nie podgląd Word, nie trwający zapis). */
  enabled: boolean;
  open: boolean;
  show: () => void;
  close: () => void;
  /** `ready` dopiero po udanym zapytaniu — awaria to nie „brak wersji”. */
  listState: "loading" | "error" | "ready";
  versions: readonly CvVersionSummary[];
  listError: string | null;
  reload: () => void;
  /** Co się wczytuje: numer wersji albo plik Word. */
  loading: number | "word" | null;
  /** Dlaczego porównania nie ma (błąd serwera, zły plik). */
  message: string | null;
  comparison: CvHistoryComparison | null;
  /** Trwa nakładanie treści (zakładanie szkicu, zmiana w edytorze). */
  busy: boolean;
  /** Wersja, której plik Word właśnie się pobiera. */
  downloading: number | null;
  compare: (version: number) => void;
  importWord: (file: File) => void;
  download: (version: number) => void;
  apply: () => Promise<void>;
  back: () => void;
}

interface Options {
  editor: Editor | null;
  /** Etap rekrutacji; `undefined` = edytor wyniku generatora (bez historii). */
  stageId: number | undefined;
  disabled: boolean;
  /** Zakłada szkic na zatwierdzonej wersji; `false` = nie udało się. */
  ensureDraft: () => Promise<boolean>;
  /** Pobiera plik Word zatwierdzonej wersji (nazwę pliku zna okno edytora). */
  downloadVersion: (version: number) => Promise<void>;
  /** Treść została nałożona — okno pokazuje kartkę (wąski ekran). */
  onApplied?: () => void;
  api?: CvEditorHistoryApi;
}

interface Incoming {
  source: CvHistorySource;
  doc: PMNode;
  lines: CvDiffLine[];
}

const NO_VERSIONS: readonly CvVersionSummary[] = [];
const MSG_NOT_DOCX = "To nie jest plik Word w formacie .docx. Zapisz plik jako .docx i wgraj go jeszcze raz.";
const MSG_TOO_BIG = "Ten plik jest za duży — limit to 10 MB.";
const MSG_NOT_APPLIED = "Nie udało się wstawić tej treści do edytora — CV zostało bez zmian.";

export function useCvHistory({
  editor,
  stageId,
  disabled,
  ensureDraft,
  downloadVersion,
  onApplied,
  api = networkHistoryApi,
}: Options): CvHistoryController {
  const { showError, showSuccess } = useToast();
  const enabled = !!editor && stageId != null && !disabled;
  const stageKey = stageId ?? 0;
  const [open, setOpen] = useState(false);
  const [incoming, setIncoming] = useState<Incoming | null>(null);
  const [loading, setLoading] = useState<number | "word" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState<number | null>(null);
  // Drugie kliknięcie „Przywróć” w tej samej chwili nie może nałożyć treści dwa razy.
  const applying = useRef(false);
  const enabledNow = useRef(enabled);
  enabledNow.current = enabled;
  // Numer żądania: odpowiedź po „Wróć do listy” albo po zamknięciu panelu jest ignorowana.
  const ticket = useRef(0);
  useEffect(
    () => () => {
      ticket.current += 1;
    },
    [],
  );

  const versionsQuery = useQuery<CvVersionsResponse>({
    queryKey: cvEditorVersionsQueryKey(stageKey),
    queryFn: () => api.versions(stageKey),
    enabled: stageId != null && open,
    // Każde otwarcie panelu pyta od nowa: zatwierdzenie w tle dopisuje wersję.
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  });

  const reset = useCallback(() => {
    ticket.current += 1;
    setIncoming(null);
    setLoading(null);
    setMessage(null);
  }, []);
  const close = useCallback(() => {
    reset();
    setOpen(false);
  }, [reset]);

  // Podgląd Word albo zapis w trakcie — porównanie nie ma już dokąd trafić.
  // Nie w trakcie nakładania: zakładanie szkicu to właśnie jego krok.
  useEffect(() => {
    if (!enabled && open && !busy) close();
  }, [enabled, open, busy, close]);

  // Różnice dotyczą treści z edytora TERAZ — po każdej zmianie liczą się od nowa.
  const comparing = incoming != null;
  const [docTick, setDocTick] = useState(0);
  useEffect(() => {
    if (!editor || !comparing) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onTransaction = ({ transaction }: { transaction: { docChanged: boolean } }) => {
      if (!transaction.docChanged) return;
      clearTimeout(timer);
      timer = setTimeout(() => setDocTick((tick) => tick + 1), 200);
    };
    editor.on("transaction", onTransaction);
    return () => {
      editor.off("transaction", onTransaction);
      clearTimeout(timer);
    };
  }, [editor, comparing]);
  const comparison = useMemo<CvHistoryComparison | null>(
    () =>
      incoming && editor && !editor.isDestroyed
        ? { source: incoming.source, diff: diffLines(contentLines(editor.state.doc), incoming.lines) }
        : null,
    // `docTick` = treść edytora się zmieniła.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editor, incoming, docTick],
  );

  const load = (
    what: number | "word",
    fetch: (stage: number) => Promise<{ html: string; source: CvHistorySource }>,
    failed: string,
    empty: string,
  ) => {
    if (!editor || stageId == null || !enabled || busy || loading != null) return;
    ticket.current += 1;
    const mine = ticket.current;
    setMessage(null);
    setLoading(what);
    fetch(stageId)
      .then(({ html, source }) => {
        if (ticket.current !== mine || editor.isDestroyed) return;
        const doc = htmlToDoc(editor.schema, html);
        const lines = contentLines(doc);
        // Pusta treść zastąpiłaby całe CV samą klauzulą — to nie jest wersja do przywrócenia.
        if (lines.length === 0) setMessage(empty);
        else setIncoming({ source, doc, lines });
      })
      .catch((error: unknown) => {
        if (ticket.current === mine) setMessage(apiErrorMessage(error, failed));
      })
      .finally(() => {
        if (ticket.current === mine) setLoading(null);
      });
  };

  const compare = (version: number) =>
    load(
      version,
      (stage) =>
        api.version(stage, version).then((result) => ({
          html: result.content_html,
          source: { kind: "version", version: result.version },
        })),
      "Nie udało się wczytać tej wersji CV. Spróbuj ponownie.",
      "Ta wersja nie ma treści, którą dałoby się porównać.",
    );

  const importWord = (file: File) => {
    if (!enabled || busy || loading != null) return;
    if (!/\.docx$/i.test(file.name)) return setMessage(MSG_NOT_DOCX);
    if (file.size > CV_WORD_IMPORT_MAX_BYTES) return setMessage(MSG_TOO_BIG);
    load(
      "word",
      (stage) =>
        api.importPreview(stage, file).then((result) => ({
          html: result.content_html,
          source: { kind: "word", filename: result.filename || file.name },
        })),
      "Nie udało się odczytać pliku Word. Spróbuj ponownie.",
      "W tym pliku nie ma treści CV, którą dałoby się porównać.",
    );
  };

  const download = (version: number) => {
    if (downloading != null) return;
    setDownloading(version);
    downloadVersion(version)
      .catch((error: unknown) => showError(apiErrorMessage(error, "Nie udało się pobrać pliku Word tej wersji.")))
      .finally(() => setDownloading(null));
  };

  const apply = async () => {
    if (!editor || !incoming || !enabled || applying.current) return;
    // Nic do zmiany = bez szkicu: nowy szkic zdejmuje z CV stan „zatwierdzone”.
    if (!contentDiffers(editor.state, incoming.doc)) return;
    const mine = ticket.current;
    applying.current = true;
    setBusy(true);
    try {
      if (!(await ensureDraft()) || editor.isDestroyed) return;
      // Panel zamknięty, „Zapisz” albo podgląd Word w trakcie zakładania szkicu.
      if (ticket.current !== mine || !enabledNow.current) return;
      if (!contentDiffers(editor.state, incoming.doc)) return;
      // `null` przy różnej treści = edytor nie przyjąłby zmiany albo jej cofnięcia.
      const transaction = replaceContentStep(editor.state, incoming.doc);
      if (!transaction) return showError(MSG_NOT_APPLIED);
      const before = editor.state.doc;
      editor.view.dispatch(transaction);
      // Edytor odrzuca transakcję po cichu (filtr wtyczki) — sukces ogłaszamy
      // dopiero, gdy treść naprawdę się zmieniła.
      if (editor.state.doc === before) return showError(MSG_NOT_APPLIED);
      showSuccess(
        incoming.source.kind === "version"
          ? `Przywrócono treść wersji ${incoming.source.version}. Cofniesz to jednym „Cofnij”.`
          : "Wstawiono treść z pliku Word. Cofniesz to jednym „Cofnij”.",
      );
      reset();
      onApplied?.();
      // Klawiatura wraca do tekstu (Ctrl+Z cofa od razu); nie na ekranie dotykowym
      // i nie na kartce tylko do odczytu — tam fokus nic by nie dał.
      if (editor.isEditable && !window.matchMedia?.("(pointer: coarse)").matches) {
        editor.view.dom.focus({ preventScroll: true });
      }
    } finally {
      applying.current = false;
      setBusy(false);
    }
  };

  const back = () => {
    if (!busy) reset();
  };

  return {
    enabled,
    open,
    show: () => {
      if (enabled) setOpen(true);
    },
    close,
    listState: versionsQuery.isSuccess ? "ready" : versionsQuery.isError ? "error" : "loading",
    versions: versionsQuery.data?.versions ?? NO_VERSIONS,
    listError: versionsQuery.isError
      ? apiErrorMessage(versionsQuery.error, "Nie udało się wczytać historii wersji.")
      : null,
    reload: () => void versionsQuery.refetch(),
    loading,
    message,
    comparison,
    busy,
    downloading,
    compare,
    importWord,
    download,
    apply,
    back,
  };
}
