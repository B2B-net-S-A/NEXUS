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
}

export type EmploymentMarkerTone = "success" | "warning" | "info";

const HEADLINE: Record<EmploymentPhase, string> = {
  working: "Pracuje u nas",
  ending: "Kończy u nas",
  starting: "Zaczyna u nas",
};

const SAME_CLIENT_HEADLINE: Record<EmploymentPhase, string> = {
  working: "Pracuje u tego klienta",
  ending: "Kończy u tego klienta",
  starting: "Zaczyna u tego klienta",
};

function clientName(client: EmploymentMarkerClient): string | null {
  const name = client.client_name?.trim();
  if (name) return name;
  return client.client_id != null ? `Klient #${client.client_id}` : null;
}

/** Klienci, o których mówi nagłówek: przy „pracuje” bez tych z przyszłym startem. */
function headlineClients(marker: EmploymentMarker): EmploymentMarkerClient[] {
  if (marker.phase === "working") return marker.clients.filter((c) => c.phase !== "starting");
  return marker.clients.filter((c) => c.phase === marker.phase);
}

function shortDate(iso: string): string {
  // DD.MM.RRRR → DD.MM (karta Tablicy ma ~170 px).
  return formatIsoDatePl(iso).slice(0, 5);
}

export interface MarkerLabelOptions {
  /** `names` (domyślnie): do dwóch nazw, powyżej liczba; `count`: liczba od dwóch; `none`: bez klienta. */
  clients?: "names" | "count" | "none";
  date?: "full" | "short";
}

/** Tekst pigułki, np. „Pracuje u nas · Bank · do 31.12.2026”. */
export function markerLabel(marker: EmploymentMarker, options: MarkerLabelOptions = {}): string {
  const sameClient = marker.elsewhere === false;
  const clients = headlineClients(marker);
  const single = clients.length === 1 ? clients[0] : null;
  const formatDate = options.date === "short" ? shortDate : formatIsoDatePl;

  let headline = (sameClient ? SAME_CLIENT_HEADLINE : HEADLINE)[marker.phase];
  let tail: string | null = null;
  if (single) {
    if (marker.phase === "working" && single.order_end_date) {
      tail = `do ${formatDate(single.order_end_date)}`;
    } else if (marker.phase === "ending" && single.order_end_date) {
      headline = `${headline} ${formatDate(single.order_end_date)}`;
    } else if (marker.phase === "starting" && single.starts_on) {
      headline = `${headline} ${formatDate(single.starts_on)}`;
    }
  }

  let who: string | null = null;
  const mode = sameClient ? "none" : (options.clients ?? "names");
  if (mode !== "none") {
    const names = clients.map(clientName).filter((name): name is string => name !== null);
    if (names.length === 1) {
      who = names[0];
    } else if (names.length > 2 || (mode === "count" && names.length > 1)) {
      who = `${names.length} ${pluralPl(names.length, "klienta", "klientów", "klientów")}`;
    } else if (names.length === 2) {
      who = names.join(", ");
    }
  }
  return [headline, who, tail].filter(Boolean).join(" · ");
}

export function markerTone(marker: EmploymentMarker): EmploymentMarkerTone {
  if (marker.elsewhere === false || marker.phase === "ending") return "warning";
  return marker.phase === "starting" ? "info" : "success";
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

/** Wiersze ramki: jeden na klienta, z końcem zamówienia i Delivery Leadem. */
export function markerDetails(marker: EmploymentMarker): MarkerDetailLine[] {
  return marker.clients.map((client, index) => {
    const name = clientName(client);
    const parts: string[] = [];
    if (client.phase === "starting") {
      if (client.starts_on) parts.push(`Start ${formatIsoDatePl(client.starts_on)}`);
    } else if (client.order_end_date) {
      parts.push(`Zamówienie do ${formatIsoDatePl(client.order_end_date)}`);
    } else {
      parts.push("Zamówienie bez daty końca");
    }
    if (client.delivery_lead_name) parts.push(`Delivery Lead: ${client.delivery_lead_name}`);
    return {
      key: `${client.client_id ?? "x"}:${client.contract_id ?? index}`,
      title: [HEADLINE[client.phase], name].filter(Boolean).join(" · "),
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
