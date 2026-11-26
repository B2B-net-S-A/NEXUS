/**
 * Karty, które automat oddał ze „Screeningu” do „Nowych” (26.11.2026).
 *
 * Rekruter zgłosił, że osoby „znikają” ze Screeningu i nie pamięta, które to
 * były. Reguła 2 dni roboczych zostaje (`services/screening_stale.py`), ale
 * Tablica pokazuje ślad: osobie, od której karta wróciła, grupę „Wróciły od
 * Ciebie” na górze „Nowych”, a pozostałym napis „Wróciła ze Screeningu od …”
 * pod kartą. Dane liczy serwer (`returned_from_screening` w
 * `/api/pipeline/kanban/{job_id}`, ostatnie 5 dni roboczych, tylko karty,
 * których nikt jeszcze nie ruszył). Reguła:
 * `docs/claude/rekrutacja-tablica/karty-bez-sladu-wracaja-do-nowych.md`.
 */

export interface ReturnedFromScreening {
  at: string;
  holder_user_id?: number | null;
  holder_name?: string | null;
  screening_since?: string | null;
}

interface ReturnedItem {
  returned_from_screening?: ReturnedFromScreening | null;
}

const DAY = new Intl.DateTimeFormat("pl-PL", {
  timeZone: "Europe/Warsaw",
  day: "2-digit",
  month: "2-digit",
});

function dayLabel(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? null : DAY.format(at);
}

/** Karta wróciła od osoby, która patrzy na Tablicę. */
export function returnedToViewer(item: ReturnedItem, viewerId: number | null | undefined): boolean {
  const holder = item.returned_from_screening?.holder_user_id;
  return viewerId != null && holder != null && holder === viewerId;
}

/** Napis pod kartą w „Nowych”; `null` = karta nie wróciła ze Screeningu. */
export function returnedLine(item: ReturnedItem, viewerId: number | null | undefined): string | null {
  const returned = item.returned_from_screening;
  if (!returned) return null;
  const when = dayLabel(returned.at);
  if (returnedToViewer(item, viewerId)) {
    // Grupa nad kartą mówi już „Wróciły od Ciebie” — tu sam dzień, żeby
    // „Weź z powrotem” zmieściło się w tej samej linii przy 1280 px.
    return `Wróciła${when ? ` ${when}` : ""}`;
  }
  const holder = returned.holder_name?.trim();
  return holder ? `Wróciła ze Screeningu od: ${holder}` : "Wróciła ze Screeningu";
}

/** Podpowiedź napisu: dlaczego karta wróciła. */
export const RETURNED_TITLE =
  "2 dni robocze bez notatki, próby kontaktu, telefonu, arkusza i ruchu karty — karta wróciła do „Nowych” dla wszystkich.";

/** Podpowiedź napisu pod kartą: od kiedy stała w Screeningu i dlaczego wróciła. */
export function returnedTitle(item: ReturnedItem): string {
  const since = dayLabel(item.returned_from_screening?.screening_since);
  return since ? `W Screeningu od ${since}. ${RETURNED_TITLE}` : RETURNED_TITLE;
}

/** Pasek nad „Screeningiem” (26.11.2026): ile kart ma napis „Wraca do
 *  „Nowych” …” (został najwyżej 1 dzień roboczy). `notices` to wynik
 *  `returnNotice` dla kart kolumny; `null` = nic nie wraca. */
export function screeningWarning(notices: readonly (string | null)[]): string | null {
  const shown = notices.filter((n): n is string => Boolean(n));
  if (shown.length === 0) return null;
  const same = shown.every((n) => n === shown[0]);
  const head = same ? shown[0] : "Wkrótce wraca do „Nowych”";
  return `${head}: ${people(shown.length)}`;
}

/** „1 osoba”, „3 osoby”, „5 osób”, „22 osoby”. */
export function people(count: number): string {
  if (count === 1) return "1 osoba";
  const few = count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14);
  return `${count} ${few ? "osoby" : "osób"}`;
}
