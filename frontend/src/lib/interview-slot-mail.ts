/**
 * Terminy rozmowy u klienta z wklejonego maila (20.10.2026).
 *
 * Serwer (`POST /api/interview-cycle/slots/from-mail`) zwraca terminy, które
 * przeszły kontrolę kodu; tu tylko zamieniamy je na wiersze formularza
 * (pola `datetime-local` w czasie przeglądarki, jak reszta okna) i notatkę
 * dla rekrutera. Treści maila nigdzie nie zapisujemy.
 */
import { formatSlot } from "@/lib/interview-cycle";

export type SlotMailWarning = "quote_mismatch" | "weekday_mismatch" | "weekend" | "unusual_hour";

export interface SlotFromMail {
  start: string;
  end: string;
  window: boolean;
  quote: string;
  warning: SlotMailWarning | null;
}

export interface SlotsFromMail {
  status: "ok" | "empty" | "unavailable";
  message: string | null;
  slots: SlotFromMail[];
  extra_slots: number;
  dropped: number;
  duration_minutes: number | null;
  respond_by: string | null;
  format: "online" | "onsite" | "phone" | null;
  location_note: string | null;
  people: string | null;
  unclear: string[];
}

/** Wiersz terminu w oknie „Terminy od klienta”: wartość pola + skąd się wziął. */
export interface SlotRow {
  value: string;
  quote?: string;
  warning?: SlotMailWarning | null;
  /** Koniec okna klienta („piątek 9–12”) — godzinę ustala rekruter z kandydatem. */
  windowEnd?: string;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** ISO → wartość `datetime-local` w czasie przeglądarki (odwrotność `new Date(value)`). */
export function isoToLocalInput(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function rowsFromMail(result: SlotsFromMail): SlotRow[] {
  return result.slots.map((slot) => ({
    value: isoToLocalInput(slot.start),
    quote: slot.quote,
    warning: slot.warning,
    windowEnd: slot.window ? slot.end : undefined,
  }));
}

/**
 * Czy wiersz z oknem klienta dalej nim jest: początek (`datetime-local`) tego
 * samego dnia co koniec okna, a cała rozmowa mieści się przed końcem okna.
 */
export function keepsWindow(value: string, windowEnd: string | undefined, durationMinutes: number): boolean {
  if (!value || !windowEnd) return false;
  const start = new Date(value);
  const end = new Date(windowEnd);
  return (
    start.toDateString() === end.toDateString() &&
    start.getTime() + durationMinutes * 60_000 <= end.getTime()
  );
}

const WARNINGS: Record<SlotMailWarning, string> = {
  quote_mismatch: "Data albo godzina nie zgadza się z cytatem z maila — sprawdź.",
  weekday_mismatch: "Dzień tygodnia w mailu nie zgadza się z datą — sprawdź z klientem.",
  weekend: "Termin wypada w weekend — sprawdź.",
  unusual_hour: "Nietypowa godzina — sprawdź.",
};

export function warningLabel(warning: SlotMailWarning | null | undefined): string | null {
  return warning ? WARNINGS[warning] : null;
}

const FORMAT: Record<NonNullable<SlotsFromMail["format"]>, string> = {
  online: "Online",
  onsite: "U klienta na miejscu",
  phone: "Telefonicznie",
};

/**
 * Notatka dla rekrutera z tego, co mail mówi poza terminami: forma, kto
 * będzie, okna godzin. Krótko — rekruter czyta ją przy telefonie do kandydata.
 */
export function noteFromMail(result: SlotsFromMail): string {
  const lines: string[] = [];
  const where = [result.format ? FORMAT[result.format] : null, result.location_note]
    .filter(Boolean)
    .join(" · ");
  if (where) lines.push(where);
  if (result.people) lines.push(`Po stronie klienta: ${result.people}`);
  for (const slot of result.slots) {
    if (slot.window) {
      lines.push(`Okno klienta: ${formatSlot({ start: slot.start, end: slot.end })} — godzinę ustal z kandydatem.`);
    }
  }
  return lines.join("\n");
}

/** Jedno zdanie pod polem maila po odczycie. */
export function readSummary(result: SlotsFromMail): string {
  if (result.status !== "ok") return result.message ?? "Nie udało się odczytać terminów.";
  const n = result.slots.length;
  const parts = [`Odczytane terminy: ${n}. Sprawdź je przed wysłaniem.`];
  if (result.extra_slots > 0) parts.push(`Pominięte ponad limit 6: ${result.extra_slots}.`);
  if (result.unclear.length > 0) parts.push(`Bez godziny: ${result.unclear.join("; ")}.`);
  return parts.join(" ");
}
