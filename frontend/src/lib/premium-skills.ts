// Czyste reguły sekcji „Technologie premium” (F3, 15.11.2026) — testowane osobno.
import type { ClaimStatus, PremiumClaim, PremiumEvidence } from "@/lib/api/framework-rates";

export const CLAIM_LABEL: Record<ClaimStatus, string> = {
  approved: "Zatwierdzony przez DL",
  sent: "Wysłany do klienta",
  granted: "Przyznana",
  refused: "Odmowa klienta",
  dropped: "Wycofany",
};

export const OPEN_CLAIMS: ClaimStatus[] = ["approved", "sent"];

/** Otwarty wniosek dla technologii (jeden na raz). */
export function openClaimFor(claims: PremiumClaim[], technology: string): PremiumClaim | null {
  const wanted = technology.toLocaleLowerCase("pl");
  return claims.find((c) => OPEN_CLAIMS.includes(c.status) && c.technology.toLocaleLowerCase("pl") === wanted) ?? null;
}

/** Ostatnia odmowa klienta dla technologii — przypomnienie przy kolejnej prolongacji. */
export function lastRefusal(claims: PremiumClaim[], technology: string): PremiumClaim | null {
  const wanted = technology.toLocaleLowerCase("pl");
  return claims.find((c) => c.status === "refused" && c.technology.toLocaleLowerCase("pl") === wanted) ?? null;
}

/** Krótki opis propozycji NEXUSA. */
export function proposalLabel(e: PremiumEvidence): string {
  if (e.uses && e.knows) return "zna i korzysta";
  if (e.uses) return "korzysta";
  return "zna, brak dowodu użycia";
}

/** Przyznana dopłata dla technologii (zamknięty wniosek ze zgodą klienta). */
export function grantedClaim(claims: PremiumClaim[], technology: string): PremiumClaim | null {
  const wanted = technology.toLocaleLowerCase("pl");
  return claims.find((c) => c.status === "granted" && c.technology.toLocaleLowerCase("pl") === wanted) ?? null;
}

/**
 * Umowa daje jedną dopłatę — wyższą. Gdy przyznano już dopłatę co najmniej
 * tak wysoką, wniosek o inną technologię nic nie zmieni (zwraca przyznaną).
 */
export function coveredBy(
  claims: PremiumClaim[],
  evidence: PremiumEvidence[],
  technology: string,
): PremiumClaim | null {
  const percentOf = (tech: string) =>
    Number(evidence.find((e) => e.technology.toLocaleLowerCase("pl") === tech.toLocaleLowerCase("pl"))?.percent ?? 0);
  const own = percentOf(technology);
  return (
    claims.find(
      (c) =>
        c.status === "granted" &&
        c.technology.toLocaleLowerCase("pl") !== technology.toLocaleLowerCase("pl") &&
        percentOf(c.technology) >= own,
    ) ?? null
  );
}
