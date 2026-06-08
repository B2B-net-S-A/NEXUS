"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Repeat, Volume2, VolumeX } from "lucide-react";
import { useThemeStore, type KidsBuddy } from "@/store/theme";
import { CELEBRATE_EVENT, type CelebrateVariant } from "@/lib/celebrate";
import { playPetSound } from "@/lib/kidsSound";

const IDLE_BUBBLES = [
  "Świetna robota! 🌟",
  "Działasz super! 🚀",
  "Lecimy dalej! 🎯",
  "Jesteś the best! 💪",
  "Kawka? ☕",
];
const PET_BUBBLES = ["Miło! 💛", "Hej! 👋", "Mrr… 😺", "Łaskocze! 😆"];
const VARIANT_BUBBLE: Record<CelebrateVariant, string> = {
  hired: "Zatrudniony! 🎉",
  offer: "Oferta przyjęta! 💖",
  levelup: "Poziom zaliczony! 🏆",
  welcome: "Witaj w grze! 🎮",
  default: "Brawo! 🎉",
};

function pick<T>(arr: readonly T[]): T {
  // Avoid Math.random gotchas in some sandboxes — vary by clock.
  return arr[Math.floor(performance.now()) % arr.length];
}

/**
 * Floating game-world mascot — shown only in Kids mode. Idles with a gentle
 * float + periodic blink, tosses the occasional encouragement, waves on hover
 * and reacts (pop + bubble) when petted or when a `celebrate()` fires. A small
 * hover-revealed control cluster toggles sound and swaps the buddy character.
 */
export function KidsMascot() {
  const kidsMode = useThemeStore((s) => s.kidsMode);
  const kidsSound = useThemeStore((s) => s.kidsSound);
  const kidsBuddy = useThemeStore((s) => s.kidsBuddy);
  const toggleKidsSound = useThemeStore((s) => s.toggleKidsSound);
  const cycleKidsBuddy = useThemeStore((s) => s.cycleKidsBuddy);

  const [mounted, setMounted] = useState(false);
  const [popping, setPopping] = useState(false);
  const [bubble, setBubble] = useState<string | null>(null);
  const timersRef = useRef<number[]>([]);
  const streakRef = useRef(0);

  // Avoid hydration mismatch — kidsMode comes from localStorage on the client.
  useEffect(() => setMounted(true), []);

  const clearTimers = useCallback(() => {
    timersRef.current.forEach((t) => window.clearTimeout(t));
    timersRef.current = [];
  }, []);

  const react = useCallback(
    (msg: string, popMs = 700, bubbleMs = 3200) => {
      clearTimers();
      setPopping(true);
      setBubble(msg);
      timersRef.current.push(window.setTimeout(() => setPopping(false), popMs));
      timersRef.current.push(window.setTimeout(() => setBubble(null), bubbleMs));
    },
    [clearTimers]
  );

  // Celebrations → pop + themed bubble; every 3rd in a row → a "streak" cheer.
  useEffect(() => {
    if (!kidsMode) return;
    const onCelebrate = (e: Event) => {
      const detail = (e as CustomEvent<{ message?: string; variant?: CelebrateVariant }>).detail;
      streakRef.current += 1;
      const fallback = VARIANT_BUBBLE[detail?.variant ?? "default"] ?? VARIANT_BUBBLE.default;
      react(streakRef.current % 3 === 0 ? "Seria! 🔥" : detail?.message ?? fallback);
    };
    window.addEventListener(CELEBRATE_EVENT, onCelebrate);
    return () => window.removeEventListener(CELEBRATE_EVENT, onCelebrate);
  }, [kidsMode, react]);

  // Occasional unprompted encouragement (skipped while the tab is hidden).
  useEffect(() => {
    if (!kidsMode) return;
    const id = window.setInterval(() => {
      if (document.hidden) return;
      setBubble(pick(IDLE_BUBBLES));
      timersRef.current.push(window.setTimeout(() => setBubble(null), 4000));
    }, 210_000); // ~3.5 min
    return () => window.clearInterval(id);
  }, [kidsMode]);

  useEffect(() => clearTimers, [clearTimers]);

  const onPet = useCallback(() => {
    react(pick(PET_BUBBLES), 650, 1800);
    if (kidsSound) {
      try {
        playPetSound();
      } catch {
        /* audio optional */
      }
    }
  }, [kidsSound, react]);

  if (!mounted || !kidsMode) return null;

  return (
    <div className="fixed bottom-5 right-5 z-30 flex items-end gap-1.5 select-none group pointer-events-none">
      {/* Hover-revealed controls: sound + swap buddy */}
      <div className="flex flex-col gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity pointer-events-auto">
        <button
          type="button"
          onClick={toggleKidsSound}
          aria-label={kidsSound ? "Wyłącz dźwięki" : "Włącz dźwięki"}
          title={kidsSound ? "Dźwięki: wł." : "Dźwięki: wył."}
          className="h-7 w-7 flex items-center justify-center rounded-full border-2 border-primary/40 bg-card text-foreground shadow-md hover:scale-110 transition-transform"
        >
          {kidsSound ? <Volume2 className="h-3.5 w-3.5" /> : <VolumeX className="h-3.5 w-3.5" />}
        </button>
        <button
          type="button"
          onClick={cycleKidsBuddy}
          aria-label="Zmień maskotkę"
          title="Zmień maskotkę"
          className="h-7 w-7 flex items-center justify-center rounded-full border-2 border-primary/40 bg-card text-foreground shadow-md hover:scale-110 transition-transform"
        >
          <Repeat className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex items-end gap-2">
        {bubble && (
          <div className="kids-anim-pop mb-10 max-w-[180px] rounded-2xl border-2 border-primary/40 bg-card px-3 py-2 text-sm font-semibold text-foreground shadow-lg pointer-events-none">
            {bubble}
          </div>
        )}
        <button
          type="button"
          onClick={onPet}
          aria-label="Pogłaszcz maskotkę"
          className="kids-buddy pointer-events-auto outline-none"
        >
          <span className={popping ? "kids-anim-pop block" : "kids-anim-float block"}>
            <Buddy id={kidsBuddy} waving={popping} />
          </span>
        </button>
      </div>
    </div>
  );
}

