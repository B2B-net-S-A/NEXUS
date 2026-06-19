"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { MessageCircle, MessageCircleOff, Repeat, Volume2, VolumeX } from "lucide-react";
import { useThemeStore, type KidsBuddy } from "@/store/theme";
import { useAuthStore } from "@/store/auth";
import { CELEBRATE_EVENT, celebrateParty, type CelebrateVariant } from "@/lib/celebrate";
import { speak } from "@/lib/kidsSound";

// Motivational slogans the mascot shows (and, with sound on, speaks aloud).
// Recruiter / IT-staffing flavored — fun but not cringe.
const MOTIVATIONAL_SLOGANS = [
  "Każde CV to czyjaś szansa — działaj! 💪",
  "Dziś znajdziesz talent dnia! 💎",
  "Pełny pipeline, pełen sukces! 🚀",
  "Jeden telefon dzieli Cię od hire'a! 📞",
  "Nie ma złych kandydatów — są nietrafione role! 🎯",
  "Follow-up wygrywa mecze! ✉️",
  "Twój następny placement już czeka — idź po niego! 🏆",
  "Uśmiech słychać przez telefon — uśmiechnij się! 😊",
  "Małe kroki, wielkie hire'y! 🥇",
  "Każde 'nie' przybliża Cię do 'tak'! ✨",
  "Jesteś łowcą talentów — celuj wysoko! 🦅",
  "Dobry recruiter słucha 2× więcej niż mówi! 👂",
  "Zamknij dziś jeden etap więcej! ✅",
  "Twoja energia napędza cały zespół! ⚡",
  "Sourcing to skarb — kop głębiej! ⛏️",
  "Najlepszy moment na działanie to teraz! ⏰",
  "Relacje ponad transakcje — buduj mosty! 🌉",
  "Pamiętaj: i Ty jesteś czyimś talentem! 🌟",
  "Dziś rozbijesz target! 💥",
  "Spokojnie — masz to pod kontrolą! 🧘",
  "Wierzę w Ciebie — do dzieła! 🙌",
  "Świetnie Ci idzie, tak trzymaj! 🌈",
  "Zrób sobie przerwę, zasłużyłeś! 🍵",
  "Twój pipeline rośnie w siłę! 📈",
  "Bądź dziś czyimś dobrym dniem! ☀️",
  "Talent jest wszędzie — Ty go widzisz! 👀",
  "Końcówka dnia bliżej niż myślisz — finiszuj! 🏁",
  "Kawa w dłoni, sukces w głowie! ☕",
  "Wczorajszy sufit dzisiejszą podłogą! 🪜",
];

function greetingFor(firstName?: string): string {
  const h = new Date().getHours();
  const who = firstName ? `, ${firstName}` : "";
  if (h < 12) return `Dzień dobry${who}! Gotowy podbić dziś rynek? ☀️`;
  if (h < 18) return `Cześć${who}! Druga połowa dnia — dajesz radę! 💪`;
  return `Hej${who}! Końcówka dnia — finiszuj mocno! 🌆`;
}
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

// "Tip of the day" — practical recruiter pro-tips, distinct in tone from the
// motivational slogans. Picked deterministically by day so it's stable for 24h.
const RECRUITER_TIPS = [
  "Personalizuj pierwszą wiadomość — wzrasta odpowiedzialność 2-3×.",
  "Dzwoń rano (9-11) lub po 16 — wtedy kandydaci najczęściej odbierają.",
  "Zawsze ustal następny krok przed końcem rozmowy.",
  "Notatka po każdym kontakcie = zero zgubionych szczegółów.",
  "Pytaj o motywację do zmiany, nie tylko o stack technologiczny.",
  "Krótki feedback po odrzuceniu buduje markę na lata.",
  "Sourcing booleanowy: łącz synonimy ról przez OR, wymagania przez AND.",
  "Re-engage 'starych' kandydatów — często są już gotowi na zmianę.",
  "Mów o zespole i projekcie, nie tylko o widełkach.",
  "Follow-up po 2-3 dniach ciszy — większość hire'ów żyje w follow-upie.",
  "Zbieraj referencje od zadowolonych kandydatów — to najlepszy sourcing.",
  "Ustaw realny timeline z klientem na starcie — unikniesz spalonych ofert.",
  "Jeden dobrze dopasowany kandydat to więcej niż pięciu 'może pasuje'.",
  "Pytaj kandydata, kogo poleca — talenty znają talenty.",
  "Aktualizuj etap od razu po zmianie — pipeline to Twoja mapa.",
];

function tipOfTheDay(): string {
  const now = new Date();
  const dayOfYear = Math.floor(
    (now.getTime() - new Date(now.getFullYear(), 0, 0).getTime()) / 86_400_000
  );
  return `💡 Porada dnia: ${RECRUITER_TIPS[dayOfYear % RECRUITER_TIPS.length]}`;
}

// Contextual greetings when the user lands on a section (keyed by first path seg).
const ROUTE_COMMENTS: Record<string, string> = {
  candidates: "Czas na sourcing! ⛏️",
  jobs: "Nowe rekrutacje czekają! 🎯",
  clients: "Zadbaj o klientów! 🤝",
  "my-clients": "Twoi klienci Cię potrzebują! 🤝",
  calendar: "Co dziś w planie? 📅",
  contracts: "Papierologia, ale ważna! 📄",
  insights: "Czas na liczby! 📊",
  talents: "Skarbnica talentów! 💎",
  dashboard: "Witaj z powrotem! 👋",
};

function routeCommentFor(pathname: string | null): string | null {
  if (!pathname) return null;
  const seg = pathname.split("/").filter(Boolean)[0] ?? "dashboard";
  return ROUTE_COMMENTS[seg] ?? null;
}

