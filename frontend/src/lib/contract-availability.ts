/**
 * Dostępność osoby, która pracuje u nas — z umowy, nie ze screeningu
 * (15.10.2026, decyzje Artura D1–D6).
 *
 * Zgłoszenie: profil mówił „Pracuje u nas do 30.11.2026” i jednocześnie
 * „Dostępność od 1.09.2026” — data pochodziła z notatek sprzed zatrudnienia.
 * Serwer liczy w znaczniku `free_from` (dzień po końcu pracy u nas); termin =
 * późniejsza z dat: `free_from` i data z profilu. Wcześniejsza data z profilu
 * to dawny screening; późniejsza znaczy, że kandydat sam podał dalszy termin.
 * Odejście przed końcem zamówienia ustala Delivery.
 *
 * Każdy ekran z osobą sprawdza najpierw ten moduł; `null` = osoba bez żywej
 * umowy, ekran liczy dostępność jak dotąd. Bez importów z `@/lib/api`
 * (testy okien mockują tamte moduły wąsko — jak `lib/employment-marker.ts`).
 */
import { formatIsoDatePl } from "@/lib/date-pl";
import type { EmploymentMarker } from "@/lib/employment-marker";

const DAY_MS = 86_400_000;

interface Common {
  /** Klient (albo klienci) bieżącej pracy — do dymka. */
  clientName: string | null;
  deliveryLead: string | null;
  /** Data z profilu (`availability_date`), także ta, która się nie liczy. */
  profileDate: string | null;
}

export type ContractAvailability =
  | (Common & {
      kind: "date";
      /** Termin dostępności (RRRR-MM-DD). */
      date: string;
      /** `profile` = kandydat podał termin późniejszy niż koniec pracy u nas. */
      basis: "contract" | "profile";
      /** Ostatni dzień pracy u nas. */
      workEnd: string;
      /** Zamówienia już się skończyły, a umowa trwa. */
      ordersEnded: boolean;
      /** Faza „kończy u nas”: ile dni do terminu. */
      daysLeft: number | null;
    })
  | (Common & { kind: "no_end_date" })
  | (Common & { kind: "starting"; date: string | null });

/** Dzień kalendarzowy RRRR-MM-DD z ISO (bez `new Date(...)` — patrz `date-pl`). */
function isoDay(value: string | null | undefined): string | null {
  const match = /^(\d{4}-\d{2}-\d{2})/.exec(value?.trim() ?? "");
  return match ? match[1] : null;
}

