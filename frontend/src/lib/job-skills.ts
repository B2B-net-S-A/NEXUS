/**
 * Wyciąga listę nazw skilli z `Job.must_skills` / `Job.nice_skills` — pole
 * JSONB o niejednoznacznym kształcie (lista stringów, lista obiektów
 * `{name}`, albo stary kształt `{technologies: [...]}`).
 *
 * Wyniesione z `JobsListV2` (gdzie żyło jako funkcja lokalna) do wspólnego
 * modułu — `JobReadinessDock` potrzebuje TEJ SAMEJ logiki do liczenia
 * „N must · M nice” w checkliście gotowości, bez duplikowania rozgałęzień
 * kształtu.
 */
export function extractSkills(must: unknown): string[] {
  if (!must) return [];
  if (Array.isArray(must)) {
    return must
      .map((x) => (typeof x === "string" ? x : ((x as any)?.name ?? null)))
      .filter(Boolean) as string[];
  }
  if (typeof must === "object" && (must as any).technologies) {
    return Array.isArray((must as any).technologies)
      ? (must as any).technologies
      : [];
  }
  return [];
}
