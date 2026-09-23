/**
 * Sekcja 4 Profilu Championa — „Doświadczenie poza stackiem” (09.2026).
 *
 * Dziedzina (np. płatności), certyfikaty i regulacje NIE są technologiami —
 * do 09.2026 lądowały w stacku, gdzie scoring czytał je jak skille. Tu żyją
 * etykiety i podpowiedzi; wpisać można dowolną nazwę, lista to tylko skrót.
 *
 * Plakietka w wynikach (`breakdown.experience` z `/api/search/candidates/scores`)
 * mówi „jest ślad w CV” albo „brak danych” — nigdy „nie ma”, bo branża w CV
 * bywa pusta (decyzja 23.09.2026: plakietka + ranking fraz, bez bramki).
 */

import type {
  ChampionExperience,
  ExperienceItem,
  ExperienceKind,
  ExperienceLevel,
} from "@/lib/api";

export const EXPERIENCE_KINDS: readonly ExperienceKind[] = [
  "domains",
  "certifications",
  "regulations",
];

export const EXPERIENCE_KIND_LABEL: Record<ExperienceKind, string> = {
  domains: "Dziedzina",
  certifications: "Certyfikaty",
  regulations: "Regulacje i standardy",
};

export const EXPERIENCE_KIND_HINT: Record<ExperienceKind, string> = {
  domains: "W czym kandydat pracował — np. płatności, ubezpieczenia. Nie technologia.",
  certifications: "Np. ISTQB Foundation, AWS Solutions Architect, PSM I.",
  regulations: "Np. PSD2, PCI DSS, RODO, KNF, ISO 27001.",
};

export const EXPERIENCE_LEVEL_LABEL: Record<ExperienceLevel, string> = {
  must: "Musi",
  nice: "Mile",
};

/** Podpowiedzi (`datalist`) — skrót, nie słownik zamknięty. */
export const EXPERIENCE_SUGGESTIONS: Record<ExperienceKind, readonly string[]> = {
  domains: [
    "płatności",
    "karty płatnicze",
    "bankowość detaliczna",
    "bankowość korporacyjna",
    "kredyty",
    "ubezpieczenia",
    "telekomunikacja",
    "e-commerce",
    "sektor publiczny",
    "e-zdrowie",
    "energetyka",
    "logistyka",
    "fintech",
    "automotive",
  ],
  certifications: [
    "ISTQB Foundation",
    "ISTQB Advanced",
    "AWS Solutions Architect",
    "Azure Administrator",
    "PSM I",
    "PMP",
    "PRINCE2",
    "CKA",
    "CISSP",
  ],
  regulations: ["PSD2", "PCI DSS", "RODO", "KNF", "ISO 27001", "DORA", "SWIFT", "SEPA"],
};

export function experienceItemLabel(kind: ExperienceKind, item: ExperienceItem): string {
  const years =
    kind === "domains" && typeof item.min_years === "number" && item.min_years > 0
      ? ` · min. ${item.min_years} ${item.min_years === 1 ? "rok" : item.min_years < 5 ? "lata" : "lat"}`
      : "";
  return `${item.name}${years}`;
}

export function hasExperience(experience: ChampionExperience | null | undefined): boolean {
  return Boolean(
    experience &&
      EXPERIENCE_KINDS.some((kind) => (experience[kind] ?? []).length > 0),
  );
}

/** Dodaje pozycje z tekstu (przecinki, średniki, nowe linie), bez duplikatów. */
export function addExperienceItems(
  items: readonly ExperienceItem[],
  raw: string,
  level: ExperienceLevel = "must",
): ExperienceItem[] {
  const next = [...items];
  for (const part of raw.split(/[,;\n]/)) {
    const name = part.trim().replace(/\s+/g, " ");
    if (!name) continue;
    if (next.some((i) => i.name.toLowerCase() === name.toLowerCase())) continue;
    next.push({ name: name.slice(0, 160), level, min_years: null, note: "" });
  }
  return next;
}

/** Plakietka z `/api/search/candidates/scores` (`breakdown.experience`). */
export interface ExperienceEvidence {
  kind: ExperienceKind;
  name: string;
  level: ExperienceLevel;
  min_years?: number | null;
  status: "met" | "unknown";
  source?: string | null;
}

export function readExperienceEvidence(breakdown: unknown): ExperienceEvidence[] {
  if (!breakdown || typeof breakdown !== "object") return [];
  const raw = (breakdown as { experience?: unknown }).experience;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (e): e is ExperienceEvidence =>
      !!e &&
      typeof e === "object" &&
      typeof (e as ExperienceEvidence).name === "string" &&
      ((e as ExperienceEvidence).status === "met" ||
        (e as ExperienceEvidence).status === "unknown"),
  );
}

/**
 * Pozycje sekcji 4 jako tekst — okno „Uzgodnij profil i pola rekrutacji”
 * pracuje na polach tekstowych. „(min. N lat)” i „(mile)” to ta sama
 * gramatyka, którą serwer czyta z komórki wzoru Word v5
 * (`champion_document.experience_from_text`), więc przejście przez okno nie
 * gubi poziomu ani lat. Lustro w teście backendu
 * (`test_champion_rate_retention_flows._experience_line`).
 */
export function experienceToText(items: readonly ExperienceItem[] | undefined): string {
  return (items ?? [])
    .map((item) => {
      let line = item.name;
      if (item.min_years) line += ` (min. ${item.min_years} lat)`;
      if (item.level === "nice") line += " (mile)";
      return line;
    })
    .join("\n");
}
