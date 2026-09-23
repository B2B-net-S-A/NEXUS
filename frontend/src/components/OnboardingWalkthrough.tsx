"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { X, ArrowRight, LayoutDashboard, Users, Briefcase, Sparkles, CheckCircle2 } from "lucide-react";
import {
  clearOnboardingCompleted,
  markOnboardingCompleted,
} from "@/lib/onboarding-storage";

/** Zdarzenie otwierające przewodnik (Ustawienia → „Pokaż przewodnik"). */
export const OPEN_ONBOARDING_EVENT = "nexus:open-onboarding";

export function requestOnboardingOpen(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(OPEN_ONBOARDING_EVENT));
}

// ── Steps config ──────────────────────────────────────────────────────────────

const STEPS = [
  {
    id: "dashboard",
    icon: <LayoutDashboard className="w-8 h-8 text-primary" />,
    title: "Dashboard",
    description: "Twoje centrum dowodzenia — statystyki rekrutacji, aktywności i KPI w jednym miejscu. Szybki podgląd pipeline'ów i nadchodzących spotkań.",
    action: "Zobacz Dashboard",
    href: "/",
  },
  {
    id: "candidates",
    icon: <Users className="w-8 h-8 text-violet-500" />,
    title: "Kandydaci",
    description: "Zarządzaj bazą kandydatów, dodawaj profile, śledź statusy i źródła. Możesz importować CVs i porównywać kandydatów obok siebie.",
    action: "Przejdź do Kandydatów",
    href: "/candidates",
  },
  {
    id: "jobs",
    icon: <Briefcase className="w-8 h-8 text-emerald-500" />,
    title: "Ogłoszenia",
    description: "Twórz rekrutacje z pomocą AI, zarządzaj pipeline'ami rekrutacyjnymi dla każdej z nich i publikuj ogłoszenia na portalach.",
    action: "Przejdź do Ogłoszeń",
    href: "/jobs",
  },
  {
    id: "ai-search",
    icon: <Sparkles className="w-8 h-8 text-amber-500" />,
    title: "Wyszukiwanie AI",
    description: "Używaj semantycznego wyszukiwania AI, aby znajdować idealnych kandydatów. System automatycznie dopasowuje kandydatów do rekrutacji na podstawie umiejętności i doświadczenia.",
    action: "Spróbuj AI Matching",
    href: "/jobs",
  },
];

export function useOnboarding() {
  const [shouldShow, setShouldShow] = useState(false);

  // Bez automatycznego startu (przegląd UX 17.09.2026): modal zasłaniał
  // pierwszy ekran nowej osoby. Przewodnik otwiera się wyłącznie na żądanie.
  useEffect(() => {
    const open = () => setShouldShow(true);
    window.addEventListener(OPEN_ONBOARDING_EVENT, open);
    return () => window.removeEventListener(OPEN_ONBOARDING_EVENT, open);
  }, []);

  const dismiss = () => {
    markOnboardingCompleted();
    setShouldShow(false);
  };

  const resetOnboarding = () => {
    clearOnboardingCompleted();
    setShouldShow(true);
  };

  return { shouldShow, dismiss, resetOnboarding };
}

// ── Component ─────────────────────────────────────────────────────────────────

export function OnboardingWalkthrough({ onDismiss }: { onDismiss: () => void }) {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [closing, setClosing] = useState(false);

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;

  const handleClose = () => {
    setClosing(true);
    setTimeout(onDismiss, 200);
  };

  const handleNext = () => {
    if (isLast) {
      handleClose();
    } else {
      setStep(s => s + 1);
    }
  };

  const handleNavigate = () => {
    if (current.href) {
      router.push(current.href);
    }
    handleClose();
  };

  return (
    <div
      className={`fixed inset-0 bg-black/50 z-200 flex items-center justify-center p-4 transition-opacity duration-200 ${closing ? "opacity-0" : "opacity-100"}`}
    >
      {/* Krótki ekran (telefon w poziomie): karta przewija się, więc
          „Dalej” / „Pomiń” zawsze da się osiągnąć. */}
      <div className="bg-card dark:bg-muted rounded-2xl shadow-2xl w-full max-w-md max-h-[calc(100dvh-2rem)] overflow-y-auto">
        {/* Header */}
        <div className="bg-linear-to-r from-blue-600 to-violet-600 px-6 pt-6 pb-4 text-white">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-xl font-bold">Witaj w Nexus! 🚀</h2>
              <p className="text-primary text-sm mt-1">Twój system ATS nowej generacji</p>
            </div>
            <button
              onClick={handleClose}
              aria-label="Zamknij"
              className="hit-area text-white/70 hover:text-white transition-colors ml-4"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Step dots */}
          <div className="flex gap-2 mt-4">
            {STEPS.map((s, i) => (
              <button
                key={s.id}
                onClick={() => setStep(i)}
                className={`h-1.5 rounded-full transition-all ${
                  i === step ? "bg-card w-6" : i < step ? "bg-card/60 w-4" : "bg-card/30 w-4"
                }`}
              />
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="p-6">
          <div className="flex flex-col items-center text-center gap-4">
            <div className="w-16 h-16 rounded-2xl bg-muted dark:bg-muted flex items-center justify-center">
              {current.icon}
            </div>
            <div>
              <h3 className="text-xl font-bold text-foreground dark:text-foreground">
                {current.title}
              </h3>
              <p className="text-muted-foreground dark:text-muted-foreground text-sm mt-2 leading-relaxed">
                {current.description}
              </p>
            </div>
          </div>

          {/* Step counter */}
          <p className="text-center text-xs text-muted-foreground mt-4">
            Krok {step + 1} z {STEPS.length}
          </p>
        </div>

        {/* Footer */}
        <div className="px-6 pb-6 flex gap-2">
          <button
            onClick={handleNavigate}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 border border-border dark:border-border text-foreground dark:text-muted-foreground rounded-xl text-sm font-medium hover:bg-muted dark:hover:bg-muted transition-colors"
          >
            {current.action}
          </button>
          <button
            onClick={handleNext}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            {isLast ? (
              <><CheckCircle2 className="w-4 h-4" /> Zacznij pracę!</>
            ) : (
              <>Dalej <ArrowRight className="w-4 h-4" /></>
            )}
          </button>
        </div>

        {/* Skip */}
        <div className="text-center pb-4">
          <button onClick={handleClose} className="text-xs text-muted-foreground hover:text-muted-foreground transition-colors">
            Pomiń przewodnik
          </button>
        </div>
      </div>
    </div>
  );
}
