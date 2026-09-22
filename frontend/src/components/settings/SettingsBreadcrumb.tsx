"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { SettingsArea, SettingsItem } from "@/lib/settings-registry";

/** Ścieżka „Ustawienia / Obszar / Pozycja" — ta sama na `/settings` i nad
 *  podstronami z własną trasą (layout Ustawień). */
export function SettingsBreadcrumb({ area, item }: { area?: SettingsArea; item?: SettingsItem }) {
  return (
    <nav aria-label="Ścieżka" className="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
      <Link href="/settings" className="hover:text-foreground hover:underline">
        Ustawienia
      </Link>
      {area && (
        <>
          <ChevronRight className="h-3.5 w-3.5" aria-hidden />
          {item ? (
            <Link href={`/settings?area=${area.id}`} className="hover:text-foreground hover:underline">
              {area.name}
            </Link>
          ) : (
            <span className="font-medium text-foreground" aria-current="page">
              {area.name}
            </span>
          )}
        </>
      )}
      {item && (
        <>
          <ChevronRight className="h-3.5 w-3.5" aria-hidden />
          <span className="font-medium text-foreground" aria-current="page">
            {item.title}
          </span>
        </>
      )}
    </nav>
  );
}