function Buddy({ id, waving }: { id: KidsBuddy; waving: boolean }) {
  const wave = waving ? "kids-anim-wiggle" : undefined;
  const drop = "drop-shadow-[0_8px_14px_rgba(168,85,247,0.35)]";
  const common = { width: 76, height: 76, viewBox: "0 0 76 76", fill: "none", xmlns: "http://www.w3.org/2000/svg", role: "img" as const, className: drop };

  if (id === "rocket") {
    return (
      <svg {...common} aria-label="Maskotka: rakieta">
        <path d="M38 6c10 8 14 20 14 32H24c0-12 4-24 14-32Z" fill="#a855f7" stroke="#7e22ce" strokeWidth="2.5" />
        <circle cx="38" cy="30" r="8" fill="#0f172a" />
        <circle cx="35" cy="28" r="2" fill="#67e8f9" />
        <path d="M24 40c-6 2-9 6-9 6 4 1 7 0 7 0M52 40c6 2 9 6 9 6-4 1-7 0-7 0" fill="#ec4899" stroke="#7e22ce" strokeWidth="2" strokeLinejoin="round" />
        <path d="M30 52h16l-3 8c-2 4-8 4-10 0l-3-8Z" fill="#facc15" className={wave} />
      </svg>
    );
  }

  if (id === "cat") {
    return (
      <svg {...common} aria-label="Maskotka: kotek">
        <path d="M20 22 18 8l12 8M56 22 58 8 46 16" fill="#fb7185" stroke="#be123c" strokeWidth="2.5" strokeLinejoin="round" className={wave} />
        <circle cx="38" cy="40" r="24" fill="#fbcfe8" stroke="#be123c" strokeWidth="2.5" />
        <circle className="kids-eye" cx="30" cy="38" r="3.5" fill="#0f172a" />
        <circle className="kids-eye" cx="46" cy="38" r="3.5" fill="#0f172a" />
        <path d="M38 44l-3 3h6l-3-3Z" fill="#be123c" />
        <path d="M38 47c0 3-3 4-5 3M38 47c0 3 3 4 5 3" stroke="#be123c" strokeWidth="2" strokeLinecap="round" fill="none" />
        <path d="M14 38h10M14 44h10M52 38h10M52 44h10" stroke="#be123c" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    );
  }

  if (id === "star") {
    return (
      <svg {...common} aria-label="Maskotka: gwiazdka">
        <path d="M38 6l8.6 17.4L66 26.2 51 41l3.5 19.8L38 51.4 21.5 60.8 25 41 10 26.2l19.4-2.8L38 6Z" fill="#facc15" stroke="#d97706" strokeWidth="2.5" strokeLinejoin="round" className={wave} />
        <circle className="kids-eye" cx="32" cy="34" r="3" fill="#0f172a" />
        <circle className="kids-eye" cx="44" cy="34" r="3" fill="#0f172a" />
        <path d="M31 42q7 5 14 0" stroke="#0f172a" strokeWidth="2.5" strokeLinecap="round" fill="none" />
        <circle cx="26" cy="40" r="2.4" fill="#fb7185" opacity="0.8" />
        <circle cx="50" cy="40" r="2.4" fill="#fb7185" opacity="0.8" />
      </svg>
    );
  }

  // robot (default)
  return (
    <svg {...common} aria-label="Maskotka: robot">
      <defs>
        <linearGradient id="kidsBody" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#c084fc" />
          <stop offset="100%" stopColor="#ec4899" />
        </linearGradient>
      </defs>
      <line x1="38" y1="10" x2="38" y2="20" stroke="#a855f7" strokeWidth="3" strokeLinecap="round" />
      <circle cx="38" cy="8" r="4" fill="#facc15" className={wave} />
      <rect x="14" y="18" width="48" height="42" rx="16" fill="url(#kidsBody)" stroke="#7e22ce" strokeWidth="2.5" />
      <rect x="21" y="26" width="34" height="22" rx="10" fill="#0f172a" />
      <circle className="kids-eye" cx="31" cy="37" r="4" fill="#67e8f9" />
      <circle className="kids-eye" cx="45" cy="37" r="4" fill="#67e8f9" />
      <circle cx="32" cy="36" r="1.4" fill="#0f172a" />
      <circle cx="46" cy="36" r="1.4" fill="#0f172a" />
      <path d="M30 43 Q38 48 46 43" stroke="#34d399" strokeWidth="2.5" strokeLinecap="round" fill="none" />
      <circle cx="20" cy="44" r="3" fill="#fb7185" opacity="0.8" />
      <circle cx="56" cy="44" r="3" fill="#fb7185" opacity="0.8" />
      <rect x="24" y="59" width="10" height="7" rx="3.5" fill="#7e22ce" />
      <rect x="42" y="59" width="10" height="7" rx="3.5" fill="#7e22ce" />
    </svg>
  );
}
