"use client";

import { useEffect } from "react";
import { useThemeStore } from "@/store/theme";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useThemeStore((s) => s.theme);
  const palette = useThemeStore((s) => s.palette);
  const kidsMode = useThemeStore((s) => s.kidsMode);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
  }, [theme]);

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

  return <>{children}</>;
}
