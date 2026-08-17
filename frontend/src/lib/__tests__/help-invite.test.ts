import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { HelpMaterial } from "@/lib/api/help-materials";
import {
  PREP_INVITE_CV_REMINDER,
  PREP_INVITE_SLUG,
  buildInviteIcs,
  buildOutlookComposeUrl,
  downloadIcsFile,
  fillInviteDraft,
  fillInviteTemplate,
  findPrepInviteTemplate,
  icsFileName,
  toDeeplinkHtmlBody,
} from "@/lib/help-invite";

/** Treść 1:1 z seeda migracji 0229 — testujemy to, co realnie jedzie do Outlooka. */
const SEED_SUBJECT =
  "Przygotowanie do spotkania z (nazwa Klienta) – (imię i nazwisko kandydata)";
const SEED_BODY = [
  "Dzień dobry,",
  "",
  "Zapraszam na spotkanie przygotowujące do rozmowy z (nazwa Klienta) na stanowisko (nazwa stanowiska), które odbędzie się (data interview).",
  "",
  "Link do opisu stanowiska: (link do pracuj / rocketjobs)",
  "",
  "W razie pytań pozostaję do dyspozycji.",
  "",
  "Pozdrawiam",
].join("\n");

const FIXED_NOW = new Date(2026, 7, 17, 11, 42, 13);

describe("Zaproszenie prep — deeplink do Outlook Web", () => {
  it("łamie wiersze przez <br>, bo %0A jest w deeplinku zjadane", () => {
    // Zmierzone zachowanie Outlooka: `body` z `\n` zlewa się w jeden akapit.
    expect(toDeeplinkHtmlBody("a\nb")).toBe("a<br>b");
    expect(toDeeplinkHtmlBody("a\r\nb")).toBe("a<br>b");

    const url = buildOutlookComposeUrl({ subject: "T", body: SEED_BODY });
    const body = new URL(url).searchParams.get("body") ?? "";
    expect(body).toContain("<br>");
    expect(body).not.toContain("\n");
  });

  it("otwiera pop-out SPOTKANIA (rru=addevent), nie maila", () => {
    const url = new URL(buildOutlookComposeUrl({ subject: "T", body: "B" }));
    expect(url.origin + url.pathname).toBe(
      "https://outlook.office.com/calendar/action/compose",
    );
    expect(url.searchParams.get("rru")).toBe("addevent");
  });

  it("przenosi temat i treść bez zgubienia polskich znaków", () => {
    const url = new URL(
      buildOutlookComposeUrl({ subject: SEED_SUBJECT, body: SEED_BODY }),
    );
    expect(url.searchParams.get("subject")).toBe(SEED_SUBJECT);
    expect(url.searchParams.get("body")).toContain("Dzień dobry,");
    expect(url.searchParams.get("body")).toContain("pozostaję do dyspozycji");
  });

  it("escapuje HTML z treści szablonu, zanim wstawi <br>", () => {
    // Treść edytuje admin — bez escapowania „<b>" trafiłoby do zaproszenia
    // jako znacznik, a nie jako tekst.
    expect(toDeeplinkHtmlBody("<b>x</b> & y")).toBe("&lt;b&gt;x&lt;/b&gt; &amp; y");
  });
});

