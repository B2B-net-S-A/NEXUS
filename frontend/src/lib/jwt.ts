/**
 * Decode & inspect JWTs on the client WITHOUT verifying the signature.
 *
 * Dlaczego bez weryfikacji: podpis jest weryfikowany przy KAŻDYM wywołaniu API
 * po stronie backendu (backend/app/api/deps.py::get_current_user). Na kliencie
 * dekodujemy sam payload wyłącznie na potrzeby UX-guardów: routingu (`role`)
 * oraz świeżości sesji (`exp`).
 *
 * Moduł jest PURE — zero `window`/`document`/API Node — więc bezpiecznie
 * importuje się go zarówno z edge middleware Next.js, jak i z komponentów
 * klienckich. Jedna kopia base64url-decode = brak dryfu między tymi miejscami.
 */
import type { ProductSection, SectionAccess } from "@/lib/section-access";

export interface JwtPayload {
  role?: string;
  roles?: string[];
  exp?: number;
  fpc?: boolean;
  /** Podpisany snapshot dostępu do sekcji używany przez edge middleware. */
  sa?: Partial<Record<ProductSection, SectionAccess>>;
}

/** Decode the JWT payload segment, or `null` when the token is malformed. */
export function decodeJwtPayload(token: string): JwtPayload | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    // base64url → base64, a następnie dopełnienie do wielokrotności 4.
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    return JSON.parse(atob(padded)) as JwtPayload;
  } catch {
    return null;
  }
}

/**
 * True gdy token jest bezużyteczny czasowo: brak claim `exp` albo `exp` wypada
 * w/przed teraz. Granica (`>=`) lustrzana do backendowej definicji wygaśnięcia.
 */
export function isJwtExpired(exp: number | undefined): boolean {
  if (!exp) return true;
  return Date.now() / 1000 >= exp;
}
