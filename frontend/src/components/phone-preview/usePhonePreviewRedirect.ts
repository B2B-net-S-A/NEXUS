"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { BOARD_HOME } from "@/lib/board-access";
import { hasRole, useAuthStore, type User } from "@/store/auth";

import { PHONE_MAX_WIDTH, PREVIEW_PATH, canUsePreview } from "./access";

const FULL_VERSION_KEY = "nexus_full_version";
let fullVersionInMemory = false;

/** „Pełna wersja”: do końca sesji przeglądarki telefon nie wraca sam na podgląd. */
export function chooseFullVersion(): void {
  fullVersionInMemory = true;
  try {
    sessionStorage.setItem(FULL_VERSION_KEY, "1");
  } catch {
    // Zablokowany magazyn: wybór trzyma pamięć strony.
  }
}

function choseFullVersion(): boolean {
  if (fullVersionInMemory) return true;
  try {
    return sessionStorage.getItem(FULL_VERSION_KEY) === "1";
  } catch {
    return false;
  }
}

export function fullVersionHref(user: User | null | undefined): string {
  return hasRole(user, "board") ? BOARD_HOME : "/dashboard";
}

/** Tylko ekran startowy: link z maila albo zakładka ma dalej otwierać swój ekran. */
export function isStartScreen(pathname: string, user: User | null | undefined): boolean {
  return pathname === "/dashboard" || (pathname === "/insights" && hasRole(user, "board"));
}

/** Stoi w powłoce aplikacji, więc nie działa na stronach publicznych. */
export function PhonePreviewRedirect(): null {
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);
  const pathname = usePathname() ?? "";
  const router = useRouter();

  useEffect(() => {
    if (!hydrated || !canUsePreview(user) || !isStartScreen(pathname, user)) return;
    if (!window.matchMedia(`(max-width: ${PHONE_MAX_WIDTH}px)`).matches) return;
    if (choseFullVersion()) return;
    router.replace(PREVIEW_PATH);
  }, [hydrated, user, pathname, router]);

  return null;
}
