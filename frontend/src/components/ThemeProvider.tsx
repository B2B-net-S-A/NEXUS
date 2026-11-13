"use client";

import { useEffect } from "react";
import { companyDate, worldAvailable } from "@/lib/worlds/seasons";
import { useThemeStore, worldScheme } from "@/store/theme";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useThemeStore((s) => s.theme);
  const palette = useThemeStore((s) => s.palette);
  const kidsMode = useThemeStore((s) => s.kidsMode);

  const world = useThemeStore((s) => s.world);
  const worldBeforeSeason = useThemeStore((s) => s.worldBeforeSeason);
  const setWorld = useThemeStore((s) => s.setWorld);

  // Świat narzuca schemat (`docs/claude/ui/swiaty-wygladu.md`): ciemny świat
  // dostaje klasę .dark, żeby warianty `dark:` w komponentach pasowały do jego
  // tokenów, a jasny ją zdejmuje.
  useEffect(() => {
    const root = document.documentElement;
    const forced = worldScheme(world);
    root.classList.toggle("dark", forced ? forced === "dark" : theme === "dark");
  }, [theme, world]);

  useEffect(() => {
    document.documentElement.dataset.theme = palette;
  }, [palette]);

  // Styl „Wyraźny” (cienie) jest stały od 13.11.2026 — bez przełącznika.
  useEffect(() => {
    document.documentElement.dataset.soft = "true";
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (kidsMode) {
      root.dataset.kids = "true";
    } else {
      delete root.dataset.kids;
    }
  }, [kidsMode]);

  useEffect(() => {
    const root = document.documentElement;
    if (world && world !== "none") {
      root.dataset.world = world;
    } else {
      delete root.dataset.world;
    }
  }, [world]);

  // Sezonowy świat po swoim terminie: powrót do świata sprzed sezonu.
  useEffect(() => {
    if (!worldAvailable(world, companyDate())) setWorld(worldBeforeSeason ?? "none");
  }, [world, worldBeforeSeason, setWorld]);

  return <>{children}</>;
}
