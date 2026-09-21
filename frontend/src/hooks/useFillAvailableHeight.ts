"use client";

import { useCallback, useEffect, useLayoutEffect, useState } from "react";

const useIsomorphicLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

function px(value: string): number {
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let node = el.parentElement; node; node = node.parentElement) {
    const overflowY = getComputedStyle(node).overflowY;
    if (overflowY === "auto" || overflowY === "scroll") return node;
  }
  return null;
}

/**
 * Wysokość, przy której element kończy się dokładnie na dolnej krawędzi
 * przewijanego obszaru (minus dolne odstępy przodków). Liczona z POMIARU, nie
 * ze stałej: nad tabelą rekrutacji stoją elementy o zmiennej wysokości (baner
 * „prowadzona w Trafficie", zawijające się chipy), więc `calc(100vh - N)`
 * zostawiało pusty pas na dole albo drugi pasek przewijania.
 *
 * Pozycja jest liczona w układzie TREŚCI (z `scrollTop`), więc przewinięcie
 * strony nie zmienia wyniku. `null` = jeszcze nie zmierzono (SSR, pierwszy
 * render) — wołający zostawia wtedy wysokość z CSS.
 */
export function useFillAvailableHeight(minHeight: number): {
  ref: (node: HTMLElement | null) => void;
  height: number | null;
} {
  const [node, setNode] = useState<HTMLElement | null>(null);
  const [height, setHeight] = useState<number | null>(null);
  const ref = useCallback((next: HTMLElement | null) => setNode(next), []);

  useIsomorphicLayoutEffect(() => {
    if (!node) return;
    const scroller = scrollParent(node);

    const measure = () => {
      const rect = node.getBoundingClientRect();
      let viewportHeight: number;
      let topInContent: number;
      if (scroller) {
        const scrollerRect = scroller.getBoundingClientRect();
        viewportHeight = scroller.clientHeight;
        topInContent = rect.top - scrollerRect.top - scroller.clientTop + scroller.scrollTop;
      } else {
        viewportHeight = window.innerHeight;
        topInContent = rect.top + window.scrollY;
      }
      let bottomGap = 0;
      for (
        let el: HTMLElement | null = node.parentElement;
        el && el !== document.documentElement;
        el = el.parentElement
      ) {
        const style = getComputedStyle(el);
        bottomGap += px(style.paddingBottom);
        if (style.borderBottomStyle !== "none" && style.borderBottomStyle !== "") {
          bottomGap += px(style.borderBottomWidth);
        }
        if (el === scroller) break;
      }
      const next = Math.max(minHeight, Math.floor(viewportHeight - topInContent - bottomGap));
      setHeight((prev) => (prev === next ? prev : next));
    };

    measure();
    window.addEventListener("resize", measure);
    if (typeof ResizeObserver === "undefined") {
      return () => window.removeEventListener("resize", measure);
    }
    // Wszystko, co stoi NAD elementem (baner, zawijające się chipy, nagłówek
    // strony), leży w którymś z przodków — zmiana jego wysokości zmienia
    // wysokość przodka. Przewijany obszar reaguje na okno i pasek górny.
    const observer = new ResizeObserver(measure);
    for (
      let el: HTMLElement | null = node.parentElement;
      el && el !== document.documentElement;
      el = el.parentElement
    ) {
      observer.observe(el);
      if (el === scroller) break;
    }
    return () => {
      window.removeEventListener("resize", measure);
      observer.disconnect();
    };
  }, [node, minHeight]);

  return { ref, height };
}
