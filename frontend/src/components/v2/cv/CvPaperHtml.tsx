"use client";

/**
 * Treść CV w układzie kartki edytora (`.cv-paper` w `globals.css`: czcionka,
 * kolory i punkty szablonu) — zapas podglądu, gdy pliku Word nie da się
 * pokazać (brak zgody RODO, brak prawa do podglądu szkicu). Treść z edytora
 * przechodzi przez DOMPurify, ładowany dopiero przy pokazaniu.
 */

import { useEffect, useState } from "react";

import type { CvAlign } from "@/lib/cv-editor-align";

export interface CvPaperHtmlProps {
  html: string;
  language?: "pl" | "en";
  textAlign?: CvAlign;
}

export function CvPaperHtml({ html, language = "pl", textAlign = "justify" }: CvPaperHtmlProps) {
  const [safe, setSafe] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    void import("dompurify").then(({ default: DOMPurify }) => {
      if (!cancelled) setSafe(DOMPurify.sanitize(html, { FORBID_TAGS: ["style", "script"] }));
    });
    return () => {
      cancelled = true;
    };
  }, [html]);
  if (safe == null) return null;
  return (
    <div className="cv-paper px-4 pb-6" data-cv-lang={language} data-cv-align={textAlign}>
      <div
        className="ProseMirror"
        data-testid="cv-paper-html"
        // Treść po DOMPurify (bez skryptów i stylów).
        dangerouslySetInnerHTML={{ __html: safe }}
      />
    </div>
  );
}
