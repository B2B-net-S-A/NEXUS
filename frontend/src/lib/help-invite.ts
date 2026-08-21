/**
 * Zaproszenie na spotkanie przygotowujące (prep) — budowanie treści dla Outlooka.
 *
 * Rekruter ma dostać GOTOWE ZAPROSZENIE KALENDARZOWE, a CV i link do ogłoszenia
 * dokłada sam już w Outlooku. Dlatego tu nie ma żadnego wysyłania: generujemy
 * wyłącznie treść, którą przejmuje klient pocztowy.
 *
 * Dwie ścieżki, świadomie w tej kolejności:
 *
 * 1. **Plik `.ics` — ścieżka GŁÓWNA.** Rekruterzy pracują w DESKTOPOWYM
 *    Outlooku, a pobrany `.ics` otwiera się w aplikacji jako formularz
 *    spotkania. Tam da się dołączyć plik CV — czego pop-out webowy nie robi.
 * 2. **Deeplink `outlook.office.com/calendar/action/compose` — opcja dodatkowa**
 *    dla pracujących w Outlook Web.
 *
 * ⚠️ Zmierzone zachowanie deeplinku (nie „poprawiaj" tego na `%0A`): parametr
 * `body` w URL-u gubi znaki nowej linii — treść zlewa się w jeden akapit.
 * Łamanie wierszy działa dopiero przez `<br>`, więc dla deeplinku body idzie
 * jako HTML, a dla `.ics` jako czysty tekst z `\n` (RFC 5545). To są dwa różne
 * formaty tej samej treści, nie duplikacja przez niedopatrzenie.
 */

import type {
  HelpMaterial,
  HelpMaterialTemplate,
} from "@/lib/api/help-materials";

/** Slug wiersza-szablonu zaseedowanego migracją 0229 (zakładka Pomoc). */
export const PREP_INVITE_SLUG = "zaproszenie-prep-spotkanie";

/**
 * Czy pozycja Pomocy jest SZABLONEM treści (a nie linkiem do pliku).
 *
 * Świadomie tutaj, a nie w `@/lib/api/help-materials`: testy mockują moduł API
 * w całości, więc funkcja trzymana tam znikałaby w nich z eksportów.
 * `import type` wyżej jest wymazywany przy kompilacji, więc ten moduł nie
 * ciągnie mocka za sobą.
 */
export function isTemplateMaterial(
  material: HelpMaterial,
): material is HelpMaterialTemplate {
  return (
    typeof material.template_body === "string" &&
    material.template_body.trim().length > 0
  );
}

/**
 * Szablon zaproszenia prep z listy materiałów — `null`, gdy admin go usunął.
 *
 * Slug jest wskazówką, nie warunkiem koniecznym. Samo przypięcie do stałej było
 * kruche: dopóki backend przeliczał slug z tytułu, jedna poprawka nazwy pozycji
 * w Pomocy gasiła przycisk na profilu KAŻDEGO kandydata, a admin nie widział
 * żadnego sygnału (zakładka Pomoc działa dalej — ona sluga nie używa).
 * Slug jest już niezmienny po stronie API, ale fallback zostaje: wiersz dodany
 * ręcznie przez admina NIGDY nie dostanie tej konkretnej stałej, bo slug
 * powstaje z tytułu — a komunikat pustego stanu każe właśnie taki wiersz dodać.
 */
export function findPrepInviteTemplate(
  materials: readonly HelpMaterial[],
): HelpMaterialTemplate | null {
  const bySlug = materials.find((m) => m.slug === PREP_INVITE_SLUG);
  if (bySlug && isTemplateMaterial(bySlug)) return bySlug;
  // Lista przychodzi posortowana po `sort_order`, więc przy kilku szablonach
  // wybór jest deterministyczny, a nie zależny od kolejności zapisu w bazie.
  return materials.find(isTemplateMaterial) ?? null;
}

/**
 * Podpowiedź dla REKRUTERA, świadomie trzymana poza treścią zaproszenia.
 *
 * Wrzucenie tego zdania do `body` wysłałoby kandydatowi wewnętrzną notatkę
 * operacyjną. Miejsce tej instrukcji jest w UI obok przycisku — i tylko tam.
 */
export const PREP_INVITE_CV_REMINDER =
  "UWAGA! Do zaproszenia załączamy CV wysłane pod dany projekt";

export interface InviteDraft {
  subject: string;
  body: string;
}

// ── Deeplink (Outlook Web) ──────────────────────────────────────────────────

const OUTLOOK_COMPOSE_BASE =
  "https://outlook.office.com/calendar/action/compose";

/** Kolejność ma znaczenie: `&` musi lecieć pierwszy, inaczej podwójnie escapuje. */
function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/**
 * Treść dla parametru `body` deeplinku: HTML z `<br>` zamiast `\n`.
 *
 * Escapowanie idzie PRZED zamianą na `<br>`, bo treść szablonu edytuje admin —
 * gdyby wpisał `<b>`, bez escapowania trafiłoby to do zaproszenia jako znacznik.
 */
