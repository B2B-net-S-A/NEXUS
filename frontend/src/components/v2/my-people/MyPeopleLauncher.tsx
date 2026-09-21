"use client";

/**
 * Wejścia do panelu „Moi ludzie":
 *
 * - `MyPeopleTopbarButton` — przycisk z licznikiem obok dzwonka. To jest
 *   GŁÓWNE, dostępne wejście (klawiatura, czytnik ekranu, mobile);
 * - `MyPeopleBuddy` — mała postać w rogu z tym samym licznikiem i dymkiem.
 *   Dodatek: mówi tylko, gdy ma konkret (zdania z szablonów, zero AI), raz na
 *   sesję dla tej samej treści, i da się ją ukryć. Ustępuje maskotce
 *   Jarvisa (0330 — ten sam róg), gdy ta jest widoczna;
 * - `MyPeopleRoot` — montowany w `AppShellV2`: panel, postać i obsługa
 *   `?people=1` z linku w dzwonku.
 */

import { Suspense, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Users, X } from "lucide-react";

import { useMyPeopleSummary } from "@/lib/api/myPeople";
import { fetchJarvisPrefs, fetchJarvisStatus, jarvisKeys } from "@/lib/jarvis/api";
import { sentencesKey, summarySentences } from "@/lib/my-people-summary";
import { prefersReducedMotion } from "@/lib/prefers-reduced-motion";
import { useCapability } from "@/hooks/useCapability";
import { useMyPeoplePanel } from "@/store/my-people";
import { useThemeStore } from "@/store/theme";
import { useUiStore } from "@/store/ui";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { MyPeoplePanel } from "./MyPeoplePanel";

const BUBBLE_SEEN_KEY = "nexus:myPeopleBubbleSeen:v1";

function countLabel(n: number): string {
  return n > 99 ? "99+" : String(n);
}

export function MyPeopleTopbarButton() {
  const allowed = useCapability("nav.my_people");
  const toggle = useMyPeoplePanel((s) => s.toggle);
  const open = useMyPeoplePanel((s) => s.open);
  const summary = useMyPeopleSummary(allowed);
  if (!allowed) return null;
  const count = summary.data?.new_matches ?? 0;
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggle}
      aria-pressed={open}
      aria-label={
        count > 0 ? `Moi ludzie — ${count} nowych dopasowań` : "Moi ludzie"
      }
      title="Moi ludzie (m)"
      className="relative"
    >
      <Users className="h-4 w-4" aria-hidden />
      {count > 0 ? (
        <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold text-primary-foreground tabular-nums">
          {countLabel(count)}
        </span>
      ) : null}
    </Button>
  );
}

function readSeenBubble(): string | null {
  try {
    return window.sessionStorage.getItem(BUBBLE_SEEN_KEY);
  } catch {
    return null;
  }
}

function writeSeenBubble(key: string) {
  try {
    window.sessionStorage.setItem(BUBBLE_SEEN_KEY, key);
  } catch {
    // Prywatne okno / zablokowane dane — dymek po prostu pojawi się ponownie.
  }
}

export function MyPeopleBuddyView({
  count,
  sentences,
  showBubble,
  onOpen,
  onDismissBubble,
  onHide,
  animate = true,
}: {
  count: number;
  sentences: string[];
  showBubble: boolean;
  onOpen: () => void;
  onDismissBubble: () => void;
  onHide: () => void;
  animate?: boolean;
}) {
  return (
    <div className="fixed bottom-5 right-5 z-30 flex items-end gap-2">
      {showBubble && sentences.length ? (
        <div
          role="status"
          className="relative max-w-[260px] rounded-xl border border-border bg-card px-3 py-2 text-xs text-foreground shadow-lg"
        >
          <button
            type="button"
            onClick={onDismissBubble}
            aria-label="Zamknij podpowiedź"
            className="absolute right-1 top-1 rounded p-0.5 text-muted-foreground hover:text-foreground"
          >
            <X className="h-3 w-3" aria-hidden />
          </button>
          <div className="space-y-1 pr-3">
            {sentences.slice(0, 2).map((s) => (
              <p key={s}>{s}</p>
            ))}
          </div>
          <div className="mt-1.5 flex gap-2">
            <button
              type="button"
              onClick={onOpen}
              className="text-xs font-medium text-primary hover:underline"
            >
              Pokaż moich ludzi
            </button>
            <button
              type="button"
              onClick={onHide}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Ukryj postać
            </button>
          </div>
        </div>
      ) : null}
      <button
        type="button"
        onClick={onOpen}
        aria-label={count > 0 ? `Moi ludzie — ${count} nowych dopasowań` : "Moi ludzie"}
        className={cn(
          "relative flex h-12 w-12 items-center justify-center rounded-full border border-border bg-primary text-primary-foreground shadow-lg transition-transform hover:scale-105",
        )}
      >
        <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
          <circle cx="16" cy="16" r="13" className="fill-primary-foreground/15" />
          <circle cx="11.5" cy="14" r="2" className="fill-current" />
          <circle cx="20.5" cy="14" r="2" className="fill-current" />
          <path
            d="M10.5 19.5c1.6 2.2 3.4 3.2 5.5 3.2s3.9-1 5.5-3.2"
            className="stroke-current"
            strokeWidth="2"
            strokeLinecap="round"
            fill="none"
          />
        </svg>
        {count > 0 ? (
          <span
            className={cn(
              "absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full border-2 border-background bg-destructive px-1 text-[10px] font-bold text-destructive-foreground tabular-nums",
              // Tylko licznik pulsuje — skacząca postać po tygodniu męczy.
              animate && "animate-pulse",
            )}
          >
            {countLabel(count)}
          </span>
        ) : null}
      </button>
    </div>
  );
}

