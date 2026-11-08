"use client";

/**
 * Wejścia do panelu „Moi ludzie":
 *
 * - `MyPeopleTopbarButton` — przycisk z licznikiem obok dzwonka. To jest
 *   GŁÓWNE, dostępne wejście (klawiatura, czytnik ekranu, mobile);
 * - `MyPeopleBuddy` — mała postać w rogu, sama, bez liczby i dymku (audyt
 *   08.11.2026, U6: liczba 872 i dymek przestały być sygnałem). Ukrywa się ją
 *   w stopce panelu. Ustępuje maskotce Jarvisa (0330 — ten sam róg), gdy ta
 *   jest widoczna;
 * - `MyPeopleRoot` — montowany w `AppShellV2`: panel, postać i obsługa
 *   `?people=1` z linku w dzwonku.
 */

import { Suspense, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { usePathname, useSearchParams } from "next/navigation";
import { useUrlWriter } from "@/lib/url-selection";
import { Users } from "lucide-react";

import { useMyPeopleSummary } from "@/lib/api/myPeople";
import { fetchJarvisPrefs, fetchJarvisStatus, jarvisKeys } from "@/lib/jarvis/api";
import { recentJobsLabel } from "@/lib/my-people-summary";
import { useCapability } from "@/hooks/useCapability";
import { useMyPeoplePanel } from "@/store/my-people";
import { useThemeStore } from "@/store/theme";
import { useUiStore } from "@/store/ui";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { MyPeoplePanel } from "./MyPeoplePanel";

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
      aria-label={count > 0 ? `Moi ludzie — ${recentJobsLabel(count)}` : "Moi ludzie"}
      title={count > 0 ? `${recentJobsLabel(count)} (m)` : "Moi ludzie (m)"}
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

export function MyPeopleBuddyView({ onOpen }: { onOpen: () => void }) {
  return (
    // `data-floating-corner`: na czas przeklikania nowości postać znika, bo
    // przy 1280×720 zasłania stopkę panelu (`NoveltyLayer`).
    <div
      data-floating-corner
      className="fixed bottom-[calc(1.25rem+env(safe-area-inset-bottom))] right-[calc(1.25rem+env(safe-area-inset-right))] z-30 flex items-end gap-2"
    >
      <button
        type="button"
        onClick={onOpen}
        aria-label="Moi ludzie"
        className="relative flex h-12 w-12 items-center justify-center rounded-full border border-border bg-primary text-primary-foreground shadow-lg transition-transform hover:scale-105"
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
  const panelOpen = useMyPeoplePanel((s) => s.open);
  const openPanel = useMyPeoplePanel((s) => s.openPanel);
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Na stronie rekrutacji prawy dolny róg zajmuje dok kandydata na tablicy —
  // postać by go zasłaniała. Licznik zostaje w topbarze.
  const onJobPage = /^\/jobs\/\d+/.test(pathname ?? "");
  if (!mounted || !allowed || hidden || panelOpen || onJobPage) return null;
  if (jarvisOwnsCorner !== false) return null;
  return <MyPeopleBuddyView onOpen={openPanel} />;
}

/** `?people=1` (link z dzwonka) otwiera panel i znika z adresu. */
function PeopleParamOpener() {
  const params = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const pathname = usePathname();
  const openPanel = useMyPeoplePanel((s) => s.openPanel);
  const flag = params?.get("people");
  useEffect(() => {
    if (flag !== "1" || !pathname) return;
    openPanel();
    const next = new URLSearchParams(params?.toString() ?? "");
    next.delete("people");
    const qs = next.toString();
    replaceUrl(qs ? `${pathname}?${qs}` : pathname);
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
