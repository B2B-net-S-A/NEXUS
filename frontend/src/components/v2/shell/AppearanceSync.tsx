"use client";

import { useEffect, useRef } from "react";

import { useUpdateUserPreferences, useUserPreferences } from "@/lib/api/userPreferences";
import { isAccountWorldId } from "@/lib/worlds/world-ids";
import { isThemeWorld, useThemeStore, type ThemeWorld } from "@/store/theme";

/**
 * Świat wyglądu idzie za osobą na każdy komputer (`users.appearance_prefs`,
 * decyzja Artura 13.11.2026, `docs/claude/ui/swiaty-wygladu.md`).
 *
 * Przy wczytaniu wygrywa konto. Konto bez zapisu (`world: null`) dostaje
 * wybór z tej przeglądarki, także dawny „Tryb gry” (`game`). Potem każda
 * zmiana w galerii idzie na konto. Montowane tylko przy własnej sesji —
 * w „podglądzie jako” zapis i tak zwraca 403.
 */
export function AppearanceSync() {
  const prefs = useUserPreferences();
  const update = useUpdateUserPreferences();
  const world = useThemeStore((s) => s.world);
  const kidsMode = useThemeStore((s) => s.kidsMode);
  const before = useThemeStore((s) => s.worldBeforeSeason);
  const applyAccountWorld = useThemeStore((s) => s.applyAccountWorld);
  const synced = useRef(false);
  const lastSent = useRef<string | null>(null);

  const accountWorld = kidsMode ? "game" : world;
  const signature = `${accountWorld}|${before ?? ""}`;

  // Jeden efekt, nie dwa: przy wczytaniu z konta ten sam cykl renderu ma
  // jeszcze stary wybór z przeglądarki i drugi efekt wysyłał go z powrotem,
  // nadpisując konto (złapane testem 13.11.2026).
  useEffect(() => {
    if (!prefs.isSuccess) return;
    const appearance = prefs.data.appearance;
    if (!appearance) return; // serwer bez pola — zostaje przeglądarka
    if (!synced.current) {
      synced.current = true;
      const server = appearance.world;
      if (server && isAccountWorldId(server)) {
        const serverBefore = isThemeWorld(appearance.world_before_season) ? appearance.world_before_season : null;
        const kids = server === "game";
        applyAccountWorld(kids ? "none" : (server as ThemeWorld), serverBefore, kids);
        lastSent.current = `${server}|${serverBefore ?? ""}`;
        return;
      }
      // Konto puste — niżej wyślemy wybór z tej przeglądarki.
    }
    if (lastSent.current === signature) return;
    lastSent.current = signature;
    update.mutate({ appearance: { world: accountWorld, world_before_season: before } });
    // `update` zmienia tożsamość przy każdym renderze — świadomie poza zależnościami.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefs.isSuccess, prefs.data, signature, accountWorld, before, applyAccountWorld]);

  return null;
}
