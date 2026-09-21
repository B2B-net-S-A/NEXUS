"use client";

/**
 * Zachowania „trybu kids” przeniesione z dawnej `KidsMascot` do Jarvisa —
 * od 0330 jest JEDNA maskotka. Aktywne wyłącznie przy `kidsMode`:
 * powitanie i porada dnia, slogany co kilka minut, komentarz przy zmianie
 * sekcji, reakcja na `celebrate()` i tryb imprezy po kodzie Konami.
 * Hook zwraca dymek i nastrój; renderuje go `JarvisMascot`.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { CELEBRATE_EVENT, celebrateParty, type CelebrateVariant } from "@/lib/celebrate";
import { speak } from "@/lib/kidsSound";
import type { JarvisMood } from "@/lib/jarvis/types";

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
  "Ustaw realny timeline z klientem na starcie — unikniesz spalonych rekrutacji.",
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

interface Options {
  enabled: boolean;
  sound: boolean;
  autoTalk: boolean;
  firstName?: string;
}

export function useKidsChatter({ enabled, sound, autoTalk, firstName }: Options) {
  const pathname = usePathname();
  const [bubble, setBubble] = useState<string | null>(null);
  const [mood, setMood] = useState<JarvisMood | null>(null);
  const timersRef = useRef<number[]>([]);
  const streakRef = useRef(0);
  const greetedRef = useRef(false);
  const firstRouteRef = useRef(true);
  const konamiRef = useRef(0);

  const clearTimers = useCallback(() => {
    timersRef.current.forEach((t) => window.clearTimeout(t));
    timersRef.current = [];
  }, []);

  const react = useCallback(
    (msg: string, popMs = 700, bubbleMs = 3200) => {
      clearTimers();
      setMood("success");
      setBubble(msg);
      timersRef.current.push(window.setTimeout(() => setMood(null), popMs));
      timersRef.current.push(window.setTimeout(() => setBubble(null), bubbleMs));
    },
    [clearTimers],
  );

  useEffect(() => {
    if (!enabled) return;
    const onCelebrate = (e: Event) => {
      const detail = (e as CustomEvent<{ message?: string; variant?: CelebrateVariant }>).detail;
      streakRef.current += 1;
      const fallback = VARIANT_BUBBLE[detail?.variant ?? "default"] ?? VARIANT_BUBBLE.default;
      react(streakRef.current % 3 === 0 ? "Seria! 🔥" : detail?.message ?? fallback);
    };
    window.addEventListener(CELEBRATE_EVENT, onCelebrate);
    return () => window.removeEventListener(CELEBRATE_EVENT, onCelebrate);
  }, [enabled, react]);

  useEffect(() => {
    if (!enabled || greetedRef.current) return;
    greetedRef.current = true;
    const ts = [
      window.setTimeout(() => setBubble(greetingFor(firstName)), 900),
      window.setTimeout(() => setBubble(null), 6500),
      window.setTimeout(() => setBubble(tipOfTheDay()), 8000),
      window.setTimeout(() => setBubble(null), 15500),
    ];
    return () => ts.forEach((t) => window.clearTimeout(t));
  }, [enabled, firstName]);

  useEffect(() => {
    if (!enabled) return;
    const id = window.setInterval(
      () => {
        if (document.hidden) return;
        const slogan = pick(MOTIVATIONAL_SLOGANS);
        setBubble(slogan);
        if (autoTalk) speak(slogan);
        timersRef.current.push(window.setTimeout(() => setBubble(null), 5000));
      },
      autoTalk ? 90_000 : 150_000,
    );
    return () => window.clearInterval(id);
  }, [enabled, autoTalk]);

  useEffect(() => {
    if (!enabled) return;
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
  }, [enabled, pathname]);

  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      konamiRef.current = key === KONAMI[konamiRef.current] ? konamiRef.current + 1 : key === KONAMI[0] ? 1 : 0;
      if (konamiRef.current === KONAMI.length) {
        konamiRef.current = 0;
        setMood("working");
        setBubble("🎉 TRYB IMPREZY! 🎉");
        if (sound) speak("Impreza!");
        celebrateParty();
        window.setTimeout(() => setMood(null), 5200);
        window.setTimeout(() => setBubble((b) => (b === "🎉 TRYB IMPREZY! 🎉" ? null : b)), 5200);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, sound]);

  useEffect(() => clearTimers, [clearTimers]);

  const dismiss = useCallback(() => setBubble(null), []);

  return { bubble: enabled ? bubble : null, mood: enabled ? mood : null, dismiss };
}
