"use client"

import { useMemo } from "react"

import {
  CAPABILITY_ROLES,
  hasAnyCapability,
  hasCapability,
  type Capability,
} from "@/lib/capabilities"
import { useAuthStore } from "@/store/auth"

/**
 * Bramka capability dla zalogowanego usera (audyt F-19).
 *
 * Jedno wejście dla wszystkich powierzchni UI: sidebar, Command Palette,
 * Quick Actions, skróty klawiszowe, empty states, modale i `enabled:` zapytań.
 * Backend pozostaje ostatecznym arbitrem — to warstwa UX.
 */
export function useCapability(capability: Capability): boolean {
  const user = useAuthStore((s) => s.user)
  return hasCapability(user, capability)
}

/**
 * Cała macierz capability zalogowanego usera, policzona raz i zmemoizowana.
 * Rejestr ma kilkanaście wpisów, więc liczenie wszystkiego jest tańsze niż
 * utrzymywanie list per komponent (i nie kusi do lokalnych bramek obok
 * rejestru — czyli do usterki, którą F-19 zamyka).
 */
export function useCapabilities(): Record<Capability, boolean> {
  const user = useAuthStore((s) => s.user)
  return useMemo(() => {
    const out = {} as Record<Capability, boolean>
    for (const capability of Object.keys(CAPABILITY_ROLES) as Capability[]) {
      out[capability] = hasCapability(user, capability)
    }
    return out
  }, [user])
}

/** Czy user ma choć jedną z capability (np. „czy w ogóle pokazywać menu Dodaj"). */
export function useAnyCapability(...capabilities: Capability[]): boolean {
  const user = useAuthStore((s) => s.user)
  return hasAnyCapability(user, ...capabilities)
}
