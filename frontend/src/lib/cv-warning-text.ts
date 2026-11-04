/**
 * Uwaga generatora CV po ludzku — jedno zdanie po polsku, co sprawdzić
 * (18.10.2026).
 *
 * Generator pisze uwagi w języku CV i z kluczami pól („NOT IN SOURCE: '32 year'
 * (why_points) follows neither…”), więc rekruter przy CV po angielsku czytał
 * w edytorze surowy angielski komunikat strażnika. Tu zmienia się tylko to,
 * co widać: surowy tekst zostaje kluczem pominięcia („To nieprawda”, „OK”)
 * i podstawą klasyfikacji (`classifyCvWarnings`), wynik QC się nie zmienia.
 *
 * Wzorce MUSZĄ odpowiadać szablonom w
 * `backend/app/services/cv_generator_b2b/standalone_service.py`
 * (`_fabrication_warnings`, `_free_text_warnings`, `_date_overlap_warnings`),
 * `legacy_v7/_helpers.py` (te same szablony) i `final_review.py`
 * (`review_warnings`). Uwaga, której żaden wzorzec nie zna, zostaje bez zmian.
 */

const HIGH = "(?:NOT IN SOURCE|BRAK POKRYCIA)";
const SOFT = "(?:VERIFY|WERYFIKUJ)";

/** Pole `why_points` to w CV sekcja „Dlaczego nasz kandydat”; inne etykiety to stanowisko. */
function where(label: string): string {
  if (label === "why_points") return "w sekcji „Dlaczego nasz kandydat”";
  return `w stanowisku „${label}”`;
}

const REVIEW_FIELD_PL: Record<string, string> = {
  summary: "podsumowanie",
  experience: "doświadczenie",
  certifications: "certyfikaty",
  skills: "umiejętności",
  languages: "języki",
  education: "edukacja",
  "full name": "imię i nazwisko",
  "first name": "imię",
  position: "stanowisko",
  "candidate data": "dane kandydata",
};

const REVIEW_REASON_PL: Record<string, string> = {
  "not confirmed in the CV or notes": "brak potwierdzenia w CV i notatkach",
  "contradicts the source": "sprzeczne ze źródłem",
  "the reviewer gave no valid citation": "recenzent nie wskazał poprawnego cytatu",
  "content from private notes / recruiter assessment": "treść z notatek prywatnych / ocen rekrutera",
  "almost the same is in the sources — check the wording": "w źródłach jest prawie to samo — sprawdź brzmienie",
};

const CHECK_BY_HAND = "przeczytaj CV obok oryginału, zanim je wyślesz.";

type Rule = { pattern: RegExp; text: (m: RegExpMatchArray) => string };

const RULES: readonly Rule[] = [
  {
    pattern: new RegExp(
      `^${HIGH}: '(.+?)' \\((.+?)\\) (?:follows neither from the source nor from the dates|nie wynika ani ze źródła, ani z dat)`,
    ),
    text: (m) =>
      `Sprawdź „${m[1]}” ${where(m[2])}: tej liczby lat nie ma w oryginale i nie wynika ona z dat stanowisk.`,
  },
  {
    pattern: new RegExp(
      `^${HIGH}: (?:figure|liczba) '(.+?)' \\((.+?)\\) (?:does not appear in the CV or notes|nie występuje w CV ani notatkach)`,
    ),
    text: (m) => `Sprawdź liczbę „${m[1]}” ${where(m[2])}: nie ma jej w oryginale CV ani w notatkach.`,
  },
  {
    pattern: new RegExp(
      `^${SOFT}: (?:scale claim|rozdmuchanie skali) '(.+?)' \\((.+?)\\) (?:has no basis in the source|bez pokrycia w źródle)`,
    ),
    text: (m) => `Sprawdź określenie „${m[1]}” ${where(m[2])}: oryginał nie mówi o takiej skali.`,
  },
  {
    pattern: /^VERIFY: the independent AI review did not confirm the document \((.+?)\)/,
    text: () => `Kontrola AI nie dała czytelnego wyniku — ${CHECK_BY_HAND}`,
  },
  {
    pattern: /^WERYFIKUJ: niezależna kontrola AI treści CV nie potwierdziła dokumentu \((.+?)\)/,
    text: () => `Kontrola AI nie dała czytelnego wyniku — ${CHECK_BY_HAND}`,
  },
  {
    pattern: /^VERIFY: the independent AI review did not run \((.+?)\)/,
    text: () => `Kontrola AI się nie wykonała — ${CHECK_BY_HAND}`,
  },
  {
    pattern: /^(NOT IN SOURCE|VERIFY) \(AI review\): (.+?) —(?: "(.*)")? \((.+)\)$/,
    text: (m) => {
      const field = REVIEW_FIELD_PL[m[2]] ?? m[2];
      const quote = m[3] ? ` „${m[3]}”` : "";
      const reason = REVIEW_REASON_PL[m[4]] ?? m[4];
      return `Kontrola AI: ${field} —${quote} (${reason}).`;
    },
  },
  {
    pattern: /^VERIFY: technology '(.+?)' \((.+?)\) not found in the CV or notes/,
    text: (m) => `Sprawdź technologię „${m[1]}” w stanowisku „${m[2]}”: nie ma jej w CV ani w notatkach.`,
  },
  {
    pattern: /^VERIFY: certification '(.+?)' not found in the CV or notes/,
    text: (m) => `Sprawdź certyfikat „${m[1]}”: nie ma go w CV ani w notatkach.`,
  },
  {
    pattern: /^VERIFY: skill '(.+?)' \((.+?)\) not found in the CV or notes/,
    text: (m) => `Sprawdź umiejętność „${m[1]}” (${m[2]}): nie ma jej w CV ani w notatkach.`,
  },
  {
    pattern: /^VERIFY: overlapping employment periods: '(.+?)' \((.*?)\) and '(.+?)' \((.*?)\)$/,
    text: (m) => `Nakładające się okresy zatrudnienia: „${m[1]}” (${m[2]}) i „${m[3]}” (${m[4]}).`,
  },
  {
    pattern: /^… and (\d+) more overlapping pairs/,
    text: (m) => `… i ${m[1]} kolejnych nakładających się par`,
  },
  {
    pattern: /^… and (\d+) more items to verify/,
    text: (m) => `… i ${m[1]} kolejnych pozycji do sprawdzenia`,
  },
  {
    pattern: /^Skipped client instruction: (.+)$/,
    text: (m) => `Pominięto instrukcję klienta: ${m[1]}`,
  },
  {
    pattern: /^Sources: omitted (\d+) AI call summaries without a transcript/,
    text: (m) =>
      `Źródła: pominięto ${m[1]} podsumowań rozmów AI bez transkryptu. Uzupełnij zweryfikowane notatki, jeśli zawierają istotne fakty o kandydacie.`,
  },
];

/** Zdanie do pokazania rekruterowi; nieznana uwaga wraca bez zmian. */
export function humanizeCvWarning(text: string): string {
  const trimmed = text.trim();
  for (const rule of RULES) {
    const match = trimmed.match(rule.pattern);
    if (match) return rule.text(match);
  }
  return trimmed;
}
