"use client";

import { useEffect } from "react";
import { applyUiFlagUrlOverride } from "@/lib/ui-flag";

/**
 * Mounted once at the root. Reads `?ui=v1|v2` from the URL on entry and, if it
 * differs from the current cookie, persists the override and hard-reloads so
 * the server-rendered `data-ui` attribute (set from cookie in layout.tsx)
 * matches the user's choice.
 *
 * Safe to render under any shell — it only fires when a URL param is present.
 */
export function UiFlagUrlSync() {
  useEffect(() => {
    const applied = applyUiFlagUrlOverride();
    if (applied && typeof window !== "undefined") {
      // Strip the ui param and reload so SSR picks up the new cookie.
      const url = new URL(window.location.href);
      url.searchParams.delete("ui");
      window.location.replace(url.toString());
    }
  }, []);
  return null;
}
