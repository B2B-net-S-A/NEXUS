"use client";

import { useEffect, useRef, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type RefObject } from "react";
import { isInputActive } from "@/components/KeyboardShortcuts";

/**
 * ↑/↓ przestawia wybrany wiersz tabeli z panelem szczegółów.
 *
 * Działa tylko, gdy fokus jest wewnątrz `containerRef` (tabela albo panel),
 * nie w polu tekstowym i bez otwartego okna czy menu — inaczej strzałki
 * przesuwałyby wybór za plecami formularza. Wiersze oznacza `data-row-key`;
 * po zmianie wyboru wiersz dostaje fokus i przewija się do widoku.
 */
export function useRowNavigation({
  keys,
  activeKey,
  onChange,
  containerRef,
  enabled = true,
}: {
  keys: string[];
  activeKey: string | null;
  onChange: (key: string) => void;
  containerRef: RefObject<HTMLElement | null>;
  enabled?: boolean;
}) {
  const state = useRef({ keys, activeKey, onChange });
  state.current = { keys, activeKey, onChange };

  useEffect(() => {
    if (!enabled) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      if (event.defaultPrevented || event.altKey || event.metaKey || event.ctrlKey) return;
      const container = containerRef.current;
      if (!container || !container.contains(document.activeElement)) return;
      if (isInputActive()) return;
      if (document.querySelector('[role="dialog"],[role="alertdialog"],[role="menu"],[role="listbox"]')) return;
      const { keys: list, activeKey: current, onChange: change } = state.current;
      if (list.length === 0) return;
      const index = current == null ? -1 : list.indexOf(current);
      const next = event.key === "ArrowDown" ? Math.min(list.length - 1, index + 1) : Math.max(0, index - 1);
      const key = list[next];
      if (key == null || key === current) return;
      event.preventDefault();
      change(key);
      requestAnimationFrame(() => {
        const row = container.querySelector<HTMLElement>(`[data-row-key="${CSS.escape(key)}"]`);
        if (row) {
          row.focus({ preventScroll: true });
          row.scrollIntoView({ block: "nearest" });
        }
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, containerRef]);
}

/**
 * Wiersz tabeli, który otwiera panel: klik i Enter/Spacja otwierają,
 * ale klik w link, przycisk, pole albo kwadracik wewnątrz wiersza — nie.
 */
export function rowActivationProps(key: string, onOpen: (key: string) => void) {
  const fromInteractive = (target: EventTarget | null, row: Element) => {
    const el = target instanceof Element ? target.closest("a,button,input,select,textarea,label,[role=checkbox],[data-row-stop]") : null;
    return el != null && el !== row && row.contains(el);
  };
  return {
    "data-row-key": key,
    tabIndex: 0,
    onClick: (event: ReactMouseEvent<HTMLElement>) => {
      if (fromInteractive(event.target, event.currentTarget)) return;
      if (typeof window !== "undefined" && window.getSelection()?.toString()) return;
      onOpen(key);
    },
    onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      if (event.target !== event.currentTarget) return;
      event.preventDefault();
      onOpen(key);
    },
  };
}
