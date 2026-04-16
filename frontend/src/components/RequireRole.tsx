"use client"

import { ReactNode } from "react"

import { UserRole, hasMinRole, hasRole, useAuthStore } from "@/store/auth"

/**
 * UI-level role gate. Renderuje `children` tylko jeśli zalogowany user spełnia
 * wymaganie roli. To jest *cosmetic gating* — nie zastępuje middleware
 * (route-level) ani guardów backendu (API-level). Defense in depth.
 *
 * Dwa tryby:
 *   <RequireRole roles={["admin", "delivery_lead"]}>  — exact match z listy
 *   <RequireRole minRole="tac">                       — hierarchiczne >= tac
 *
 * Użyj `fallback` aby wyświetlić komunikat zamiast niczego (np. tooltip-like).
 */
interface Props {
  children: ReactNode
  roles?: UserRole[]
  minRole?: UserRole
  fallback?: ReactNode
}

export function RequireRole({ children, roles, minRole, fallback = null }: Props) {
  const user = useAuthStore((s) => s.user)

  // Dozwolona tylko JEDNA strategia na raz — oba na raz = programmer error.
  if (roles && minRole) {
    if (process.env.NODE_ENV !== "production") {
      console.warn(
        "[RequireRole] Pass either `roles` OR `minRole`, not both. Using `roles`."
      )
    }
  }

  const allowed = roles
    ? hasRole(user, ...roles)
    : minRole
      ? hasMinRole(user, minRole)
      : !!user // brak wymagań — wystarczy być zalogowanym

  if (!allowed) return <>{fallback}</>
  return <>{children}</>
}
