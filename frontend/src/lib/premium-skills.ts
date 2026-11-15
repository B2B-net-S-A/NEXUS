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
