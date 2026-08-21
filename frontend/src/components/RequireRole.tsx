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
 *
 * „NIE WIEM JESZCZE" ≠ „NIE WOLNO". Przed `hydrate()` store ma `user === null`,
 * bo tożsamość leży w localStorage i jest czytana dopiero po montażu (SSR nie ma
 * do niej dostępu). W tym oknie NIE renderujemy `fallback`: dla wywołań
 * z domyślnym `fallback={null}` było to niewidoczne, ale wystarczyło podać
 * własny komunikat, żeby okno przed hydracją zaczęło TWIERDZIĆ, że użytkownik
 * nie ma uprawnień. Admin wchodzący na `/finance` widział „Brak uprawnień"
 * przez kilka sekund, zanim strona pokazała moduł — komunikat fałszywy i, co
 * gorsza, wskazujący winnego („poproś administratora"), gdy adresatem był sam
 * administrator. Dopóki nie wiemy, kim jest użytkownik, nie mówimy nic.
 */
interface Props {
  children: ReactNode
  roles?: UserRole[]
  minRole?: UserRole
  fallback?: ReactNode
  /** Co pokazać, dopóki tożsamość nie jest znana. Domyślnie nic. */
  pending?: ReactNode
}

export function RequireRole({
  children,
  roles,
  minRole,
  fallback = null,
  pending = null,
}: Props) {
  const user = useAuthStore((s) => s.user)
  const hydrated = useAuthStore((s) => s.hydrated)

  // Dozwolona tylko JEDNA strategia na raz — oba na raz = programmer error.
  if (roles && minRole) {
    if (process.env.NODE_ENV !== "production") {
      console.warn(
        "[RequireRole] Pass either `roles` OR `minRole`, not both. Using `roles`."
      )
    }
  }

  // Tożsamość nieznana — wstrzymujemy się od orzekania w którąkolwiek stronę.
  if (!hydrated) return <>{pending}</>

  const allowed = roles
    ? hasRole(user, ...roles)
    : minRole
      ? hasMinRole(user, minRole)
      : !!user // brak wymagań — wystarczy być zalogowanym

  if (!allowed) return <>{fallback}</>
  return <>{children}</>
}
