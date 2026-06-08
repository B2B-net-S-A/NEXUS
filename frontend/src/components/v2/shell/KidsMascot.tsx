"use client";

import { useEffect, useRef, useState } from "react";
import { useThemeStore } from "@/store/theme";
import { CELEBRATE_EVENT } from "@/lib/celebrate";

const IDLE_BUBBLES = [
  "Świetna robota! 🌟",
  "Działasz super! 🚀",
  "Lecimy dalej! 🎯",
];

/**
 * Floating game-world mascot — a friendly robot buddy shown only in Kids mode.
 * It idles with a gentle float/wiggle and pops + shows a cheery speech bubble
 * when a `celebrate()` fires (e.g. a candidate reaches the "hired" stage). The
 * mascot is purely decorative (`pointer-events-none`) and never blocks the UI.
 */
export function KidsMascot() {
  const kidsMode = useThemeStore((s) => s.kidsMode);
  const [mounted, setMounted] = useState(false);
  const [popping, setPopping] = useState(false);
  const [bubble, setBubble] = useState<string | null>(null);
  const timersRef = useRef<number[]>([]);

  // Avoid hydration mismatch — kidsMode comes from localStorage on the client.
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!kidsMode) return;

    const clearTimers = () => {
      timersRef.current.forEach((t) => window.clearTimeout(t));
      timersRef.current = [];
    };

    const onCelebrate = (e: Event) => {
      const detail = (e as CustomEvent<{ message?: string }>).detail;
      const msg =
        detail?.message ?? IDLE_BUBBLES[Math.floor(performance.now()) % IDLE_BUBBLES.length];
      clearTimers();
      setPopping(true);
      setBubble(msg);
      timersRef.current.push(window.setTimeout(() => setPopping(false), 700));
      timersRef.current.push(window.setTimeout(() => setBubble(null), 3500));
    };

    window.addEventListener(CELEBRATE_EVENT, onCelebrate);
    return () => {
      window.removeEventListener(CELEBRATE_EVENT, onCelebrate);
      clearTimers();
    };
  }, [kidsMode]);

  if (!mounted || !kidsMode) return null;

  return (
    <div
      className="fixed bottom-5 right-5 z-30 flex items-end gap-2 pointer-events-none select-none"
      aria-hidden
    >
      {bubble && (
        <div className="kids-anim-pop mb-10 max-w-[180px] rounded-2xl border-2 border-primary/40 bg-card px-3 py-2 text-sm font-semibold text-foreground shadow-lg">
          {bubble}
        </div>
      )}
      <div className={popping ? "kids-anim-pop" : "kids-anim-float"}>
        <RobotBuddy waving={popping} />
      </div>
    </div>
  );
}

function RobotBuddy({ waving }: { waving: boolean }) {
  return (
    <svg
      width="76"
      height="76"
      viewBox="0 0 76 76"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Maskotka trybu gry"
      className="drop-shadow-[0_8px_14px_rgba(168,85,247,0.35)]"
    >
      <defs>
        <linearGradient id="kidsBody" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#c084fc" />
          <stop offset="100%" stopColor="#ec4899" />
        </linearGradient>
      </defs>

      {/* antenna */}
      <line x1="38" y1="10" x2="38" y2="20" stroke="#a855f7" strokeWidth="3" strokeLinecap="round" />
      <circle cx="38" cy="8" r="4" fill="#facc15" className={waving ? "kids-anim-wiggle" : undefined} />

      {/* head/body */}
      <rect x="14" y="18" width="48" height="42" rx="16" fill="url(#kidsBody)" stroke="#7e22ce" strokeWidth="2.5" />

      {/* screen face */}
      <rect x="21" y="26" width="34" height="22" rx="10" fill="#0f172a" />
      {/* eyes */}
      <circle cx="31" cy="37" r="4" fill="#67e8f9" />
      <circle cx="45" cy="37" r="4" fill="#67e8f9" />
      <circle cx="32" cy="36" r="1.4" fill="#0f172a" />
      <circle cx="46" cy="36" r="1.4" fill="#0f172a" />
      {/* smile */}
      <path d="M30 43 Q38 48 46 43" stroke="#34d399" strokeWidth="2.5" strokeLinecap="round" fill="none" />

      {/* cheeks */}
      <circle cx="20" cy="44" r="3" fill="#fb7185" opacity="0.8" />
      <circle cx="56" cy="44" r="3" fill="#fb7185" opacity="0.8" />

      {/* feet */}
      <rect x="24" y="59" width="10" height="7" rx="3.5" fill="#7e22ce" />
      <rect x="42" y="59" width="10" height="7" rx="3.5" fill="#7e22ce" />
    </svg>
  );
}