describe("Zaproszenie prep — plik .ics (ścieżka główna, Outlook desktop)", () => {
  const ics = buildInviteIcs(
    { subject: SEED_SUBJECT, body: SEED_BODY },
    { now: FIXED_NOW, uid: "test-uid" },
  );

  it("jest poprawnym VCALENDAR z jednym VEVENT", () => {
    expect(ics.startsWith("BEGIN:VCALENDAR\r\n")).toBe(true);
    expect(ics.endsWith("END:VCALENDAR\r\n")).toBe(true);
    expect(ics).toContain("BEGIN:VEVENT");
    expect(ics).toContain("END:VEVENT");
    expect(ics).toContain("VERSION:2.0");
    expect(ics).toContain("UID:test-uid@nexus.dynaminds.pl");
  });

  it("używa CRLF — na samym LF Outlook desktop potrafi odmówić otwarcia", () => {
    const bareLf = ics.replace(/\r\n/g, "");
    expect(bareLf).not.toContain("\n");
  });

  it("NIE jest METHOD:REQUEST — rekruter ma dostać edytowalny szkic", () => {
    // METHOD:REQUEST każe Outlookowi pokazać „Akceptuj/Odrzuć" zamiast
    // formularza, do którego da się dołączyć CV.
    expect(ics).not.toContain("METHOD:");
    expect(ics).not.toContain("ATTENDEE");
  });

  it("domyślny termin to najbliższa pełna godzina, 30 minut", () => {
    expect(ics).toContain("DTSTART:20260817T120000");
    expect(ics).toContain("DTEND:20260817T123000");
  });

  it("escapuje przecinki i średniki wg RFC 5545", () => {
    const escaped = buildInviteIcs(
      { subject: "a,b;c\\d", body: "x,y" },
      { now: FIXED_NOW, uid: "u" },
    );
    expect(escaped).toContain("SUMMARY:a\\,b\\;c\\\\d");
  });

  it("zamienia nowe linie na \\n, nie gubi pustych akapitów", () => {
    const description = ics
      .split("\r\n")
      // rozwiń zawijanie wierszy przed sprawdzeniem treści
      .reduce<string[]>((acc, line) => {
        if (line.startsWith(" ") && acc.length) acc[acc.length - 1] += line.slice(1);
        else acc.push(line);
        return acc;
      }, [])
      .find((line) => line.startsWith("DESCRIPTION:"));
    expect(description).toBeDefined();
    expect(description).toContain("Dzień dobry\\,\\n\\nZapraszam");
    expect(description).toContain("Pozdrawiam");
  });

  it("zawija długie wiersze bez rozcinania polskich znaków", () => {
    for (const line of ics.split("\r\n")) {
      expect(new TextEncoder().encode(line).length).toBeLessThanOrEqual(75);
    }
    // Rekonstrukcja musi odtworzyć oryginał — dowód, że nie zgubiliśmy bajtu.
    const unfolded = ics.split("\r\n ").join("");
    expect(unfolded).toContain("przygotowujące");
    expect(unfolded).toContain("odbędzie się");
  });

  it("NIE zawiera instrukcji dla rekrutera o CV", () => {
    // Ta podpowiedź jest dla rekrutera; w treści byłaby wewnętrzną notatką
    // operacyjną wysłaną kandydatowi.
    expect(ics).not.toContain("UWAGA");
    expect(SEED_BODY).not.toContain(PREP_INVITE_CV_REMINDER);
  });
});

describe("Zaproszenie prep — nazwa pliku", () => {
  it("sprowadza polskie znaki do ASCII i usuwa znaki zakazane w Windows", () => {
    const name = icsFileName(SEED_SUBJECT);
    // Nawiasy zostają — są legalne w nazwach plików i niosą informację, że
    // temat wciąż ma placeholdery do uzupełnienia.
    expect(name).toBe(
      "Przygotowanie-do-spotkania-z-(nazwa-Klienta)-(imie-i-nazwisko-kandydata).ics",
    );
    expect(name).toMatch(/^[\x20-\x7e]+\.ics$/);
    expect(icsFileName('a/b:c*d?e"f<g>h|i')).toBe("abcdefghi.ics");
  });

  it("nigdy nie zwraca samego rozszerzenia", () => {
    expect(icsFileName("")).toBe("zaproszenie.ics");
    expect(icsFileName("的的的")).toBe("zaproszenie.ics");
  });
});

describe("Zaproszenie prep — podstawianie danych", () => {
  it("podstawia to, co znamy, i zostawia resztę jako widoczny placeholder", () => {
    const filled = fillInviteDraft(
      { subject: SEED_SUBJECT, body: SEED_BODY },
      { candidateName: "Jan Kowalski" },
    );
    expect(filled.subject).toBe(
      "Przygotowanie do spotkania z (nazwa Klienta) – Jan Kowalski",
    );
    expect(filled.body).toContain("(nazwa Klienta)");
    expect(filled.body).toContain("(nazwa stanowiska)");
    expect(filled.body).toContain("(data interview)");
  });

  it("NIE podstawia linku do ogłoszenia", () => {
    // Adresy ofert są w NEXUSie generowane sztucznie (`_simulate_url`), więc
    // automat wysłałby kandydatowi link prowadzący donikąd.
    const filled = fillInviteTemplate(SEED_BODY, {
      candidateName: "Jan Kowalski",
      clientName: "BNP",
      jobTitle: "DevOps",
      interviewDate: "20.08.2026",
    });
    expect(filled).toContain("(link do pracuj / rocketjobs)");
    expect(filled).toContain("z BNP na stanowisko DevOps");
    expect(filled).toContain("odbędzie się 20.08.2026");
  });

  it("puste i białe wartości nie kasują placeholdera", () => {
    // Podmiana na pusty string zostawiłaby „rozmowy z  na stanowisko" —
    // zdanie wygląda na sprawne, a rekruter nie widzi, że czegoś brakuje.
    const filled = fillInviteTemplate(SEED_BODY, {
      clientName: "   ",
      jobTitle: null,
    });
    expect(filled).toContain("(nazwa Klienta)");
    expect(filled).toContain("(nazwa stanowiska)");
  });

  it("podstawia KAŻDE wystąpienie, nie tylko pierwsze", () => {
    const filled = fillInviteTemplate(
      "(nazwa Klienta) — druga wzmianka: (nazwa Klienta)",
      { clientName: "BNP" },
    );
    expect(filled).toBe("BNP — druga wzmianka: BNP");
  });
});

