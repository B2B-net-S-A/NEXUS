"use client";

import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  groupedAreaItems,
  listedSettingsAreas,
  settingsItemHref,
  type SettingsAreaId,
  type SettingsContext,
  type SettingsItemId,
} from "@/lib/settings-registry";

type SettingsUser = Parameters<typeof listedSettingsAreas>[0];

interface SettingsSideNavProps {
  user: SettingsUser;
  areaId: SettingsAreaId;
  itemId?: SettingsItemId;
  context: SettingsContext;
}

/** Lewa kolumna Ustawień (20.10.2026): po wejściu w obszar widać jego pozycje
 *  w grupach i pozostałe obszary — przejście do sąsiedniego ekranu to jedno
 *  kliknięcie, bez powrotu do listy. Na wąskim ekranie jej nie ma; tam zostaje
 *  ścieżka i lista obszaru. */
export function SettingsSideNav({ user, areaId, itemId, context }: SettingsSideNavProps) {
  const areas = listedSettingsAreas(user, context);
  return (
    <nav
      aria-label="Ustawienia"
      className="hidden w-60 shrink-0 self-start lg:sticky lg:top-4 lg:block lg:max-h-[calc(100dvh-6rem)] lg:overflow-y-auto"
    >
      <Link
        href="/settings"
        className="mb-2 flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
        Wszystkie obszary
      </Link>
      <ul className="space-y-0.5">
        {areas.map((area) => {
          const current = area.id === areaId;
          const groups = current ? groupedAreaItems(user, area.id, context) : [];
          return (
            <li key={area.id}>
              <Link
                href={`/settings?area=${area.id}`}
                aria-current={current && !itemId ? "page" : undefined}
                className={cn(
                  "block rounded-lg px-2.5 py-1.5 text-sm font-semibold hover:bg-muted",
                  current ? "text-primary" : "text-foreground",
                )}
              >
                {area.name}
              </Link>
              {current && (
                <div className="mb-2 mt-0.5 space-y-1">
                  {groups.map((group) => (
                    <div key={group.name}>
                      {groups.length > 1 && group.name && (
                        <div className="px-2.5 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                          {group.name}
                        </div>
                      )}
                      <ul>
                        {group.items.map((item) => {
                          const active = item.id === itemId;
                          return (
                            <li key={item.id}>
                              <Link
                                href={settingsItemHref(item)}
                                aria-current={active ? "page" : undefined}
                                className={cn(
                                  "block rounded-lg px-2.5 py-1.5 text-[13px]",
                                  active
                                    ? "bg-primary/10 font-semibold text-primary"
                                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                                )}
                              >
                                {item.title}
                              </Link>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
