/**
 * Kto dostaje panel „Czy te rekrutacje nadal trwają?” (26.11.2026) — lustro
 * bramki `GET /api/hold-checks`: Delivery Lead widzi swoje rekrutacje,
 * Head of Recruitment i administrator (bez roli DL) — wszystkie (`?all=true`).
 */

import { hasRole, type RoleBearingUser } from "@/store/auth";

export function holdChecksAudience(user: RoleBearingUser | null | undefined): {
  enabled: boolean;
  all: boolean;
} {
  const dl = hasRole(user, "delivery_lead");
  const wide = hasRole(user, "head_of_recruitment", "admin");
  return { enabled: dl || wide, all: wide && !dl };
}