export function toDeeplinkHtmlBody(body: string): string {
  return escapeHtml(body).replace(/\r\n|\r|\n/g, "<br>");
}

/**
 * Pop-out SPOTKANIA (nie maila) w Outlook Web z wypełnionym tematem i treścią.
 *
 * `rru=addevent` to parametr, który przełącza formularz w tryb wydarzenia.
 */
export function buildOutlookComposeUrl(draft: InviteDraft): string {
  const params = new URLSearchParams({
    rru: "addevent",
    subject: draft.subject,
    body: toDeeplinkHtmlBody(draft.body),
  });
  return `${OUTLOOK_COMPOSE_BASE}?${params.toString()}`;
}

// ── Plik .ics (Outlook desktop) ─────────────────────────────────────────────

/**
 * Escapowanie wartości TEXT wg RFC 5545 §3.3.11.
 *
 * Backslash MUSI iść pierwszy — inaczej podwoiłby backslashe wstawione przez
 * kolejne reguły i „a;b" wyszłoby jako „a\\;b".
 */
function escapeIcsText(value: string): string {
  return value
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r\n|\r|\n/g, "\\n");
}

/**
 * Zawijanie linii do 75 oktetów (RFC 5545 §3.1) po GRANICACH ZNAKÓW.
 *
 * Liczymy oktety UTF-8, ale tniemy między znakami: przecięcie w środku
 * wielobajtowego „ż" czy „ę" dałoby uszkodzony plik — a polskie diakrytyki są
 * w tej treści w każdym zdaniu.
 */
function foldIcsLine(line: string): string {
  const encoder = new TextEncoder();
  const out: string[] = [];
  let current = "";
  let bytes = 0;
  // Limit 75 dla pierwszej linii; kontynuacje mają wiodącą spację, więc na
  // treść zostaje 74 oktety.
  let limit = 75;

  for (const char of line) {
    const size = encoder.encode(char).length;
    if (bytes + size > limit) {
      out.push(current);
      current = char;
      bytes = size;
      limit = 74;
    } else {
      current += char;
      bytes += size;
    }
  }
  out.push(current);
  return out.join("\r\n ");
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/**
 * Czas „pływający" (bez `Z` i bez `TZID`) — celowo.
 *
 * Termin jest w tym szablonie PLACEHOLDEREM: rekruter i tak ustawia go w
 * Outlooku, a rozmowy są lokalne. Zapis w UTC pokazywałby w kalendarzu godzinę
 * przesuniętą względem tej, którą widać w podglądzie, co przy „poprawianiu"
 * daty prowadzi do pomyłek o dwie godziny.
 */
function toFloatingIcsStamp(date: Date): string {
  return (
    `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}` +
    `T${pad(date.getHours())}${pad(date.getMinutes())}00`
  );
}

function toUtcIcsStamp(date: Date): string {
  return (
    `${date.getUTCFullYear()}${pad(date.getUTCMonth() + 1)}` +
    `${pad(date.getUTCDate())}T${pad(date.getUTCHours())}` +
    `${pad(date.getUTCMinutes())}${pad(date.getUTCSeconds())}Z`
  );
}

export interface BuildIcsOptions {
  /** Wstrzykiwane w testach; w produkcji „teraz". */
  now?: Date;
  /** Wstrzykiwane w testach; w produkcji losowy UID. */
  uid?: string;
  durationMinutes?: number;
}

const DEFAULT_DURATION_MINUTES = 30;

/**
 * Domyślny termin = najbliższa pełna godzina.
 *
 * Zaproszenie z terminem w przeszłości Outlook potrafi od razu oznaczyć jako
 * minione, więc pusty slot musi celować w przyszłość — nawet jeśli rekruter
 * i tak go zaraz zmieni.
 */
function nextFullHour(now: Date): Date {
  const start = new Date(now.getTime());
  start.setSeconds(0, 0);
  start.setMinutes(0);
  start.setHours(start.getHours() + 1);
  return start;
}

/**
 * Zaproszenie jako plik `.ics` (VEVENT) do otwarcia w Outlooku desktopowym.
 *
 * Bez `METHOD:REQUEST` i bez `ATTENDEE`: to jest SZKIC, który rekruter otwiera
 * u siebie, dokłada CV i adresata, i dopiero wtedy wysyła. `METHOD:REQUEST`
 * kazałby Outlookowi potraktować plik jako przychodzące zaproszenie od kogoś
 * innego — z przyciskami „Akceptuj/Odrzuć" zamiast edytowalnego formularza.
 */
export function buildInviteIcs(
  draft: InviteDraft,
  options: BuildIcsOptions = {},
): string {
  const now = options.now ?? new Date();
  const start = nextFullHour(now);
  const duration = options.durationMinutes ?? DEFAULT_DURATION_MINUTES;
  const end = new Date(start.getTime() + duration * 60_000);
  const uid = options.uid ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;

  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//NEXUS//Zaproszenie prep//PL",
    "CALSCALE:GREGORIAN",
    "BEGIN:VEVENT",
    `UID:${uid}@nexus.dynaminds.pl`,
    `DTSTAMP:${toUtcIcsStamp(now)}`,
    `DTSTART:${toFloatingIcsStamp(start)}`,
    `DTEND:${toFloatingIcsStamp(end)}`,
    `SUMMARY:${escapeIcsText(draft.subject)}`,
    `DESCRIPTION:${escapeIcsText(draft.body)}`,
    "END:VEVENT",
    "END:VCALENDAR",
  ];

  // CRLF wymagane przez RFC 5545; Outlook desktop na samych LF potrafi
  // odmówić otwarcia pliku. Zamykający CRLF też jest częścią specyfikacji.
  return `${lines.map(foldIcsLine).join("\r\n")}\r\n`;
}

