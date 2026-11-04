"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

/**
 * Stan zsynchronizowany z parametrem adresu. Efekt zależy od WARTOŚCI
 * parametru, a nie od tożsamości `searchParams`: miękka nawigacja App Routera
 * (klik w powiadomienie na tej samej stronie) zmienia adres bez odmontowania
 * strony, a inicjalizator `useState` odpala się raz. `null` z adresu NIE
 * cofa ręcznego wyboru — parametr, który zniknął, to nie polecenie.
 */
export function useUrlSyncedState<T extends string>(fromUrl: T | null, fallback: T | null) {
  const [value, setValue] = useState<T | null>(fromUrl ?? fallback);
  useEffect(() => {
    if (fromUrl !== null) setValue(fromUrl);
  }, [fromUrl]);
  return [value, setValue] as const;
}

/** Podmienia parametry bieżącego adresu bez dokładania wpisu w historii. */
export function writeUrlParams(patch: Record<string, string | null>) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  for (const [name, value] of Object.entries(patch)) {
    if (value == null) url.searchParams.delete(name);
    else url.searchParams.set(name, value);
  }
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== current) window.history.replaceState(window.history.state, "", next);
}

/**
 * Zapis stanu widoku w adresie (zakładka, filtr, strona listy) bez przewijania.
 *
 * `router.replace(href, { scroll: false })` przewija na produkcji stronę do
 * jej początku, gdy zmieniają się same parametry adresu: Next 15.5 gubi
 * `scroll: false` w ścieżce „aliased prefetch” pod `loading.tsx` (opis:
 * docs/claude/ui/parametry-adresu-natywna-historia-nie-router-replace.md).
 * Natywna historia omija router, a Next i tak przenosi adres do
 * `useSearchParams` — pod warunkiem stanu `null`; z `history.state` (jak
 * w `writeUrlParams`) uznałby wywołanie za własne i niczego nie odświeżył.
 *
 * Inna ścieżka niż bieżąca to zwykła nawigacja i idzie przez router — te same
 * komponenty stoją też w harnessach `/preview/*` pod innym adresem.
 */
export function useUrlWriter() {
  const router = useRouter();
  return useMemo(() => {
    const write = (mode: "replace" | "push", href: string) => {
      // Sam `?parametry` albo `#kotwica` (pusta ścieżka) to też bieżąca strona.
      const path = href.split(/[?#]/, 1)[0];
      if (path !== "" && path !== window.location.pathname) {
        router[mode](href, { scroll: false });
        return;
      }
      const { pathname, search, hash } = window.location;
      const managed = window.history.state?.__NA === true;
      // Ten sam adres nie dokłada wpisu historii — jak w `router.push`.
      if (mode === "push" && href !== `${pathname}${search}${hash}`) {
        window.history.pushState(null, "", href);
      } else {
        window.history.replaceState(null, "", href);
      }
      // Next przejmuje historię dopiero w efekcie routera. Zapis z efektu
      // dziecka w pierwszej klatce (poza `<Suspense>`) minąłby router i zostawił
      // wpis bez jego stanu — „Wstecz” przestaje wtedy działać. Adres ustawia
      // wtedy router; strona dopiero się otwiera, więc nie ma czego przewijać.
      if (managed && window.history.state?.__NA !== true) {
        router.replace(href, { scroll: false });
      }
    };
    return {
      /** Podmienia adres — „Wstecz” prowadzi do poprzedniej strony. */
      replaceUrl: (href: string) => write("replace", href),
      /** Dokłada wpis historii — „Wstecz” cofa ten krok. */
      pushUrl: (href: string) => write("push", href),
    };
  }, [router]);
}
