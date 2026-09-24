"use client";

import { useCallback, useEffect, useState } from "react";

export const SIDEBAR_PINNED_KEY = "sidebar_pinned_v2";

/** Od tej szerokości pasek jest domyślnie przypięty (240 px). Węższy ekran
 *  (tablet 768–1279 px) bez zapamiętanego wyboru dostaje szynę 60 px —
 *  przypięty pasek zostawiał treści ≈480 px (audyt responsywności 23.09.2026). */
export const SIDEBAR_DEFAULT_PINNED_QUERY = "(min-width: 1280px)";

type SidebarPinnedUpdate = boolean | ((previous: boolean) => boolean);

/**
 * Persisted desktop-sidebar preference with an SSR-stable first render.
 *
 * The server cannot read localStorage, so both SSR and the first browser render
 * deliberately start expanded. The stored preference is applied after mount;
 * reading it inside useState would render different markup and trigger React
 * hydration error #418 whenever a user had the sidebar collapsed.
 *
 * Without a stored preference the default follows the viewport after mount:
 * pinned from 1280 px, collapsed rail below. A stored choice always wins.
 */
export function useSidebarPinned(): [boolean, (next: SidebarPinnedUpdate) => void] {
  const [pinned, setPinned] = useState(true);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(SIDEBAR_PINNED_KEY);
      if (stored === "false") setPinned(false);
      else if (stored === null && typeof window.matchMedia === "function") {
        setPinned(window.matchMedia(SIDEBAR_DEFAULT_PINNED_QUERY).matches);
      }
    } catch {
      /* UI preference only — keep the safe expanded default. */
    }
  }, []);

  const updatePinned = useCallback((next: SidebarPinnedUpdate) => {
    setPinned((previous) => {
      const resolved = typeof next === "function" ? next(previous) : next;
      try {
        window.localStorage.setItem(SIDEBAR_PINNED_KEY, String(resolved));
      } catch {
        /* Keep the in-memory interaction working when storage is unavailable. */
      }
      return resolved;
    });
  }, []);

  return [pinned, updatePinned];
}
