/**
 * „Obowiązki” Profilu Championa jako lista z obszarami.
 *
 * Od 07.11.2026 odczyt requestu (prompt v15) zapisuje każdy obowiązek osobnym
 * punktem („- …”), a obszary jako linie z dwukropkiem. Starsze profile mają
 * jedno zdanie albo linie rozdzielone średnikami — te tną się jak dotąd.
 */

export interface ResponsibilityGroup {
  title: string | null;
  items: string[];
}

const POINT = /^\s*(?:[-–—•*·▪●]|\d+[.)])\s*/;

export function responsibilityGroups(text: string): ResponsibilityGroup[] {
  const lines = text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (!lines.some((line) => POINT.test(line))) {
    const items = text
      .split(/\n|;/)
      .map((line) => line.trim())
      .filter(Boolean);
    return items.length > 0 ? [{ title: null, items }] : [];
  }
  const groups: ResponsibilityGroup[] = [];
  for (const line of lines) {
    if (POINT.test(line)) {
      const item = line.replace(POINT, "").trim();
      if (!item) continue;
      if (groups.length === 0) groups.push({ title: null, items: [] });
      groups[groups.length - 1].items.push(item);
    } else {
      groups.push({ title: line.replace(/:\s*$/, ""), items: [] });
    }
  }
  return groups.filter((group) => group.items.length > 0);
}

export function responsibilityCount(groups: ResponsibilityGroup[]): number {
  return groups.reduce((sum, group) => sum + group.items.length, 0);
}

/** Wysokość pola „Obowiązki”: tyle wierszy, ile linii, od 2 do 14. */
export function responsibilityRows(text: string): number {
  const lines = text.split("\n").length;
  return Math.min(14, Math.max(2, text.trim() ? lines : 2));
}
