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

// --- F4: szkic uzasadnienia dla klienta (EN), tylko z faktów NEXUSA -----------------

const SOURCE_EN: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^CV$/, () => "listed in the consultant's CV"],
  [
    /^oś czasu CV(?:: (\d+) mies\.)?(, obecnie)?$/,
    (m) =>
      `${m[1] ? `${m[1]} months of hands-on use` : "hands-on use"} in the consultant's career timeline${m[2] ? ", ongoing on the current assignment" : ""}`,
  ],
  [/^zweryfikowane na screeningu$/, () => "verified in our technical screening"],
  [/^karta techniczna projektu \(opieka\)$/, () => "part of the project's technology stack confirmed in our regular account review"],
];

function sourceEn(source: string): string {
  for (const [pattern, render] of SOURCE_EN) {
    const m = source.match(pattern);
    if (m) return render(m);
  }
  return source;
}

/**
 * Szkic uzasadnienia prośby o dopłatę (po angielsku). Składa wyłącznie fakty:
 * źródła dowodu, kategorię z umowy i przykłady wpisane przez DL. Zdań bez
 * dowodu nie dopisuje — DL poprawia tekst przed wysłaniem.
 */
export function justificationDraft(input: {
  technology: string;
  percent: string;
  category: string | null;
  sources: string[];
  dlNote: string | null;
}): string {
  const evidence = input.sources.map(sourceEn).join("; ");
  const parts = [
    `${input.technology} is part of the consultant's daily work on this assignment, not an occasional or supporting skill.`,
    evidence ? `Evidence: ${evidence}.` : "",
    input.dlNote?.trim() ? `Examples from the project: ${input.dlNote.trim()}` : "",
    input.category
      ? `The assignment is delivered in the ${input.category} competence category, for which the Framework Agreement provides a ${Number(input.percent)}% Premium Technology Price Adder for ${input.technology}.`
      : `The Framework Agreement provides a ${Number(input.percent)}% Premium Technology Price Adder for ${input.technology}.`,
    `We kindly ask to include ${input.technology} in the "Description of knowledge and experience" of the request and to apply the adder.`,
  ];
  return parts.filter(Boolean).join(" ");
}
