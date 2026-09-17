/**
 * Parse a comma/newline-separated tag input into a clean list: trimmed,
 * case-insensitively de-duplicated, capped at the backend's 20-tag limit.
 *
 * Wyniesione z `CandidateSearchView` (gdzie żyło jako funkcja lokalna, wciąż
 * re-eksportowana stamtąd dla wstecznej zgodności) do wspólnego modułu —
 * `CreateJobModal` (must-have) potrzebuje TEJ SAMEJ logiki bez duplikowania
 * parsera przecinków/nowych linii.
 */
export function parseTagInput(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of raw.split(/[,\n]/)) {
    const tag = part.trim();
    if (!tag) continue;
    const key = tag.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(tag);
    if (out.length >= 20) break;
  }
  return out;
}
