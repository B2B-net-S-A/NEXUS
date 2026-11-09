/**
 * Znacznik „Pracuje u nas” — jedna treść dla każdego ekranu (12.10.2026).
 *
 * Serwer liczy go w `services/employment_marker.py` i wysyła jako
 * `employment_marker` przy osobie na liście, w wyszukiwarkach, na Tablicy,
 * w propozycjach i w „Moich ludziach”. Tu jest wyłącznie to, co z niego
 * czytamy: etykieta pigułki, kolor i wiersze ramki.
 *
 * Od 17.10.2026 (decyzja Artura) jedynym źródłem jest umowa w Kontraktach
 * (B2B, umowa o pracę, zlecenie — trwająca albo podpisana z przyszłym
 * startem). Ręcznego oznaczania i znacznika z samego etapu „Zatrudniony” już
 * nie ma; karta na „Zatrudniony” bez umowy mówi „Brak umowy w Kontraktach”
 * (`lib/board-card-badges.ts`).
 *
 * Świadomie bez importów z `@/lib/api` — testy okien mockują tamte moduły
 * wąsko i import wartości stamtąd wywracał cały plik testu.
 */
import { formatIsoDatePl } from "@/lib/date-pl";
import { pluralPl } from "@/lib/plural-pl";

export type EmploymentPhase = "working" | "ending" | "starting";

export interface EmploymentMarkerClient {
  client_id?: number | null;
  client_name?: string | null;
  contract_id?: number | null;
  phase: EmploymentPhase;
  /**
   * Koniec pracy u klienta: koniec łańcucha zamówień bez kontynuacji albo
   * wcześniejsza data końca wypowiedzianej umowy; może być w przeszłości
   * (zamówienia się skończyły, umowa trwa). Brak = bez daty końca.
   */
  order_end_date?: string | null;
  /** Tylko faza `starting`: umowa podpisana, start w przyszłości. */
  starts_on?: string | null;
  delivery_lead_name?: string | null;
}

export interface EmploymentMarker {
  phase: EmploymentPhase;
  /** Zawsze `contract` (17.10.2026) — „Pracuje u nas” daje tylko umowa. */
  source: "contract";
  /**
   * Liczone tylko w kontekście rekrutacji: `true` = któryś klient znacznika
   * jest inny niż klient tej rekrutacji, `false` = to klient tej rekrutacji.
   */
  elsewhere?: boolean | null;
  clients: EmploymentMarkerClient[];
  /**
   * Pierwszy dzień po pracy u nas (15.10.2026). Termin dostępności czyta
   * `lib/contract-availability.ts`.
   */
  free_from?: string | null;
  free_from_basis?: "work_end" | "no_end_date" | "starting" | null;
  /**
   * „Wraca na rynek DD.MM” (22.10.2026): opieka przekazała osobę do front
   * office albo zdecydowała „przekaż” na każdej trwającej umowie
   * (`employment_marker.mark_returning`). Data = koniec pracy; brak = nieznany.
   */
  returns_to_market?: boolean;
  returns_to_market_on?: string | null;
  /** Żywa umowa bez trwającego ani zaplanowanego zamówienia (09.11.2026). */
  no_current_order?: boolean;
}

export type EmploymentMarkerTone = "danger" | "neutral" | "info";

function clientName(client: EmploymentMarkerClient): string | null {
  const name = client.client_name?.trim();
  if (name) return name;
  return client.client_id != null ? `Klient #${client.client_id}` : null;
}

function shortDate(iso: string): string {
  // DD.MM.RRRR → DD.MM (karta Tablicy ma ~170 px).
  return formatIsoDatePl(iso).slice(0, 5);
}

export interface MarkerLabelOptions {
  /** Karta Tablicy (~170 px): samo polecenie. */
  short?: boolean;
}

/**
 * Tekst pigułki (decyzja Artura 09.11.2026): rekruter dostaje informację, czy
 * może dzwonić, bez daty końca. Końcem zamówień zajmuje się osobny dział,
 * a „do 31.12” czytano jak termin dostępności.
 */
export function markerLabel(marker: EmploymentMarker, options: MarkerLabelOptions = {}): string {
  const returning = returnsToMarketLabel(marker);
  if (returning) return returning;
  if (marker.no_current_order) return options.short ? "Bez zamówienia" : "Bez aktywnego zamówienia";
  if (options.short) return "Nie dzwoń";
  return marker.phase === "starting" ? "Zaczyna u nas · nie dzwoń" : "Aktywne zamówienie · nie dzwoń";
}

