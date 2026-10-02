"use client"

import { ReactNode } from "react"

import { hasAnyPermission, type Permission } from "@/lib/permissions"
import { useAuthStore } from "@/store/auth"

/**
 * Bramka UI po UPRAWNIENIU z ekranu Ustawienia → Osoby i role (nie po roli).
 * Renderuje `children`, gdy konto ma którekolwiek z podanych uprawnień.
 *
 * To warstwa prezentacji — o dostępie decyduje backend, który przy odmowie
 * nazywa brakujące uprawnienie. Zakres klientów (portfel Delivery Leada)
 * sprawdza wołający, np. `canViewClientFinance(user, clientId)`.
 *
 * Przed `hydrate()` nie wiemy, kim jest użytkownik, więc nie pokazujemy
 * `fallback` — ta sama reguła co w `RequireRole`.
 */
interface Props {
  children: ReactNode
  /** Wystarczy jedno z wymienionych. */
  permissions: readonly Permission[]
  fallback?: ReactNode
  /** Co pokazać, dopóki tożsamość nie jest znana. Domyślnie nic. */
  pending?: ReactNode
}

export function RequirePermission({
  children,
  permissions,
  fallback = null,
  pending = null,
}: Props) {
  const user = useAuthStore((s) => s.user)
  const hydrated = useAuthStore((s) => s.hydrated)

  if (!hydrated) return <>{pending}</>
  if (!hasAnyPermission(user, ...permissions)) return <>{fallback}</>
  return <>{children}</>
}
