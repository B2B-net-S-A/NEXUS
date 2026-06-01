"use client";

import { useEffect } from "react";
import { useThemeStore } from "@/store/theme";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useThemeStore((s) => s.theme);
  const palette = useThemeStore((s) => s.palette);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
  }, [theme]);

  useEffect(() => {
    document.documentElement.dataset.theme = palette;
  }, [palette]);

  return <>{children}</>;
}