/** Dzisiejsza data w strefie przeglądarki (firma pracuje w Europe/Warsaw). */
export function localIsoDay(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function utc(day: string): number {
  const [y, m, d] = day.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

function dayBefore(day: string): string {
  return new Date(utc(day) - DAY_MS).toISOString().slice(0, 10);
}

function clientNames(marker: EmploymentMarker): string | null {
  const names = marker.clients
    .map((c) => c.client_name?.trim() || (c.client_id != null ? `Klient #${c.client_id}` : ""))
    .filter(Boolean);
  return names.length ? names.join(", ") : null;
}

/** Pigułka „Szuka aktywnie / Otwarty na oferty” znika przy żywej umowie (D3). */
export function hidesAvailabilityStatus(marker: EmploymentMarker | null | undefined): boolean {
  return marker?.source === "contract";
}

export function contractAvailability(
  marker: EmploymentMarker | null | undefined,
  profileDate: string | null | undefined,
  today: string = localIsoDay(),
): ContractAvailability | null {
  if (!marker || marker.source !== "contract" || !marker.free_from_basis) return null;
  const common: Common = {
    clientName: clientNames(marker),
    deliveryLead: marker.clients.find((c) => c.delivery_lead_name)?.delivery_lead_name ?? null,
    profileDate: isoDay(profileDate),
  };
  if (marker.free_from_basis === "starting") {
    const starts = marker.clients
      .map((c) => isoDay(c.starts_on))
      .filter((d): d is string => Boolean(d))
      .sort();
    return { ...common, kind: "starting", date: starts[0] ?? null };
  }
  const free = isoDay(marker.free_from);
  if (marker.free_from_basis === "no_end_date" || !free) {
    return { ...common, kind: "no_end_date" };
  }
  const later = common.profileDate !== null && common.profileDate > free;
  const date = later ? (common.profileDate as string) : free;
  const ordersEnded = !later && free <= today;
  const daysLeft =
    marker.phase === "ending" && !ordersEnded && date > today
      ? Math.round((utc(date) - utc(today)) / DAY_MS)
      : null;
  return {
    ...common,
    kind: "date",
    date,
    basis: later ? "profile" : "contract",
    workEnd: dayBefore(free),
    ordersEnded,
    daysLeft,
  };
}

function shortDay(day: string): string {
  return formatIsoDatePl(day).slice(0, 5);
}

/**
 * Tekst terminu: `long` — profil, panel osoby, Tablica („od 01.12.2026”);
 * `short` — wąska kolumna listy („od 01.12”).
 */
export function contractAvailabilityText(
  a: ContractAvailability,
  style: "long" | "short" = "long",
): string {
  const fmt = style === "short" ? shortDay : formatIsoDatePl;
  if (a.kind === "starting") {
    if (!a.date) return style === "short" ? "zaczyna u nas" : "Zaczyna u nas";
    return style === "short" ? `zaczyna ${fmt(a.date)}` : `Zaczyna u nas ${fmt(a.date)}`;
  }
  if (a.kind === "no_end_date") {
    return style === "short" ? "bez daty końca" : "Bez daty końca zamówienia";
  }
  if (a.ordersEnded) {
    return style === "short"
      ? `zam. do ${fmt(a.workEnd)}`
      : `Zamówienia skończyły się ${fmt(a.workEnd)}`;
  }
  return `od ${fmt(a.date)}`;
}

/** „za 17 dni” przy fazie „kończy u nas”; `null` poza nią. */
export function contractAvailabilityCountdown(a: ContractAvailability): string | null {
  if (a.kind !== "date" || a.daysLeft == null) return null;
  return a.daysLeft === 1 ? "jutro" : `za ${a.daysLeft} dni`;
}

/** Dymek przy kropce źródła — skąd termin i co z datą z profilu. */
export function contractAvailabilityOrigin(a: ContractAvailability): {
  text: string;
  title: string;
  tone: "contract" | "notes";
} {
  const where = a.clientName ? ` w ${a.clientName}` : "";
  const fmt = formatIsoDatePl;
  const profileLine = (why: string) =>
    a.profileDate ? ` W profilu: od ${fmt(a.profileDate)} — ${why}.` : "";
  if (a.kind === "starting") {
    return {
      title: "Z kontraktu",
      tone: "contract",
      text: a.date
        ? `Z kontraktu: umowa${where} startuje ${fmt(a.date)}.`
        : `Z kontraktu: umowa${where} jeszcze się nie zaczęła.`,
    };
  }
  if (a.kind === "no_end_date") {
    return {
      title: "Z kontraktu",
      tone: "contract",
      text:
        `Z kontraktu: zamówienie${where} nie ma daty końca — termin zna Delivery.` +
        profileLine("liczy się dopiero po ustaleniu końca pracy u nas"),
    };
  }
  if (a.basis === "profile") {
    return {
      title: "Z profilu",
      tone: "notes",
      text: `Z profilu: później niż koniec pracy${where} (${fmt(a.workEnd)}).`,
    };
  }
  if (a.ordersEnded) {
    return {
      title: "Z kontraktu",
      tone: "contract",
      text:
        `Z kontraktu: zamówienia${where} skończyły się ${fmt(a.workEnd)}, a umowa trwa — ` +
        "ustal z Delivery, czy osoba jest wolna.",
    };
  }
  return {
    title: "Z kontraktu",
    tone: "contract",
    text:
      `Z kontraktu: dzień po końcu zamówienia${where} (${fmt(a.workEnd)}).` +
      profileLine("wcześniej niż koniec pracy u nas, nie liczy się"),
  };
}
