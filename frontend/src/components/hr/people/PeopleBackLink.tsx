"use client";

import { useEffect, useState, type MouseEvent } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { previousPeopleList } from "./person-history-view";

interface NavigationEntryLike {
  url: string | null;
  index: number;
  sameDocument?: boolean;
}

interface NavigationLike {
  currentEntry: NavigationEntryLike | null;
  entries: () => NavigationEntryLike[];
}

/**
 * Poprzedni wpis historii karty (Navigation API — Chrome i Edge, czyli
 * laptopy zespołu). `document.referrer` się tu nie nadaje: nawigacja Next
 * w przeglądarce go nie zmienia. Bez API (Safari, Firefox) — `null`.
 */
function previousEntryUrl(): string | null {
  const navigation = (window as unknown as { navigation?: NavigationLike }).navigation;
  const current = navigation?.currentEntry;
  if (!navigation || !current || current.index < 1) return null;
  try {
    return navigation.entries()[current.index - 1]?.url ?? null;
  } catch {
    return null;
  }
}

/**
 * „← Ludzie” w kartotece. Gdy kartotekę otwarto z katalogu, wraca do niego
 * krokiem wstecz — filtry katalogu są w adresie, więc zostają. W innym
 * wypadku (link z dzwonka, Struktury, nowa karta) prowadzi na `/people`.
 */
export function PeopleBackLink() {
  const [previous, setPrevious] = useState<string | null>(null);
  useEffect(() => {
    setPrevious(previousPeopleList(previousEntryUrl(), window.location.origin));
  }, []);

  const goBack = (event: MouseEvent<HTMLAnchorElement>) => {
    // Nowa karta (Ctrl/⌘, środkowy przycisk) idzie zwykłym linkiem.
    if (!previous || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) {
      return;
    }
    event.preventDefault();
    // Krok wstecz w historii (App Router obsługuje `popstate`) — bez
    // `useRouter`, żeby kartoteka działała też w harnessie i testach.
    window.history.back();
  };

  return (
    <Link
      href={previous ?? "/people"}
      onClick={goBack}
      className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-4 w-4" aria-hidden />
      Ludzie
    </Link>
  );
}
