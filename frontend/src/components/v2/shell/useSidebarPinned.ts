"use client";

import { useCallback, useEffect, useState } from "react";

export const SIDEBAR_PINNED_KEY = "sidebar_pinned_v2";

type SidebarPinnedUpdate = boolean | ((previous: boolean) => boolean);

/**
 * Persisted desktop-sidebar preference with an SSR-stable first render.
 *
 * The server cannot read localStorage, so both SSR and the first browser render
 * deliberately start expanded. The stored preference is applied after mount;
 * reading it inside useState would render different markup and trigger React
 * hydration error #418 whenever a user had the sidebar collapsed.
 */
export function useSidebarPinned(): [boolean, (next: SidebarPinnedUpdate) => void] {
  const [pinned, setPinned] = useState(true);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(SIDEBAR_PINNED_KEY);
      if (stored === "false") setPinned(false);
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
