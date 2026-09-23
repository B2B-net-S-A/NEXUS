"use client";

import { useCallback, useEffect, useState, type RefObject } from "react";

/**
 * Publiczne CV w ramce (`/cv/{token}`, `/cv/i/{token}`) — czytelność na telefonie.
 *
 * Nowe dokumenty niosą to zapytanie w szablonie (`cv_html_renderer.py`,
 * `html_export.py`), ale HTML zatwierdzonego CV jest w bazie niemutowalny, więc
 * te same reguły doklejamy przy budowie `srcDoc`. Pomijamy je, gdy dokument już
 * je ma (znacznik z backendu albo nasz własny).
 */
export const MOBILE_CV_STYLE_MARKER = "data-nexus-cv-mobile";

const MOBILE_CV_CSS = [
  "@media (max-width: 640px) {",
  "body{padding:8px!important}",
  ".cv-body{grid-template-columns:1fr!important}",
  ".cv-sidebar{border-right:0!important;border-bottom:1px solid #e2e8f0!important;padding:20px 16px!important}",
  ".cv-main{padding:20px 16px!important}",
  ".cv-header{padding:24px 16px 20px!important}",
  ".cv-header-date{position:static!important;margin-top:8px!important}",
  ".cv-footer{padding:12px 16px!important;flex-wrap:wrap!important;gap:4px!important}",
  ".cv{padding:20px 16px!important}",
  ".edu{flex-direction:column!important;gap:0!important}",
  ".edu-dates{flex:none!important}",
  ".job-head{flex-wrap:wrap!important}",
  "img,table{max-width:100%!important}",
  "}",
].join("");

const MOBILE_CV_STYLE = `<style ${MOBILE_CV_STYLE_MARKER}>${MOBILE_CV_CSS}</style>`;

/** Czy dokument ma już reguły dla wąskiego ekranu. */
function hasMobileRules(html: string): boolean {
  return (
    html.includes(MOBILE_CV_STYLE_MARKER) ||
    /@media\s*\(max-width:\s*6[04]0px\)/.test(html)
  );
}

export function withMobileCvStyle(html: string | null | undefined): string {
  const source = html ?? "";
  if (!source || hasMobileRules(source)) return source;
  // Po arkuszu dokumentu (w <head>), żeby kolejność nie przegrywała z nim.
  const headEnd = source.search(/<\/head\s*>/i);
  if (headEnd >= 0) {
    return source.slice(0, headEnd) + MOBILE_CV_STYLE + source.slice(headEnd);
  }
  return MOBILE_CV_STYLE + source;
}

/**
 * Wysokość ramki = wysokość treści, liczona przy wczytaniu ORAZ przy każdej
 * zmianie szerokości (obrót telefonu, zmiana okna) — treść się wtedy przelewa.
 * Zwraca `onLoad` do podpięcia na `<iframe>` i bieżącą wysokość (null = nieznana).
 */
export function useFitFrameHeight(
  frameRef: RefObject<HTMLIFrameElement | null>,
): { height: number | null; fit: () => void } {
  const [height, setHeight] = useState<number | null>(null);
  const [loadTick, setLoadTick] = useState(0);

  const measure = useCallback(() => {
    const doc = frameRef.current?.contentDocument;
    const body = doc?.body;
    let next = 0;
    if (body && doc?.defaultView) {
      // Mierzymy <body>, nie documentElement.scrollHeight: ten nigdy nie jest
      // mniejszy niż bieżąca ramka, więc po poszerzeniu ekranu nie malałby.
      const style = doc.defaultView.getComputedStyle(body);
      next = Math.ceil(
        body.getBoundingClientRect().height +
          (parseFloat(style.marginTop) || 0) +
          (parseFloat(style.marginBottom) || 0),
      );
    }
    if (next <= 0) next = doc?.documentElement?.scrollHeight ?? 0;
    if (next > 0) setHeight(next);
  }, [frameRef]);

  const fit = useCallback(() => {
    measure();
    setLoadTick((tick) => tick + 1);
  }, [measure]);

  useEffect(() => {
    const frame = frameRef.current;
    const root = frame?.contentDocument?.body ?? null;
    let observer: ResizeObserver | null = null;
    if (root && typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(() => measure());
      observer.observe(root);
    }
    window.addEventListener("resize", measure);
    window.addEventListener("orientationchange", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("orientationchange", measure);
    };
  }, [frameRef, measure, loadTick]);

  return { height, fit };
}
