import type { ProcedureHeading } from "@/components/v2/ProcedureTableOfContents";

/**
 * Slug nagłówka procedury — podstawa `id` kotwicy w treści Markdown.
 *
 * `ł`/`Ł` transliterujemy RĘCZNIE. Normalizacja NFKD rozkłada „ą" na „a" +
 * ogonek, ale „ł" jest osobnym znakiem bazowym i nie ma z czego zdjąć znaku
 * diakrytycznego — bez tej pary „Wgrywanie pliku" i „Wgrywanie płiku"
 * dostałyby ten sam slug, a „Główne" zamieniłoby się w „g-wne".
 */
export function slugifyHeading(text: string): string {
  const transliterated = text.replace(/ł/g, "l").replace(/Ł/g, "L");
  const ascii = transliterated
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
  const slug = ascii.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return slug || "sekcja";
}

/**
 * Nadaje `id` nagłówkom w wyrenderowanej treści i zwraca ich listę.
 *
 * Czyta DOM, a nie Markdown — patrz komentarz w `ProcedureTableOfContents`.
 * Idempotentna: wywołana ponownie na tym samym drzewie nada te same `id`,
 * więc link skopiowany przez użytkownika nie przestaje działać po odświeżeniu
 * widoku (react-query refetchuje procedurę w tle).
 *
 * Duplikaty tytułów są realne — każda sekcja klienta ma podnagłówek „Co robi
 * system automatycznie". Bez licznika wszystkie dostałyby ten sam `id`,
 * a `getElementById` zwracałby zawsze pierwszy: każdy taki punkt spisu treści
 * skakałby do pierwszego klienta.
 */
export function assignHeadingIds(root: HTMLElement): ProcedureHeading[] {
  const seen = new Map<string, number>();
  const headings: ProcedureHeading[] = [];

  root.querySelectorAll<HTMLHeadingElement>("h2, h3").forEach((element) => {
    const text = (element.textContent ?? "").trim();
    if (!text) return;

    const base = slugifyHeading(text);
    const usedBefore = seen.get(base) ?? 0;
    seen.set(base, usedBefore + 1);
    const id = usedBefore === 0 ? base : `${base}-${usedBefore + 1}`;

    element.id = id;
    // Offset pod nagłówek sekcji: bez tego `scrollIntoView` ustawia nagłówek
    // dokładnie przy górnej krawędzi okna i pierwsza linijka wchodzi pod
    // przyklejony pasek.
    element.classList.add("scroll-mt-24");
    headings.push({ id, text, level: element.tagName === "H2" ? 2 : 3 });
  });

  return headings;
}