/**
 * Czy prawy dolny róg zajmuje maskotka Jarvisa. Lustro warunku `showMascot`
 * w `JarvisRoot` — te same klucze zapytań, więc bez dodatkowych żądań.
 * `undefined` = jeszcze nie wiadomo: postać czeka, zamiast mignąć i zniknąć.
 */
function useJarvisOwnsCorner(enabled: boolean): boolean | undefined {
  const kidsMode = useThemeStore((s) => s.kidsMode);
  const status = useQuery({
    queryKey: jarvisKeys.status,
    queryFn: fetchJarvisStatus,
    enabled,
    staleTime: 60_000,
    retry: 0,
  });
  const prefs = useQuery({
    queryKey: jarvisKeys.prefs,
    queryFn: fetchJarvisPrefs,
    enabled: enabled && status.data?.available === true,
    staleTime: 5 * 60_000,
    retry: 0,
  });
  if (kidsMode) return true;
  if (status.isError) return false;
  if (!status.isSuccess) return undefined;
  if (!status.data.available) return false;
  if (prefs.isError) return true;
  if (!prefs.isSuccess) return undefined;
  return prefs.data.enabled !== false;
}

function MyPeopleBuddy() {
  const allowed = useCapability("nav.my_people");
  const hidden = useUiStore((s) => s.hideMyPeopleBuddy);
  const jarvisOwnsCorner = useJarvisOwnsCorner(allowed && !hidden);
  const setHidden = useUiStore((s) => s.setHideMyPeopleBuddy);
  const panelOpen = useMyPeoplePanel((s) => s.open);
  const openPanel = useMyPeoplePanel((s) => s.openPanel);
  const pathname = usePathname();
  const summary = useMyPeopleSummary(allowed);
  const [mounted, setMounted] = useState(false);
  const [dismissedKey, setDismissedKey] = useState<string | null>(null);

  useEffect(() => {
    setMounted(true);
    setDismissedKey(readSeenBubble());
  }, []);

  // Na stronie rekrutacji prawy dolny róg zajmuje dok kandydata na tablicy —
  // postać by go zasłaniała. Licznik zostaje w topbarze.
  const onJobPage = /^\/jobs\/\d+/.test(pathname ?? "");
  if (!mounted || !allowed || hidden || panelOpen || onJobPage) return null;
  if (jarvisOwnsCorner !== false) return null;
  const sentences = summarySentences(summary.data);
  const key = sentencesKey(sentences);
  const dismiss = () => {
    writeSeenBubble(key);
    setDismissedKey(key);
  };
  return (
    <MyPeopleBuddyView
      count={summary.data?.new_matches ?? 0}
      sentences={sentences}
      showBubble={sentences.length > 0 && dismissedKey !== key}
      onOpen={() => {
        dismiss();
        openPanel();
      }}
      onDismissBubble={dismiss}
      onHide={() => setHidden(true)}
      animate={!prefersReducedMotion()}
    />
  );
}

/** `?people=1` (link z dzwonka) otwiera panel i znika z adresu. */
function PeopleParamOpener() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const openPanel = useMyPeoplePanel((s) => s.openPanel);
  const flag = params?.get("people");
  useEffect(() => {
    if (flag !== "1" || !pathname) return;
    openPanel();
    const next = new URLSearchParams(params?.toString() ?? "");
    next.delete("people");
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    // Efekt na WARTOŚCI parametru — miękka nawigacja nie odmontowuje shella.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flag, pathname]);
  return null;
}

export function MyPeopleRoot() {
  const allowed = useCapability("nav.my_people");
  if (!allowed) return null;
  return (
    <>
      <MyPeoplePanel />
      <MyPeopleBuddy />
      <Suspense fallback={null}>
        <PeopleParamOpener />
      </Suspense>
    </>
  );
}