/** Nazwa pliku do pobrania — ASCII, bez znaków zakazanych w Windows. */
export function icsFileName(subject: string): string {
  const ascii = subject
    // NFKD rozkłada „ę" na „e" + znak łączący, ale „ł" ma diakryt wtopiony
    // w glif — bez tej podmianki wypadłoby BEZ ŚLADU („Zupełnie" → „Zupenie").
    .normalize("NFKD")
    .replace(/ł/g, "l")
    .replace(/Ł/g, "L")
    .replace(/\p{Diacritic}/gu, "")
    // Zostaje drukowalne ASCII: nazwa pliku jedzie na dysk rekrutera (Windows),
    // a znaki sterujące i spoza ASCII bywają tam odrzucane.
    .replace(/[^\x20-\x7e]/g, "")
    .replace(/[\\/:*?"<>|]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  const base = ascii.slice(0, 80) || "zaproszenie";
  return `${base}.ics`;
}

// ── Podstawianie danych do szablonu ─────────────────────────────────────────

/**
 * Nawiasy okrągłe w treści to NIE jest składnia szablonowania — to instrukcja
 * dla człowieka. Ta sama treść jedzie do Outlooka, gdzie żaden silnik jej nie
 * rozwinie, więc każdy nawias, którego nie podmienimy tutaj, MUSI zostać
 * widoczny: rekruter ma go uzupełnić ręcznie.
 */
export interface InviteFacts {
  candidateName?: string | null;
  clientName?: string | null;
  jobTitle?: string | null;
  interviewDate?: string | null;
}

const PLACEHOLDERS = {
  candidateName: "(imię i nazwisko kandydata)",
  clientName: "(nazwa Klienta)",
  jobTitle: "(nazwa stanowiska)",
  interviewDate: "(data interview)",
} as const;

function replaceAll(source: string, needle: string, value: string): string {
  return source.split(needle).join(value);
}

/**
 * Podstawia WYŁĄCZNIE to, co faktycznie znamy.
 *
 * Link do ogłoszenia zostaje placeholderem świadomie: adresy ofert w NEXUSie są
 * dziś generowane sztucznie (`_simulate_url` w `api/postings.py`), więc
 * automatyczne wklejenie wysłałoby kandydatowi link prowadzący donikąd. Lepszy
 * widoczny placeholder do uzupełnienia niż cichy martwy adres.
 */
export function fillInviteTemplate(template: string, facts: InviteFacts): string {
  let out = template;
  for (const [key, placeholder] of Object.entries(PLACEHOLDERS)) {
    const value = facts[key as keyof InviteFacts];
    const trimmed = typeof value === "string" ? value.trim() : "";
    if (trimmed) out = replaceAll(out, placeholder, trimmed);
  }
  return out;
}

export function fillInviteDraft(draft: InviteDraft, facts: InviteFacts): InviteDraft {
  return {
    subject: fillInviteTemplate(draft.subject, facts),
    body: fillInviteTemplate(draft.body, facts),
  };
}

// ── Pobranie pliku ──────────────────────────────────────────────────────────

/**
 * Pobiera wygenerowany `.ics`.
 *
 * BEZ BOM-a. Kuszące jest dopisanie `﻿` „żeby Outlook na Windows nie
 * zrobił krzaków z polskich znaków", ale RFC 5545 §3.1 wymaga, żeby strumień
 * ZACZYNAŁ się od `BEGIN:VCALENDAR` — zmierzone: z BOM-em plik odrzucają
 * `icalendar` (po zdekodowaniu jako zwykły UTF-8), `vobject` i `ical.js`
 * (czyli Thunderbird). Rekruter przesyła ten plik dalej, więc płacenie pewną
 * niezgodnością ze standardem za nigdy niezmierzoną korzyść się nie opłaca.
 * `charset=utf-8` w typie MIME zostaje.
 *
 * `revokeObjectURL` dopiero po kliknięciu — zwolnienie URL-a w tej samej
 * mikrozadaniowej turze potrafi ubić trwające pobieranie.
 */
export function downloadIcsFile(fileName: string, content: string): void {
  const blob = new Blob([content], {
    type: "text/calendar;charset=utf-8",
  });
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  setTimeout(() => URL.revokeObjectURL(href), 0);
}
