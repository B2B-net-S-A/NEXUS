/** Czyste pomocniki porównania kandydatów (UAT M01-B04).
 *
 *  Ekran porównania nie liczy dopasowania do rekrutacji — pokazuje profile
 *  obok siebie. Dawny pierścień „N/100” z podpisem „Profil kompletny” i paski
 *  umiejętności z domyślnym 60% wyglądały jak ocena dopasowania, choć były
 *  heurystyką wypełnienia pól i stałą. Tu zostaje to, co naprawdę wiemy. */

/** Kompletność profilu 0–100: udział wypełnionych pól, nie dopasowanie. */
export function profileCompleteness(c: Record<string, unknown>): number {
  let score = 0;
  const fields = [
    c.name,
    c.lastname,
    c.email,
    c.phone,
    c.location,
    c.competence_category,
    c.ai_summary,
  ];
  score += fields.filter(Boolean).length * 5;
  if (Array.isArray(c.skills) && c.skills.length > 0)
    score += Math.min(c.skills.length * 3, 30);
  if (Array.isArray(c.experience) && c.experience.length > 0)
    score += Math.min(c.experience.length * 5, 20);
  if (Array.isArray(c.languages) && c.languages.length > 0) score += 5;
  if (c.linkedin) score += 5;
  return Math.min(score, 100);
}

const SKILL_LEVEL_LABELS: Record<string, string> = {
  expert: "Ekspert",
  advanced: "Zaawansowany",
  senior: "Senior",
  mid: "Mid",
  intermediate: "Średniozaawansowany",
  junior: "Junior",
  beginner: "Początkujący",
  basic: "Podstawowy",
};

/** Poziom umiejętności tak, jak jest zapisany — bez zmyślonego procentu.
 *  Brak poziomu to pusty napis, nie „60%”. */
export function skillLevelLabel(level: unknown): string {
  if (typeof level === "number" && Number.isFinite(level)) return `${level}/10`;
  if (typeof level !== "string") return "";
  const key = level.trim().toLowerCase();
  return SKILL_LEVEL_LABELS[key] ?? level.trim();
}

/** Skąd porównanie wie o umiejętności: z listy umiejętności profilu albo
 *  z „Zweryfikowanych technologii” (profil pokazuje je jako „potwierdzone na
 *  screeningu”). */
export type CandidateSkillSource = "skills" | "verified";

function skillName(value: unknown): string | null {
  if (typeof value === "string") return value.trim() || null;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const name = record.name ?? record.tech ?? record.skill;
    return typeof name === "string" && name.trim() ? name.trim() : null;
  }
  return null;
}

/** Umiejętności kandydata do porównania z wymaganiami rekrutacji — klucz bez
 *  wielkości liter, wartość = źródło (umiejętność z listy wygrywa).
 *
 *  Runda 10 (F18): porównanie czytało wyłącznie `skills`, a profil pokazuje
 *  w sekcji „Umiejętności” także `verified_tech` (tak samo liczy filtr
 *  „Umiejętności” na liście). Python dopisany jako zweryfikowana technologia
 *  był na profilu „potwierdzony na screeningu”, a w porównaniu — „brak”. */
export function candidateSkillSources(candidate: {
  skills?: unknown;
  verified_tech?: unknown;
}): Map<string, CandidateSkillSource> {
  const out = new Map<string, CandidateSkillSource>();
  const skills: unknown[] = Array.isArray(candidate?.skills) ? candidate.skills : [];
  for (const item of skills) {
    const name = skillName(item);
    if (name) out.set(name.toLowerCase(), "skills");
  }
  const verified: unknown[] = Array.isArray(candidate?.verified_tech)
    ? candidate.verified_tech
    : [];
  for (const item of verified) {
    const name = skillName(item);
    if (name && !out.has(name.toLowerCase())) out.set(name.toLowerCase(), "verified");
  }
  return out;
}

/** Zweryfikowane technologie spoza listy umiejętności — w oryginalnym zapisie. */
export function verifiedOnlySkills(candidate: {
  skills?: unknown;
  verified_tech?: unknown;
}): string[] {
  return [...candidateSkillSources(candidate)]
    .filter(([, source]) => source === "verified")
    .map(([key]) => {
      const verified: unknown[] = Array.isArray(candidate?.verified_tech)
        ? candidate.verified_tech
        : [];
      const original = verified
        .map(skillName)
        .find((name) => name !== null && name.toLowerCase() === key);
      return original ?? key;
    });
}
