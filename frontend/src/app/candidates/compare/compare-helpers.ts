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
