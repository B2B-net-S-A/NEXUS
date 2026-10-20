"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
  type RefObject,
} from "react";

import type { CareerThemeId } from "../themes";
import { toggleInOrder, type ProcessStep, type SceneItem } from "./model";

/**
 * Stan sceny roli wspólny dla hero (scena), panelu parametrów (wynik „x z 5”
 * przy „Aplikuj”) i drobnych elementów w treści (błędy szablonu Glitch).
 * Wyłącznie pamięć komponentu: bez localStorage, bez wysyłki — odświeżenie
 * strony zaczyna od zera.
 */
export interface SceneContextValue {
  theme: CareerThemeId;
  items: SceneItem[];
  /** Mile widziane, które nie weszły do sceny (ozdoba). */
  extraNice: string[];
  /** Kroki procesu; puste, gdy rekruter ukrył proces. */
  steps: ProcessStep[];
  recruiterFirstName: string;
  login: string;
  handle: string;
  /** Zaznaczone pozycje w kolejności klikania. */
  order: number[];
  count: number;
  total: number;
  isOn: (index: number) => boolean;
  toggle: (index: number) => void;
  clear: () => void;
  /** Szablon Glitch: znalezione celowe błędy. */
  bugs: boolean[];
  fixBug: (index: number) => void;
  /** „./aplikuj” w terminalu podświetla przycisk przy wyniku. */
  applyHot: boolean;
  pingApply: () => void;
  /** `prefers-reduced-motion: reduce` — interakcja zostaje, animacje znikają. */
  still: boolean;
  /** Komputer z myszą (≥ 1024 px, precyzyjny wskaźnik) i bez ograniczenia ruchu. */
  pointerFx: boolean;
}

const SceneContext = createContext<SceneContextValue | null>(null);

export function useScene(): SceneContextValue {
  const ctx = useContext(SceneContext);
  if (!ctx) throw new Error("useScene poza CareerSceneProvider");
  return ctx;
}

export const GLITCH_BUG_COUNT = 3;

function subscribeQuery(query: string) {
  return (onChange: () => void) => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
    const mql = window.matchMedia(query);
    mql.addEventListener?.("change", onChange);
    return () => mql.removeEventListener?.("change", onChange);
  };
}

/** Zapytanie mediów; na serwerze i bez `matchMedia` (jsdom) — `false`. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useMemo(() => subscribeQuery(query), [query]);
  return useSyncExternalStore(
    subscribe,
    () =>
      typeof window !== "undefined" && typeof window.matchMedia === "function"
        ? window.matchMedia(query).matches
        : false,
    () => false,
  );
}

export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
export const FINE_POINTER_QUERY = "(min-width: 1024px) and (hover: hover) and (pointer: fine)";

export function CareerSceneProvider({
  theme,
  items,
  extraNice,
  steps,
  recruiterFirstName,
  login,
  handle,
  children,
}: {
  theme: CareerThemeId;
  items: SceneItem[];
  extraNice: string[];
  steps: ProcessStep[];
  recruiterFirstName: string;
  login: string;
  handle: string;
  children: ReactNode;
}) {
  const [order, setOrder] = useState<number[]>([]);
  const [bugs, setBugs] = useState<boolean[]>(() => Array(GLITCH_BUG_COUNT).fill(false));
  const [applyHot, setApplyHot] = useState(false);
  const still = useMediaQuery(REDUCED_MOTION_QUERY);
  const finePointer = useMediaQuery(FINE_POINTER_QUERY);

  const toggle = useCallback(
    (index: number) => setOrder((prev) => toggleInOrder(prev, index)),
    [],
  );
  const clear = useCallback(() => setOrder([]), []);
  const fixBug = useCallback(
    (index: number) => setBugs((prev) => prev.map((b, i) => (i === index ? true : b))),
    [],
  );
  const pingApply = useCallback(() => setApplyHot(true), []);

  // Podświetlenie przycisku gaśnie samo po kilku sekundach.
  useEffect(() => {
    if (!applyHot) return;
    const t = window.setTimeout(() => setApplyHot(false), 4000);
    return () => window.clearTimeout(t);
  }, [applyHot]);

  const value = useMemo<SceneContextValue>(
    () => ({
      theme,
      items,
      extraNice,
      steps,
      recruiterFirstName,
      login,
      handle,
      order,
      count: order.length,
      total: items.length,
      isOn: (index: number) => order.includes(index),
      toggle,
      clear,
      bugs,
      fixBug,
      applyHot,
      pingApply,
      still,
      pointerFx: finePointer && !still,
    }),
    [theme, items, extraNice, steps, recruiterFirstName, login, handle, order, toggle, clear, bugs, fixBug, applyHot, pingApply, still, finePointer],
  );

  return <SceneContext.Provider value={value}>{children}</SceneContext.Provider>;
}

/**
 * Efekt kursora bez przerysowania Reacta: pozycja wskaźnika w px względem
 * elementu trafia do zmiennych `--kr-px`/`--kr-py`, a `data-kr-pointer` mówi
 * CSS-owi, że kursor jest nad sceną. Wyłączony na dotyku i przy ograniczeniu ruchu.
 */
export function usePointerVars(ref: RefObject<HTMLElement | null>, enabled: boolean): void {
  useEffect(() => {
    const el = ref.current;
    if (!el || !enabled) return;
    let frame = 0;
    const onMove = (e: PointerEvent) => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        const r = el.getBoundingClientRect();
        el.style.setProperty("--kr-px", `${Math.round(e.clientX - r.left)}px`);
        el.style.setProperty("--kr-py", `${Math.round(e.clientY - r.top)}px`);
        el.style.setProperty("--kr-pfx", `${((e.clientX - r.left) / r.width - 0.5).toFixed(3)}`);
        el.style.setProperty("--kr-pfy", `${((e.clientY - r.top) / r.height - 0.5).toFixed(3)}`);
        el.setAttribute("data-kr-pointer", "");
      });
    };
    const onLeave = () => {
      if (frame) window.cancelAnimationFrame(frame);
      frame = 0;
      el.removeAttribute("data-kr-pointer");
      el.style.setProperty("--kr-pfx", "0");
      el.style.setProperty("--kr-pfy", "0");
    };
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    return () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
      onLeave();
    };
  }, [ref, enabled]);
}