export function markerTone(marker: EmploymentMarker): EmploymentMarkerTone {
  if (marker.returns_to_market) return "info";
  return marker.no_current_order ? "neutral" : "danger";
}

/** Zdanie w dymku pigułki: dlaczego taka plakietka i kto się tym zajmuje. */
export function markerCallHint(marker: EmploymentMarker): string {
  if (marker.returns_to_market) {
    return "Opieka przekazała osobę do front office. Po końcu pracy u nas szuka nowego projektu.";
  }
  if (marker.no_current_order) {
    return "Osoba ma umowę, ale żadnego trwającego zamówienia. Takimi osobami zajmuje się osobny dział.";
  }
  if (marker.phase === "starting") {
    return "Umowa podpisana, praca jeszcze się nie zaczęła. Nie dzwoń z nowym projektem.";
  }
  return "Nie dzwoń do tej osoby z nowym projektem. Końcem zamówień i powrotem na rynek zajmuje się osobny dział.";
}

/** Osoba już u nas pracuje (umowa od przyszłego miesiąca jeszcze się nie liczy). */
export function worksForUsNow(marker: EmploymentMarker | null | undefined): boolean {
  return marker != null && marker.phase !== "starting";
}

/**
 * Plakietka dopuszczalności „Kandydat obecnie pracuje u tego klienta” mówi to
 * samo co znacznik klienta rekrutacji — obok siebie byłyby dublem.
 */
export function markerCoversEligibility(
  marker: EmploymentMarker | null | undefined,
  reasonCode: string | null | undefined,
): boolean {
  return marker?.elsewhere === false && reasonCode === "client_current_employment";
}

/**
 * Plakietka przy rekrutacji na liście „Przypisz do rekrutacji”: klient tej
 * rekrutacji to klient, u którego osoba już pracuje albo zaczyna.
 */
export function sameClientNote(
  marker: EmploymentMarker | null | undefined,
  clientId: number | null | undefined,
): string | null {
  if (!marker || clientId == null) return null;
  const match = marker.clients.find((client) => client.client_id === clientId);
  if (!match) return null;
  return match.phase === "starting"
    ? "Ten sam klient, u którego zaczyna"
    : "Ten sam klient, u którego pracuje";
}

export interface MarkerDetailLine {
  key: string;
  title: string;
  detail: string;
  contractId: number | null;
}

/**
 * Wiersze ramki: jeden na klienta, z Delivery Leadem. Daty widzi tylko osoba
 * z dostępem do Delivery (`showDates`), rekruterowi są niepotrzebne.
 */
export function markerDetails(
  marker: EmploymentMarker,
  { showDates = false }: { showDates?: boolean } = {},
): MarkerDetailLine[] {
  return marker.clients.map((client, index) => {
    const name = clientName(client);
    const parts: string[] = [];
    if (showDates) {
      if (client.phase === "starting") {
        if (client.starts_on) parts.push(`Start ${formatIsoDatePl(client.starts_on)}`);
      } else if (client.order_end_date) {
        parts.push(`Zamówienie do ${formatIsoDatePl(client.order_end_date)}`);
      } else {
        parts.push("Zamówienie bez daty końca");
      }
    }
    if (client.delivery_lead_name) parts.push(`Delivery Lead: ${client.delivery_lead_name}`);
    const headline = marker.no_current_order
      ? "Bez aktywnego zamówienia"
      : client.phase === "starting"
        ? "Zaczyna u nas · nie dzwoń"
        : "Aktywne zamówienie · nie dzwoń";
    return {
      key: `${client.client_id ?? "x"}:${client.contract_id ?? index}`,
      title: [headline, name].filter(Boolean).join(" · "),
      detail: parts.join(" · "),
      contractId: client.contract_id ?? null,
    };
  });
}

/** „2 z 4 osób pracują u nas” — nagłówek ramki w oknach dodawania. */
export function employedCountLabel(employed: number, total: number): string {
  return `${employed} z ${total} osób ${pluralPl(employed, "pracuje", "pracują", "pracuje")} u nas`;
}

/** „Wraca na rynek 30.11” (albo bez daty) — plakietka obok znacznika; `null` = brak. */
export function returnsToMarketLabel(marker: EmploymentMarker | null | undefined): string | null {
  if (!marker?.returns_to_market) return null;
  return marker.returns_to_market_on
    ? `Wraca na rynek ${shortDate(marker.returns_to_market_on)}`
    : "Wraca na rynek";
}
