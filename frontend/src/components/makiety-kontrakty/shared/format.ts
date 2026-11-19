// Formatowanie w makietach modułu Kontrakty — jedno miejsce dla dat, kwot,
// odmiany i nazw osób, żeby wszystkie warianty mówiły tym samym językiem.
import { formatMoney } from "@/lib/money";
import { formatPhone } from "@/lib/phone-format";
import { warsawToday } from "@/lib/warsaw-date";
import { CONTRACT_TERMINATION_REASONS } from "@/lib/api";

/** „30.11.2026”; brak → „—”. */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  if (!y || !m || !d) return "—";
  return `${d}.${m}.${y}`;
}

/** „30.11” (bez roku) — dla dat w bieżącym roku w gęstych miejscach. */
export function fmtDayMonth(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}`;
}

const MONTHS_PL = [
  "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
  "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
];
const MONTHS_PL_SHORT = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];

/** „wrzesień 2026”. */
export function fmtMonthYear(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m] = iso.slice(0, 7).split("-");
  return `${MONTHS_PL[Number(m) - 1]} ${y}`;
}

/** „lis 2026”. */
export function fmtMonthShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m] = iso.slice(0, 7).split("-");
  return `${MONTHS_PL_SHORT[Number(m) - 1]} ${y}`;
}

/** Dziś w kalendarzu firmy (Europe/Warsaw), „RRRR-MM-DD”. */
export function today(): string {
  return warsawToday();
}

/** Liczba dni od dziś do daty (ujemna = minęło). */
export function daysUntil(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const a = Date.parse(`${today()}T00:00:00Z`);
  const b = Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return Math.round((b - a) / 86_400_000);
}

/** Odmiana: plural(5, ["dzień", "dni", "dni"]) → „5 dni”. */
export function plural(n: number, forms: [string, string, string]): string {
  const abs = Math.abs(n);
  const mod10 = abs % 10;
  const mod100 = abs % 100;
  let form = forms[2];
  if (abs === 1) form = forms[0];
  else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) form = forms[1];
  return `${n.toLocaleString("pl-PL")} ${form}`;
}

export const DNI: [string, string, string] = ["dzień", "dni", "dni"];
export const OSOBY: [string, string, string] = ["osoba", "osoby", "osób"];
export const UMOWY: [string, string, string] = ["umowa", "umowy", "umów"];
export const KONTRAKTY: [string, string, string] = ["kontrakt", "kontrakty", "kontraktów"];
export const PLIKI: [string, string, string] = ["plik", "pliki", "plików"];

/** „za 11 dni” / „dziś” / „jutro” / „11 dni temu”. */
export function relDays(iso: string | null | undefined): string {
  const d = daysUntil(iso);
  if (d == null) return "";
  if (d === 0) return "dziś";
  if (d === 1) return "jutro";
  if (d === -1) return "wczoraj";
  return d > 0 ? `za ${plural(d, DNI)}` : `${plural(-d, DNI)} temu`;
}

/** „163,00 zł/h”. */
export function fmtRate(value: number | null | undefined, unit = "hourly", currency = "PLN"): string {
  return formatMoney(value ?? null, currency, unit);
}

/** „6 384 zł” — kwota bez groszy ze spacją tysięcy. */
export function fmtPln(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(value)) return "—";
  const s = new Intl.NumberFormat("pl-PL", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    useGrouping: true,
  })
    .format(value)
    // pl-PL nie grupuje czterocyfrowych — w makietach chcemy „6 384”.
    .replace(/^(-?\d)(\d{3})([,\s]|$)/, "$1 $2$3");
  return `${s} zł`;
}

/** „163,00” — liczba z groszami, bez waluty (do kolumn z jednostką w nagłówku). */
export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("pl-PL", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/**
 * Marża procentowa od stawki klienta: „23,3 %”. Przy różnych walutach
 * (klient w EUR, konsultant w PLN) marży nie liczymy — serwer też jej nie podaje.
 */
export function marginPct(
  client: number | null | undefined,
  candidate: number | null | undefined,
  clientCur?: string | null,
  candidateCur?: string | null,
): string {
  if (!client || candidate == null) return "—";
  if ((clientCur ?? "PLN") !== (candidateCur ?? "PLN")) return "—";
  const pct = ((client - candidate) / client) * 100;
  return `${pct.toLocaleString("pl-PL", { maximumFractionDigits: 1, minimumFractionDigits: 1 })} %`;
}

/** Jednostka waluty do dopisku przy kwocie: „zł” dla PLN, kod dla reszty („EUR”). */
export function curUnit(cur: string | null | undefined): string {
  return !cur || cur === "PLN" ? "zł" : cur;
}

/** „jan.kowalski@firma.pl” → „Jan Kowalski”. */
export function personFromEmail(value: string | null | undefined): string {
  if (!value) return "System";
  if (!value.includes("@")) return value;
  const local = value.split("@")[0];
  return local
    .split(/[._-]+/)
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(" ");
}

export function terminationReasonLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  return CONTRACT_TERMINATION_REASONS.find((r) => r.value === value)?.label ?? value;
}

export const CONTRACT_STATUS_LABEL: Record<string, string> = {
  draft: "Szkic",
  ready_for_signature: "Do podpisu",
  active: "Aktywny",
  ending: "Kończy się",
  ended: "Zakończony",
  terminated: "Rozwiązany",
  cancelled: "Anulowany",
};

export const CONTRACT_TYPE_LABEL: Record<string, string> = {
  b2b: "B2B",
  uop: "Umowa o pracę",
  uz: "Umowa zlecenia",
  zlecenie: "Umowa zlecenia",
};

/** Decyzja o przedłużeniu (`prolongation_status`) słowami z punktu widzenia DL. */
export const PROLONGATION_LABEL: Record<string, string> = {
  yes: "Klient przedłuża",
  no: "Klient nie przedłuża",
  negotiate: "W negocjacjach",
  unknown: "Brak decyzji",
};

/** „667 015 150” — numer w trójkach, nieznany format bez zmian. */
export function fmtPhone(raw: string | null | undefined): string {
  return raw ? formatPhone(raw) : "—";
}