// Konami code → "party mode".
const KONAMI = [
  "ArrowUp", "ArrowUp", "ArrowDown", "ArrowDown",
  "ArrowLeft", "ArrowRight", "ArrowLeft", "ArrowRight", "b", "a",
];

/**
 * Floating game-world mascot — shown only in Kids mode. Idles with a gentle
 * float + periodic blink, tosses the occasional encouragement, waves on hover
 * and reacts (pop + bubble) when petted or when a `celebrate()` fires. A small
 * hover-revealed control cluster toggles sound and swaps the buddy character.
 */
export function KidsMascot() {
  const kidsMode = useThemeStore((s) => s.kidsMode);
  const kidsSound = useThemeStore((s) => s.kidsSound);
  const kidsAutoTalk = useThemeStore((s) => s.kidsAutoTalk);
  const kidsBuddy = useThemeStore((s) => s.kidsBuddy);
  const toggleKidsSound = useThemeStore((s) => s.toggleKidsSound);
  const toggleKidsAutoTalk = useThemeStore((s) => s.toggleKidsAutoTalk);
  const cycleKidsBuddy = useThemeStore((s) => s.cycleKidsBuddy);
  const firstName = useAuthStore((s) => s.user?.name)?.trim().split(/\s+/)[0];
  const pathname = usePathname();

  const [mounted, setMounted] = useState(false);
  const [popping, setPopping] = useState(false);
  const [party, setParty] = useState(false);
  const [bubble, setBubble] = useState<string | null>(null);
  const timersRef = useRef<number[]>([]);
  const streakRef = useRef(0);
  const greetedRef = useRef(false);
  const firstRouteRef = useRef(true);
  const konamiRef = useRef(0);

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

  // On first appearance: a time-of-day greeting, then the daily recruiter tip.
  useEffect(() => {
    if (!kidsMode || greetedRef.current) return;
    greetedRef.current = true;
    const ts = [
      window.setTimeout(() => setBubble(greetingFor(firstName)), 900),
      window.setTimeout(() => setBubble(null), 6500),
      window.setTimeout(() => setBubble(tipOfTheDay()), 8000),
      window.setTimeout(() => setBubble(null), 15500),
    ];
    return () => ts.forEach((t) => window.clearTimeout(t));
  }, [kidsMode, firstName]);

  // Occasional unprompted slogan (skipped while the tab is hidden). When
  // auto-talk is on, the mascot also speaks it aloud.
  useEffect(() => {
    if (!kidsMode) return;
    const id = window.setInterval(() => {
      if (document.hidden) return;
      const slogan = pick(MOTIVATIONAL_SLOGANS);
      setBubble(slogan);
      if (kidsAutoTalk) speak(slogan);
      timersRef.current.push(window.setTimeout(() => setBubble(null), 5000));
    }, kidsAutoTalk ? 90_000 : 150_000); // more chatty when auto-talk is on
    return () => window.clearInterval(id);
  }, [kidsMode, kidsAutoTalk]);

  // Contextual comment when the user lands on a new section (skips first mount).
  useEffect(() => {
    if (!kidsMode) return;
    if (firstRouteRef.current) {
      firstRouteRef.current = false;
      return;
    }
    const comment = routeCommentFor(pathname);
    if (!comment) return;
    const show = window.setTimeout(() => setBubble(comment), 500);
    const hide = window.setTimeout(() => setBubble(null), 4000);
    return () => {
      window.clearTimeout(show);
      window.clearTimeout(hide);
    };
  }, [kidsMode, pathname]);

  // Konami code → party mode: dance + confetti storm.
  useEffect(() => {
    if (!kidsMode) return;
    const onKey = (e: KeyboardEvent) => {
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      konamiRef.current = key === KONAMI[konamiRef.current] ? konamiRef.current + 1 : key === KONAMI[0] ? 1 : 0;
      if (konamiRef.current === KONAMI.length) {
        konamiRef.current = 0;
        setParty(true);
        setBubble("🎉 TRYB IMPREZY! 🎉");
        if (kidsSound) speak("Impreza!");
        celebrateParty();
        // Standalone timers (not in timersRef) so a celebrate's react() can't
        // clear them mid-party and leave the mascot dancing forever.
        window.setTimeout(() => setParty(false), 5200);
        window.setTimeout(() => setBubble((b) => (b === "🎉 TRYB IMPREZY! 🎉" ? null : b)), 5200);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [kidsMode, kidsSound]);

  useEffect(() => clearTimers, [clearTimers]);

  // Click the mascot → a motivational slogan, spoken aloud when sound is on.
  const onMotivate = useCallback(() => {
    const slogan = pick(MOTIVATIONAL_SLOGANS);
    react(slogan, 650, 5000);
    if (kidsSound) speak(slogan);
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
          onClick={toggleKidsAutoTalk}
          aria-label={kidsAutoTalk ? "Wyłącz auto-mówienie" : "Włącz auto-mówienie"}
          title={kidsAutoTalk ? "Auto-mówienie: wł." : "Auto-mówienie: wył."}
          className={`h-7 w-7 flex items-center justify-center rounded-full border-2 bg-card shadow-md hover:scale-110 transition-transform ${kidsAutoTalk ? "border-primary text-primary" : "border-primary/40 text-foreground"}`}
        >
          {kidsAutoTalk ? <MessageCircle className="h-3.5 w-3.5" /> : <MessageCircleOff className="h-3.5 w-3.5" />}
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
          onClick={onMotivate}
          aria-label="Zmotywuj mnie!"
          title="Kliknij po motywację!"
          className="kids-buddy pointer-events-auto outline-none"
        >
          <span className={party ? "kids-anim-dance block" : popping ? "kids-anim-pop block" : "kids-anim-float block"}>
            <Buddy id={kidsBuddy} waving={popping || party} />
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
