/**
 * Podgląd szablonu email: zmienne `{{…}}` jako opisane etykiety (UAT B14).
 *
 * Przykładowe dane (fikcyjne stanowisko, stawka, rekruter) usunięto celowo —
 * wyglądały jak prawdziwe (UAT M11-B06). Surowe `{{job_title}}` w tekście też
 * nie mówiło, co się tam pojawi. Etykieta pokazuje znaczenie zmiennej, a nie
 * zmyśloną wartość.
 */
export type TemplatePart =
  | { kind: "text"; value: string }
  | { kind: "variable"; token: string; label: string | null };

const VARIABLE = /\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}/g;

export function splitTemplateVariables(
  text: string | null | undefined,
  labels: ReadonlyMap<string, string>,
): TemplatePart[] {
  const source = text ?? "";
  const parts: TemplatePart[] = [];
  let last = 0;
  for (const match of source.matchAll(VARIABLE)) {
    const index = match.index ?? 0;
    if (index > last) parts.push({ kind: "text", value: source.slice(last, index) });
    const token = `{{${match[1]}}}`;
    parts.push({ kind: "variable", token, label: labels.get(token) ?? null });
    last = index + match[0].length;
  }
  if (last < source.length) parts.push({ kind: "text", value: source.slice(last) });
  return parts;
}
