/**
 * Umiejętności na profilu kandydata — warianty tej samej nazwy łączone
 * WYŁĄCZNIE w widoku (decyzja 04.10.2026, D3). Dane w bazie, wyszukiwanie
 * i ocena dopasowania zostają bez zmian.
 *
 * Przegląd z 04.10.2026: profil z 45 umiejętnościami pokazywał osobno
 * „Kafka” i „Apache Kafka”, „Clean Code i SOLID” i „Clean Code / SOLID”,
 * „Spring Boot” i „Spring Boot / Spring Framework”. Łączymy:
 *
 * 1. przez słownik umiejętności (`GET /api/skills`: nazwa kanoniczna
 *    + aliasy) — nazwa albo KAŻDA jej część („A / B”) wskazuje tę samą
 *    umiejętność kanoniczną,
 * 2. bez słownika — po nazwie złożonej bez wielkości liter, polskich znaków,
 *    przedrostka „Apache” i z częściami w stałej kolejności („Clean Code
 *    i SOLID” = „SOLID / Clean Code”).
 *
 * Nazwy o różnych częściach („Spring Boot / Spring Framework” obok samego
 * „Spring Boot”) zostają osobno — lepiej pokazać dwa wpisy niż zgubić jeden.
 */

export interface SkillDictionaryEntry {
  name: string;
  aliases?: string[] | null;
}

export interface ProfileSkill {
  name?: string | null;
  level?: string | null;
  years?: number | null;
}

export interface DisplaySkill {
  /** Nazwa do pokazania: kanoniczna ze słownika albo pierwszy zapis z CV. */
  name: string;
  level: string | null;
  years: number | null;
  /** Wszystkie zapisy z profilu, które weszły w ten wpis (podpowiedź). */
  variants: string[];
  /** Potwierdzone na screeningu. */
  confirmed: boolean;
}

const LEVEL_RANK: Record<string, number> = {
  expert: 4,
  senior: 3,
  mid: 2,
  junior: 1,
};

/** Domyślna liczba umiejętności na wierzchu (reszta pod „Pokaż wszystkie”). */
export const TOP_SKILLS = 10;

export function foldSkillName(raw: string): string {
  return raw
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ł/g, "l")
    .replace(/Ł/g, "l")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

// Bez „+”: „C++” podzielone po plusie dawało część „c” i zlewało się z „C”.
// „HTML + CSS” zostaje wtedy jedną nazwą — lepiej dwa wpisy niż zgubiony.
const PART_SEPARATOR = /\s*(?:\/|&|,|\s(?:i|and|oraz)\s)\s*/;

function stripVendor(folded: string): string {
  return folded.replace(/^apache\s+/, "");
}

/** Części nazwy złożonej („Clean Code / SOLID” → ["clean code", "solid"]). */
export function skillNameParts(raw: string): string[] {
  return foldSkillName(raw)
    .split(PART_SEPARATOR)
    .map((part) => stripVendor(part.trim()))
    .filter(Boolean);
}

/** Indeks słownika: nazwa albo alias (złożony) → nazwa kanoniczna. */
export function skillDictionaryIndex(
  entries: SkillDictionaryEntry[] | null | undefined,
): Map<string, string> {
  const index = new Map<string, string>();
  for (const entry of entries ?? []) {
    if (!entry?.name) continue;
    for (const raw of [entry.name, ...(entry.aliases ?? [])]) {
      if (!raw) continue;
      const key = stripVendor(foldSkillName(raw));
      if (key && !index.has(key)) index.set(key, entry.name);
    }
  }
  return index;
}

function canonicalOf(raw: string, index: Map<string, string>): string | null {
  const whole = stripVendor(foldSkillName(raw));
  const direct = index.get(whole);
  if (direct) return direct;
  const parts = skillNameParts(raw);
  if (parts.length < 2) return null;
  const mapped = parts.map((part) => index.get(part) ?? null);
  if (mapped.some((value) => value == null)) return null;
  return mapped.every((value) => value === mapped[0]) ? mapped[0] : null;
}

function groupKey(raw: string, canonical: string | null): string {
  if (canonical) return `c:${foldSkillName(canonical)}`;
  return `n:${[...skillNameParts(raw)].sort().join("|")}`;
}

function higherLevel(a: string | null, b: string | null): string | null {
  if (!a) return b;
  if (!b) return a;
  return (LEVEL_RANK[b] ?? 0) > (LEVEL_RANK[a] ?? 0) ? b : a;
}

/**
 * Lista do pokazania: warianty złączone, najwyższy poziom i najdłuższy staż
 * z wariantów, umiejętności potwierdzone na screeningu (także spoza CV).
 * Kolejność: poziom, staż, potem kolejność z profilu.
 */
export function displaySkills(
  skills: ProfileSkill[] | null | undefined,
  options: {
    dictionary?: Map<string, string>;
    confirmed?: string[];
  } = {},
): DisplaySkill[] {
  const index = options.dictionary ?? new Map<string, string>();
  const confirmedKeys = new Set(
    (options.confirmed ?? []).map((name) => groupKey(name, canonicalOf(name, index))),
  );
  const groups = new Map<string, DisplaySkill & { order: number }>();
  let order = 0;
  const add = (raw: string, level: string | null, years: number | null) => {
    const name = raw.trim();
    if (!name) return;
    const canonical = canonicalOf(name, index);
    const key = groupKey(name, canonical);
    const existing = groups.get(key);
    if (existing) {
      existing.level = higherLevel(existing.level, level);
      existing.years =
        years != null && (existing.years == null || years > existing.years)
          ? years
          : existing.years;
      if (!existing.variants.includes(name)) existing.variants.push(name);
      return;
    }
    groups.set(key, {
      name: canonical ?? name,
      level,
      years,
      variants: [name],
      confirmed: confirmedKeys.has(key),
      order: order++,
    });
  };
  for (const skill of skills ?? []) {
    if (typeof skill?.name !== "string") continue;
    add(
      skill.name,
      skill.level ? String(skill.level) : null,
      typeof skill.years === "number" && Number.isFinite(skill.years) ? skill.years : null,
    );
  }
  // Potwierdzone na screeningu, których CV nie ma — nie mogą zniknąć tylko
  // dlatego, że CV ich nie wymienia.
  for (const name of options.confirmed ?? []) {
    const key = groupKey(name, canonicalOf(name, index));
    if (!groups.has(key)) add(name, null, null);
    const group = groups.get(key);
    if (group) group.confirmed = true;
  }
  return [...groups.values()]
    .sort((a, b) => {
      const level = (LEVEL_RANK[b.level ?? ""] ?? 0) - (LEVEL_RANK[a.level ?? ""] ?? 0);
      if (level !== 0) return level;
      const years = (b.years ?? 0) - (a.years ?? 0);
      if (years !== 0) return years;
      return a.order - b.order;
    })
    .map(({ order: _order, ...skill }) => skill);
}
