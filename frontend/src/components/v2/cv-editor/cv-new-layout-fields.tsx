"use client";

/**
 * Pola formularzy nowego CV (22.11.2026): wartość czytają z dokumentu
 * edytora, a zmiana idzie transakcją Tiptapa (`lib/cv-new-layout-form.ts`).
 * Ctrl/⌘+Z w polu cofa w historii EDYTORA — jedna historia dla kartki
 * i formularza, inaczej przeglądarka cofałaby tylko tekst pola.
 */

import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import type { Editor } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";

import type { CvCommand } from "@/lib/cv-editor-blocks";
import { useTextareaAutogrow } from "@/lib/use-textarea-autogrow";
import { cn } from "@/lib/utils";

/** Dokument edytora; komponent rysuje się od nowa przy każdej zmianie treści. */
export function useEditorDoc(editor: Editor): { doc: PMNode; version: number } {
  const [state, setState] = useState(() => ({ doc: editor.state.doc, version: 0 }));
  useEffect(() => {
    const update = () =>
      setState((current) =>
        current.doc === editor.state.doc ? current : { doc: editor.state.doc, version: current.version + 1 },
      );
    update();
    editor.on("transaction", update);
    return () => {
      editor.off("transaction", update);
    };
  }, [editor]);
  return state;
}

/** Transakcja pola w edytorze — bez fokusu kartki (formularz zostaje aktywny). */
export function dispatchCv(editor: Editor, command: CvCommand): boolean {
  if (editor.isDestroyed) return false;
  const transaction = command(editor.state);
  if (!transaction) return false;
  editor.view.dispatch(transaction);
  return true;
}

/** Ctrl/⌘+Z, Ctrl/⌘+Shift+Z i Ctrl+Y w polu = historia edytora. */
export function editorHistoryKeys(editor: Editor) {
  return (event: KeyboardEvent<HTMLElement>) => {
    if (!(event.metaKey || event.ctrlKey) || event.altKey) return;
    const key = event.key.toLowerCase();
    const redo = (key === "z" && event.shiftKey) || (key === "y" && !event.shiftKey);
    if (key !== "z" && !redo) return;
    event.preventDefault();
    if (redo) editor.commands.redo();
    else editor.commands.undo();
  };
}

// Te same klasy co `components/ui/textarea.tsx` i `input.tsx`.
const FIELD =
  "w-full rounded-lg border border-border bg-card px-3 py-2 text-sm leading-5 text-foreground " +
  "placeholder:text-muted-foreground transition-colors duration-150 focus:outline-hidden focus:border-primary " +
  "disabled:cursor-not-allowed disabled:bg-[hsl(var(--border))]/30";

export interface DocTextareaProps {
  editor: Editor;
  value: string;
  onChange: (value: string) => void;
  label: ReactNode;
  disabled?: boolean;
  placeholder?: string;
  hint?: ReactNode;
  maxRows?: number;
  /** Etykieta tylko dla czytnika ekranu (np. punkt obowiązków). */
  srLabel?: boolean;
  trailing?: ReactNode;
  className?: string;
  onBlur?: () => void;
  /** `false` = pole spoza treści CV (dodatek strony 1) — zwykłe cofanie przeglądarki. */
  editorHistory?: boolean;
}

/** Pole tekstu CV rosnące z treścią (do `maxRows` linii). */
export function DocTextarea({
  editor,
  value,
  onChange,
  label,
  disabled,
  placeholder,
  hint,
  maxRows = 6,
  srLabel = false,
  trailing,
  className,
  onBlur,
  editorHistory = true,
}: DocTextareaProps) {
  const id = useId();
  const field = useRef<HTMLTextAreaElement | null>(null);
  const [wrapper, setWrapper] = useState<HTMLDivElement | null>(null);
  useTextareaAutogrow(field, wrapper, value, maxRows);
  return (
    <div className={cn("space-y-1", className)}>
      <label htmlFor={id} className={cn("block text-xs font-medium text-foreground", srLabel && "sr-only")}>
        {label}
      </label>
      <div ref={setWrapper} className="flex items-start gap-1.5">
        <textarea
          ref={field}
          id={id}
          rows={2}
          value={value}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={editorHistory ? editorHistoryKeys(editor) : undefined}
          onBlur={onBlur}
          className={cn(FIELD, "w-0 min-w-0 flex-1 resize-none")}
        />
        {trailing}
      </div>
      {hint ? <div className="text-xs text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

export interface DocInputProps {
  editor: Editor;
  value: string;
  onChange: (value: string) => void;
  label: string;
  disabled?: boolean;
  placeholder?: string;
  className?: string;
}

/** Pole jednej linii (daty, firma). */
export function DocInput({ editor, value, onChange, label, disabled, placeholder, className }: DocInputProps) {
  return (
    <input
      type="text"
      aria-label={label}
      value={value}
      disabled={disabled}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={editorHistoryKeys(editor)}
      className={cn(FIELD, "h-9 py-1.5", className)}
    />
  );
}
