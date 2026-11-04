"use client";

import { useMemo } from "react";
import { visibleNavEntries } from "@/lib/nav-registry";
import { useAuthStore } from "@/store/auth";

/**
 * Czy użytkownik ma okienko „Rozmowy” w górnym pasku. Ten sam warunek co
 * pozycja „Kalendarz” w menu: trasa cyklu rozmów odmawia pozostałym, więc
 * u nich rozmowy i prepy zostają w dzwonku.
 */
export function useHasInterviewsWindow(): boolean {
  const user = useAuthStore((state) => state.user);
  return useMemo(
    () =>
      visibleNavEntries(user, { contactQueueEnabled: false }).some(
        (entry) => entry.id === "calendar",
      ),
    [user],
  );
}
