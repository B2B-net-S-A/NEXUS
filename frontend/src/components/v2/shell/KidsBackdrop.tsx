"use client";

import { useEffect, useRef, useState } from "react";
import { useThemeStore } from "@/store/theme";
import { prefersReducedMotion } from "@/lib/prefers-reduced-motion";

interface FloatItem {
  emoji: string;
  left: string;
  size: number;
  durationS: number;
  delayS: number;
  depth: number; // parallax strength multiplier
}

// Stable, hand-tuned scatter (no Math.random — keeps SSR/CSR consistent).
const ITEMS: FloatItem[] = [
  { emoji: "🎈", left: "6%", size: 34, durationS: 26, delayS: 0, depth: 1.4 },
  { emoji: "⭐", left: "18%", size: 22, durationS: 34, delayS: 6, depth: 0.7 },
  { emoji: "🎈", left: "32%", size: 28, durationS: 30, delayS: 12, depth: 1.1 },
  { emoji: "🌟", left: "47%", size: 20, durationS: 38, delayS: 3, depth: 0.5 },
  { emoji: "🎈", left: "62%", size: 36, durationS: 24, delayS: 9, depth: 1.5 },
  { emoji: "✨", left: "74%", size: 22, durationS: 36, delayS: 1, depth: 0.6 },
  { emoji: "🎈", left: "85%", size: 30, durationS: 28, delayS: 15, depth: 1.2 },
  { emoji: "⭐", left: "93%", size: 18, durationS: 40, delayS: 7, depth: 0.4 },
];

/**
 * Decorative floating layer for Kids mode — balloons and stars drifting up the
 * viewport with a subtle cursor parallax. Sits behind page content
 * (`-z-10`, `pointer-events-none`) and is fully inert outside the game world.
 * Honors `prefers-reduced-motion` (no drift, no parallax).
 */
export function KidsBackdrop() {
  const kidsMode = useThemeStore((s) => s.kidsMode);
  const [mounted, setMounted] = useState(false);
  const layerRef = useRef<HTMLDivElement>(null);
  const frame = useRef<number | null>(null);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!kidsMode) return;
    if (typeof window === "undefined") return;
    if (prefersReducedMotion()) return;

    const onMove = (e: MouseEvent) => {
      if (frame.current != null) return;
      frame.current = window.requestAnimationFrame(() => {
        frame.current = null;
        const dx = (e.clientX / window.innerWidth - 0.5) * 24;
        const dy = (e.clientY / window.innerHeight - 0.5) * 16;
        const layer = layerRef.current;
        if (!layer) return;
        layer.querySelectorAll<HTMLElement>("[data-depth]").forEach((el) => {
          const d = Number(el.dataset.depth) || 1;
          // The independent `translate` property composes with the animated
          // `transform` (the upward drift) — no nesting needed.
          el.style.translate = `${dx * d}px ${dy * d}px`;
        });
      });
    };
    window.addEventListener("mousemove", onMove, { passive: true });
    return () => {
      window.removeEventListener("mousemove", onMove);
      if (frame.current != null) window.cancelAnimationFrame(frame.current);
    };
  }, [kidsMode]);

  if (!mounted || !kidsMode) return null;

  return (
    <div
      ref={layerRef}
      aria-hidden
      className="fixed inset-0 -z-10 overflow-hidden pointer-events-none"
    >
      {ITEMS.map((it, i) => (
        <span
          key={i}
          data-depth={it.depth}
          className="kids-float-item absolute bottom-[-12%] will-change-transform"
          style={
            {
              left: it.left,
              fontSize: `${it.size}px`,
              opacity: 0.5,
              "--dur": `${it.durationS}s`,
              "--delay": `${it.delayS}s`,
            } as React.CSSProperties
          }
        >
          {it.emoji}
        </span>
      ))}
    </div>
  );
}
