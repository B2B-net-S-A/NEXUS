"use client";

/**
 * Miejsce tuż pod paskiem zakładek narzędzi osoby (09.10.2026). Panel osoby
 * wkłada tu zwiniętą linię „Warunki i następny etap”, żeby głowa panelu miała
 * tę samą wysokość w każdej zakładce — pasek zakładek nie zjeżdża wtedy w dół
 * po wyjściu ze „Screeningu”.
 *
 * Osobny moduł: dok osoby podaje treść, `PersonWorkbenchTabs` ją renderuje,
 * a żaden z nich nie musi importować drugiego.
 */

import { createContext, type ReactNode } from "react";

export const WorkbenchBelowTabsContext = createContext<ReactNode>(null);
