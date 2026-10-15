"use client";

import { useLayoutEffect, type RefObject } from "react";

import { textareaFitHeight } from "@/lib/textarea-autogrow";
import { contentScrollHeight } from "@/lib/textarea-mirror";
import { useElementWidth } from "@/lib/use-element-width";

/**
 * Pole tekstowe rośnie z treścią do `maxRows` linii, dalej przewija się
 * w środku — ten sam rachunek co `MentionTextarea` (pomiar ukrytej kopii,
 * ramka z kroju). `wrapper` to opakowanie o szerokości pola: po zmianie
 * szerokości tekst zawija się inaczej i wysokość liczy się od nowa.
 *
 * Bez układu (jsdom, ukryty panel) wysokość zostaje z atrybutu `rows`.
 */
export function useTextareaAutogrow(
  field: RefObject<HTMLTextAreaElement | null>,
  wrapper: HTMLElement | null,
  value: string,
  maxRows: number,
): void {
  const width = useElementWidth(wrapper);
  useLayoutEffect(() => {
    const node = field.current;
    if (!node) return;
    const style = getComputedStyle(node);
    const fit = textareaFitHeight(
      {
        scrollHeight: contentScrollHeight(node, width),
        lineHeight: parseFloat(style.lineHeight),
        padding: parseFloat(style.paddingTop) + parseFloat(style.paddingBottom),
        border: (parseFloat(style.borderTopWidth) || 0) + (parseFloat(style.borderBottomWidth) || 0),
      },
      maxRows,
    );
    node.style.height = fit ? `${fit.height}px` : "";
    node.style.overflowY = fit ? (fit.scroll ? "auto" : "hidden") : "";
  }, [field, value, maxRows, width]);
}
