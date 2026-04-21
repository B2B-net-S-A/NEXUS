"use client"

import { useEffect } from "react"
import { usePathname, useRouter } from "next/navigation"

import {
  requiresOnboarding,
  useAuthStore,
} from "@/store/auth"

/** Ścieżki wyłączone z guarda — login + same /onboarding + share portal. */
const EXEMPT_PREFIXES = ["/login", "/onboarding", "/share/", "/apply/", "/403"]

function isExempt(pathname: string | null): boolean {
  if (!pathname) return false
  return EXEMPT_PREFIXES.some((p) =>
    p.endsWith("/") ? pathname.startsWith(p) : pathname === p || pathname.startsWith(`${p}/`),
  )
}

/**
 * Wymusza blokujący onboarding po pierwszym zalogowaniu.
 *
 * Zasady:
 * - Działa dopiero po hydracji store (inaczej leci redirect w pierwszym
 *   renderze, gdy user=null, i tłumi normalny flow).
 * - Pomija /login, /onboarding, /share, /apply, /403.
 * - Redirectuje tylko role z `ONBOARDING_REQUIRED_ROLES` i tylko gdy
 *   `profile_completed=false`.
 *
 * Wywoływany z `AppShellV2`.
 */
export function useOnboardingGuard(): { needsOnboarding: boolean } {
  const router = useRouter()
  const pathname = usePathname()
  const user = useAuthStore((s) => s.user)
  const hydrated = useAuthStore((s) => s.hydrated)

  const needs = hydrated && requiresOnboarding(user)

  useEffect(() => {
    if (!hydrated) return
    if (!needs) return
    if (isExempt(pathname)) return
    router.replace("/onboarding")
  }, [hydrated, needs, pathname, router])

  return { needsOnboarding: needs }
}
