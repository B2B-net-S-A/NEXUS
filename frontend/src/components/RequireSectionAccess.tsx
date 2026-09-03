"use client";

import type { ReactNode } from "react";

import {
  hasSectionAccess,
  type ProductSection,
  type SectionAccess,
} from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";

interface Props {
  children: ReactNode;
  section: ProductSection;
  required?: Exclude<SectionAccess, "none">;
  fallback?: ReactNode;
  pending?: ReactNode;
}
/**
 * UI-level gate for the database-backed product-section policy.
 *
 * This mirrors the signed JWT/middleware decision for rendering only. Backend
 * dependencies independently resolve the current database policy and remain
 * the authorization authority.
 */
export function RequireSectionAccess({
  children,
  section,
  required = "read",
  fallback = null,
  pending = null,
}: Props) {
  const user = useAuthStore((state) => state.user);
  const hydrated = useAuthStore((state) => state.hydrated);

  if (!hydrated) return <>{pending}</>;
  if (!hasSectionAccess(user, section, required)) return <>{fallback}</>;
  return <>{children}</>;
}
