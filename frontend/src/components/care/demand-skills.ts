/**
 * Technologie działu, które padły w rolach sygnału popytu (makieta R4,
 * 22.10.2026): okno „Rozmowa z menedżerem” zaznacza je od razu, reszta mapy
 * działu czeka na klik. Porównanie bez wielkości liter, po całej nazwie albo po
 * jej pierwszym słowie jako osobnym słowie roli — „Java 17” pasuje do „Java
 * Developer (Kafka)”, ale „Java” nie pasuje do „JavaScript”.
 */

const SPLIT = /[\s,;:()[\]/|]+/;

function tokens(text: string): string[] {
  return text
    .toLocaleLowerCase("pl")
    .split(SPLIT)
    .map((part) => part.trim())
    .filter(Boolean);
}

export function skillsMentionedIn(
  roles: readonly string[],
  skills: readonly { id: number; name: string }[],
): number[] {
  const roleTokens = new Set(roles.flatMap(tokens));
  if (roleTokens.size === 0) return [];
  const roleText = ` ${[...roles].join(" ").toLocaleLowerCase("pl")} `;
  return skills
    .filter((skill) => {
      const name = skill.name.trim().toLocaleLowerCase("pl");
      if (!name) return false;
      if (name.includes(" ") && roleText.includes(` ${name} `)) return true;
      const first = tokens(name)[0];
      return Boolean(first) && first.length >= 2 && roleTokens.has(first);
    })
    .map((skill) => skill.id);
}
