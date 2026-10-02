import {
  PERMISSION_KEYS,
  closePermissions,
  deriveSections,
  type Permission,
} from "@/lib/permissions";

/**
 * `effective_action_access` w kształcie z `GET /api/auth/me`: komplet
 * dziewięciu kluczy (nadane razem z tymi, które z nich wynikają) plus
 * generator umów B2B.
 *
 * Komplet jest istotny: profil bez klucza `delivery_view` front traktuje jak
 * zapisany przed wdrożeniem uprawnień i liczy z domyślnych ról — test osoby
 * z WYŁĄCZONYM uprawnieniem przechodziłby wtedy mimo zepsutej bramki.
 */
export function permissionSnapshot(
  ...granted: Permission[]
): Record<Permission | "b2b_contract_generator", "none" | "manage"> {
  const held = closePermissions(granted);
  return {
    b2b_contract_generator: "manage",
    ...Object.fromEntries(
      PERMISSION_KEYS.map((key) => [key, held.has(key) ? "manage" : "none"]),
    ),
  } as Record<Permission | "b2b_contract_generator", "none" | "manage">;
}

/**
 * Sekcje Delivery i Finanse wynikają z uprawnień — backend zwraca je razem
 * z uprawnieniami. Pozostałe sekcje podaje test (`extra`).
 */
export function sectionSnapshot(
  granted: readonly Permission[],
  extra: Partial<
    Record<
      "sourcing" | "pipeline" | "insights" | "system_admin",
      "none" | "read" | "write"
    >
  > = {},
): Record<
  "sourcing" | "pipeline" | "delivery" | "insights" | "finance" | "system_admin",
  "none" | "read" | "write"
> {
  const derived = deriveSections(closePermissions(granted));
  return {
    sourcing: "none",
    pipeline: "none",
    insights: "none",
    system_admin: "none",
    ...extra,
    delivery: derived.delivery,
    finance: derived.finance,
  };
}