describe("Zaproszenie prep — odnajdywanie szablonu w Materiałach", () => {
  function row(overrides: Partial<HelpMaterial> = {}): HelpMaterial {
    return {
      id: 1,
      slug: PREP_INVITE_SLUG,
      category: "Szablony i wzory",
      title: "Zaproszenie na spotkanie przygotowujące (prep)",
      url: null,
      description: null,
      template_subject: SEED_SUBJECT,
      template_body: SEED_BODY,
      is_editable_template: false,
      sort_order: 35,
      is_published: true,
      created_by: null,
      updated_by: null,
      created_at: "2026-08-17T10:00:00Z",
      updated_at: "2026-08-17T10:00:00Z",
      ...overrides,
    };
  }

  it("bierze wiersz o zaseedowanym slugu", () => {
    expect(findPrepInviteTemplate([row({ id: 7 })])?.id).toBe(7);
  });

  it("znajduje szablon także wtedy, gdy slug jest INNY", () => {
    // Slug jest już niezmienny po stronie API, ale wiersz dodany ręcznie przez
    // admina nigdy nie dostanie tej stałej (slug powstaje z tytułu) — a pusty
    // stan każe właśnie taki wiersz dodać. Bez fallbacku instrukcja kłamie.
    const found = findPrepInviteTemplate([
      row({ id: 12, slug: "zaproszenie-prep-2026" }),
    ]);
    expect(found?.id).toBe(12);
  });

  it("woli slug od kolejności, gdy szablonów jest kilka", () => {
    const found = findPrepInviteTemplate([
      row({ id: 1, slug: "inny-szablon", template_body: "co innego" }),
      row({ id: 2 }),
    ]);
    expect(found?.id).toBe(2);
  });

  it("pozycja bez treści NIE udaje sprawnego szablonu", () => {
    // Pusty szablon dałby puste zaproszenie — gorsze niż widoczny brak.
    expect(findPrepInviteTemplate([row({ template_body: "   " })])).toBeNull();
    expect(findPrepInviteTemplate([row({ template_body: null })])).toBeNull();
    expect(findPrepInviteTemplate([])).toBeNull();
  });
});

describe("Zaproszenie prep — pobranie pliku", () => {
  const blobs: Blob[] = [];

  beforeEach(() => {
    blobs.length = 0;
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn((blob: Blob) => {
        blobs.push(blob);
        return "blob:stub";
      }),
      revokeObjectURL: vi.fn(),
    });
    // jsdom nie implementuje nawigacji, więc `anchor.click()` na blob: URL-u
    // zaśmieca wynik ostrzeżeniem „Not implemented".
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  afterEach(async () => {
    // `downloadIcsFile` zwalnia blob: URL dopiero w `setTimeout(…, 0)` — celowo,
    // bo revoke w tej samej turze potrafi ubić trwające pobieranie. Ten timeout
    // wypada JUŻ PO teście, więc zdejmowanie atrapy tutaj zostawiało go z
    // prawdziwym `URL` jsdomu, który nie ma `revokeObjectURL`: wyjątek leciał
    // poza test jako „unhandled error", a vitest sam ostrzega, że takie błędy
    // potrafią dawać fałszywe zielone. Oddajemy pętli zdarzeń jedną turę, żeby
    // revoke wypadł, póki atrapa jeszcze żyje.
    await new Promise((resolve) => setTimeout(resolve, 0));
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("zapisuje plik BEZ BOM-a — RFC 5545 każe zacząć od BEGIN:VCALENDAR", () => {
    // Z BOM-em plik odrzucają `icalendar` (po zdekodowaniu jako UTF-8),
    // `vobject` i `ical.js` (Thunderbird). Rekruter przesyła go dalej, więc
    // niezgodność ze standardem kosztuje realnie.
    const content = buildInviteIcs(
      { subject: SEED_SUBJECT, body: SEED_BODY },
      { now: FIXED_NOW, uid: "u" },
    );
    downloadIcsFile("zaproszenie.ics", content);

    expect(blobs).toHaveLength(1);
    // Rozmiar w BAJTACH: BOM dołożyłby dokładnie 3 (EF BB BF) i to jedyna
    // różnica, jakiej ten test pilnuje.
    expect(blobs[0].size).toBe(new TextEncoder().encode(content).length);
    expect(blobs[0].type).toBe("text/calendar;charset=utf-8");
  });
});
