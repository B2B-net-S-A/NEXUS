"use client";

import { useLayoutEffect, useState } from "react";

/**
 * Szerokość elementu w px, śledzona `ResizeObserver`-em. Przed pierwszym
 * pomiarem i w testach (jsdom nie liczy układu) zwraca 0 — układ zależny od
 * szerokości ma wtedy wybrać wariant najwęższy.
 *
 * Element podaje się ze stanu (`const [node, setNode] = useState(null)` +
 * `ref={setNode}`), bo bywa montowany dopiero po wczytaniu danych.
 *
 * Szerokość 0 po wcześniejszym pomiarze znaczy, że element (albo jego przodek)
 * został ukryty przez `display: none` — zwinięty panel, inna zakładka. To nie
 * jest zmiana układu, więc zostaje ostatnia zmierzona szerokość: inaczej
 * układ przeskakiwałby na najwęższy wariant i odmontowywał podgląd CV, który
 * po powrocie pobierałby plik drugi raz.
 */
export function useElementWidth(element: HTMLElement | null): number {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    if (!element) return;
    const update = () => {
      const next = element.clientWidth;
      if (next > 0) setWidth(next);
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return width;
}
