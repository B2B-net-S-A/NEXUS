// Mapa strony Ustawienia (przebudowa 22.09.2026, propozycja „kafelki").
//
// Ustawienia to JEDNO wejście: strona startowa z pięcioma obszarami, w obszarze
// krótka lista pozycji, w pozycji — sam ekran. Ten plik jest jedynym miejscem,
// które mówi, co istnieje, gdzie leży i kto to widzi. Czytają go strona
// `/settings` (kafelki, lista, wyszukiwarka) i layout podstron (ścieżka
// „Ustawienia / Obszar / Pozycja" nad `/settings/cv-rules` itd.).
//
// Pozycje z `hidden: true` NIE są listowane ani wyszukiwane (decyzja Artura
// 22.09.2026: raporty, narzędzia techniczne, Konflikty, Coaching, Pomoc i Teams
// znikają z menu), ale dalej otwierają się pod adresem — stare linki działają.
import { hasRole, type UserRole } from "@/store/auth";
import { hasCapability, type Capability } from "@/lib/capabilities";
import {
  hasSectionAccess,
  type ProductSection,
  type SectionAccess,
} from "@/lib/section-access";

export type SettingsAreaId = "me" | "team" | "rec" | "deals" | "sys";

export interface SettingsArea {
  id: SettingsAreaId;
  name: string;
  hint: string;
}

export const SETTINGS_AREAS: readonly SettingsArea[] = [
  { id: "me", name: "Moje konto", hint: "Outlook, kalendarz i moje powiadomienia" },
  { id: "team", name: "Zespół i dostęp", hint: "Kto ma konto, co widzi i którego klienta prowadzi" },
  { id: "rec", name: "Rekrutacja", hint: "Etapy, CV dla klientów, ranking, maile" },
  { id: "deals", name: "Umowy i stawki", hint: "Wzory umów, stawki rynkowe" },
  { id: "sys", name: "System", hint: "Powiadomienia, AI, Traffit, listy wyboru, historia zdarzeń, wykluczone placementy" },
] as const;

export type SettingsItemId =
  | "outlook"
  | "my-notifications"
  | "people"
  | "assign"
  | "stages"
  | "cv"
  | "ranking"
  | "mail"
  | "contracts"
  | "rates"
  | "ai"
  | "traffit"
  | "fireflies"
  | "dict"
  | "fields"
  | "history"
  | "placements"
  | "notifications"
  // Ukryte — tylko pod adresem.
  | "teams"
  | "coaching"
  | "conflicts"
  | "help"
  | "advanced";

type Gate = {
  roles?: UserRole[];
  /** Capability z `lib/capabilities.ts` — lustro strażnika backendu. */
  capability?: Capability;
  section?: ProductSection;
  required?: Exclude<SectionAccess, "none">;
  /** Rola Finanse bez admina widzi tylko pozycje z tą flagą. */
  finance?: boolean;
};

export interface SettingsItem {
  id: SettingsItemId;
  area: SettingsAreaId;
  title: string;
  description: string;
  keywords: string;
  /** Osobna trasa (np. `/settings/cv-rules`). Brak = ekran w `/settings?item=`. */
  route?: string;
  hidden?: boolean;
  /** Ekran z tabelą — szerszy kontener. */
  wide?: boolean;
  /** Komponent ekranu ma własny nagłówek — strona rysuje tylko ścieżkę,
   *  inaczej ten sam ekran miałby dwa tytuły jeden pod drugim. */
  ownHeader?: boolean;
  gate: Gate;
}

type SettingsUser = Parameters<typeof hasRole>[0] &
  Parameters<typeof hasSectionAccess>[0];

export const SETTINGS_ITEMS: readonly SettingsItem[] = [
  {
    id: "outlook", area: "me", title: "Outlook i kalendarz",
    description: "Podłącz swoją skrzynkę i kalendarz Microsoft 365.",
    keywords: "poczta mail m365 microsoft skrzynka integracje",
    // Finanse też tworzą wydarzenia w kalendarzu (audyt ról U6, 22.09).
    gate: { finance: true },
  },
  {
    id: "my-notifications", area: "me", title: "Moje powiadomienia",
    description: "Wybierz, które powiadomienia mają do Ciebie trafiać.",
    keywords: "powiadomienia dzwonek wycisz wylacz alerty przypomnienia kategorie",
    gate: {},
  },
  {
    id: "people", area: "team", title: "Osoby i role",
    description: "Dodaj osobę, zmień jej rolę i dostęp albo wyłącz konto.",
    keywords: "uzytkownicy konta uprawnienia dostep haslo rola administracja",
    wide: true,
    gate: { roles: ["admin"] },
  },
  {
    id: "assign", area: "team", title: "Kto prowadzi którego klienta",
    description: "Przypisania Delivery Leadów do klientów i kompetencje zespołu.",
    keywords: "dl delivery portfel kompetencje przypisania odpowiedzialnosci",
    route: "/settings/team-structure",
    gate: { roles: ["admin", "head_of_recruitment", "finance"], finance: true },
  },
  {
    id: "stages", area: "rec", title: "Procesy rekrutacyjne",
    description: "Etapy (kolumny tablicy) i ich kolejność dla rekrutacji.",
    keywords: "pipeline procesy kanban kolumny etapy szablony",
    wide: true, ownHeader: true,
    gate: { roles: ["admin", "delivery_lead"], section: "pipeline", required: "write" },
  },
  {
    id: "cv", area: "rec", title: "Reguły CV klientów",
    description: "Jak ma wyglądać CV wysyłane do danego klienta.",
    keywords: "generator cv plik jezyk klient reguly karta",
    route: "/settings/cv-rules",
    gate: { roles: ["admin", "delivery_lead"], section: "delivery", required: "write" },
  },
  {
    id: "ranking", area: "rec", title: "Ranking kandydatów",
    description: "Co liczy się najbardziej przy dopasowaniu kandydata.",
    keywords: "scoring wagi dopasowanie ranking profile",
    route: "/settings/scoring",
    gate: { roles: ["admin", "delivery_lead"], section: "insights", required: "read" },
  },
  {
    id: "mail", area: "rec", title: "Szablony maili",
    description: "Treści maili do kandydatów, także odrzucenia.",
    keywords: "email odrzucenie outreach szablony wiadomosci",
    // Zapis szablonu = `require_candidate_write` (emails.py) — każdy rekruter;
    // do 22.09 pozycję widział tylko admin (audyt ról U10).
    gate: { capability: "candidate.write" },
  },
  {
    id: "contracts", area: "deals", title: "Wzory umów",
    description: "Treść umów B2B używanych przez generator.",
    keywords: "umowa b2b szablon generator kontrakt",
    route: "/settings/contract-templates",
    gate: { roles: ["admin", "finance"], section: "finance", finance: true },
  },
  {
    id: "rates", area: "deals", title: "Stawki rynkowe",
    description: "Widełki rynkowe dla ról — punkt odniesienia przy wycenie.",
    keywords: "benchmark wycena stawki rynek",
    route: "/settings/rate-benchmarks",
    gate: { roles: ["admin", "finance"], section: "finance", finance: true },
  },
  {
    id: "notifications", area: "sys", title: "Powiadomienia",
    description: "Co uruchamia automatyczne maile, kto je otrzymuje i które są włączone.",
    keywords: "powiadomienia email maile wysylka nadawca odbiorcy kolejka",
    wide: true,
    gate: { roles: ["admin"], section: "system_admin" },
  },
  {
    id: "ai", area: "sys", title: "Koszty AI",
    description: "Który model robi co i ile to kosztuje w tym miesiącu.",
    keywords: "model claude limit alarm ai koszty funkcje",
    route: "/settings/ai",
    gate: { roles: ["admin"], section: "system_admin" },
  },
  {
    id: "traffit", area: "sys", title: "Import z Traffita",
    description: "Czy nocny import przeszedł bez błędów.",
    keywords: "traffit synchronizacja import",
    gate: { roles: ["admin"] },
  },
  {
    id: "fireflies", area: "sys", title: "Notatki ze spotkań",
    description: "Transkrypcje z Fireflies w profilach kandydatów.",
    keywords: "fireflies spotkania notatki transkrypcje",
    gate: { roles: ["admin"], section: "sourcing" },
  },
  {
    id: "dict", area: "sys", title: "Listy wyboru",
    description: "Branże, powody odrzucenia i inne wartości list.",
    keywords: "slowniki branze powody taksonomie",
    route: "/settings/dictionaries",
    gate: { roles: ["admin"], section: "system_admin" },
  },
  {
    id: "fields", area: "sys", title: "Dodatkowe pola",
    description: "Własne pola na profilu kandydata i rekrutacji.",
    keywords: "pola konfiguracja formularz",
    route: "/settings/entity-fields",
    gate: { roles: ["admin"], section: "system_admin" },
  },
  {
    id: "history", area: "sys", title: "Historia zdarzeń",
    description: "Kto co usunął i które próby zostały zablokowane.",
    keywords: "zdarzenia audyt log historia usuniecia",
    wide: true, ownHeader: true,
    gate: { roles: ["admin", "finance"], section: "finance", finance: true },
  },
  {
    id: "placements", area: "sys", title: "Wykluczone placementy",
    description: "Zatrudnienia z masowych serii bez CV, które nie liczą się w statystykach.",
    keywords: "placementy zatrudnieni statystyki wykluczenia seria kpi insights",
    wide: true, ownHeader: true,
    gate: { roles: ["admin"] },
  },
  // ── Ukryte (tylko pod adresem) ────────────────────────────────────────────
  {
    id: "teams", area: "me", title: "Powiadomienia Teams",
    description: "Powiadomienia NEXUSA w Microsoft Teams.",
    keywords: "", hidden: true, gate: { finance: true },
  },
  {
    id: "coaching", area: "me", title: "Coaching KPI",
    description: "Pochwały i przypomnienia o celach KPI.",
    keywords: "", hidden: true, gate: {},
  },
  {
    id: "conflicts", area: "team", title: "Konflikty",
    description: "Rejestr konfliktów kandydat ↔ klient.",
    keywords: "", hidden: true, wide: true, ownHeader: true,
    gate: { roles: ["admin", "delivery_lead", "head_of_recruitment"], section: "sourcing" },
  },
  {
    id: "help", area: "me", title: "Przewodnik i skróty",
    description: "Pokaż ponownie przewodnik po NEXUSIE.",
    keywords: "", hidden: true, gate: { finance: true },
  },
  {
    id: "advanced", area: "sys", title: "Pozostałe narzędzia",
    description: "Raporty i narzędzia techniczne dostępne pod adresem.",
    keywords: "", hidden: true, gate: { finance: true },
  },
];

/** Finanse bez admina widzą wyłącznie powierzchnie tylko do odczytu. */
export function isFinanceReadOnly(user: SettingsUser | null): boolean {
  return hasRole(user, "finance") && !hasRole(user, "admin");
}

export function canSeeSettingsItem(user: SettingsUser | null, item: SettingsItem): boolean {
  if (!user) return false;
  const { gate } = item;
  if (isFinanceReadOnly(user) && !gate.finance) return false;
  if (gate.roles && !hasRole(user, ...gate.roles)) return false;
  if (gate.capability && !hasCapability(user, gate.capability)) return false;
  if (gate.section && !hasSectionAccess(user, gate.section, gate.required ?? "read")) return false;
  return true;
}

/** Pozycje widoczne w menu (bez ukrytych). */
export function listedSettingsItems(user: SettingsUser | null): SettingsItem[] {
  return SETTINGS_ITEMS.filter((i) => !i.hidden && canSeeSettingsItem(user, i));
}

export function listedSettingsAreas(user: SettingsUser | null): SettingsArea[] {
  const items = listedSettingsItems(user);
  return SETTINGS_AREAS.filter((a) => items.some((i) => i.area === a.id));
}

export function findSettingsItem(id: string | null | undefined): SettingsItem | undefined {
  return id ? SETTINGS_ITEMS.find((i) => i.id === id) : undefined;
}

export function findSettingsArea(id: string | null | undefined): SettingsArea | undefined {
  return id ? SETTINGS_AREAS.find((a) => a.id === id) : undefined;
}

/** Pozycja z osobną trasą, której adres zaczyna się od `pathname`. */
export function findSettingsItemByRoute(pathname: string): SettingsItem | undefined {
  return SETTINGS_ITEMS.find(
    (i) => i.route && (pathname === i.route || pathname.startsWith(`${i.route}/`)),
  );
}

export function settingsItemHref(item: SettingsItem): string {
  return item.route ?? `/settings?item=${item.id}`;
}

/** Stare `?tab=` (do 22.09.2026) → nowa pozycja. Linki są w kodzie, w
 *  powiadomieniach i w zakładkach przeglądarki — nie usuwaj. */
export const LEGACY_SETTINGS_TABS: Readonly<Record<string, SettingsItemId>> = {
  integracje: "outlook",
  szablony: "mail",
  coaching: "coaching",
  procesy: "stages",
  administracja: "people",
  historia: "history",
  konflikty: "conflicts",
  zaawansowane: "advanced",
  pomoc: "help",
};

export type SettingsView =
  | { kind: "home" }
  | { kind: "area"; area: SettingsArea }
  | { kind: "item"; item: SettingsItem; area: SettingsArea };

/** Widok strony `/settings` z parametrów adresu. Pozycja, której użytkownik
 *  nie może zobaczyć (albo z własną trasą), wraca do strony startowej. */
export function resolveSettingsView(
  user: SettingsUser | null,
  params: { item?: string | null; area?: string | null; tab?: string | null },
): SettingsView {
  const itemId = params.item ?? (params.tab ? LEGACY_SETTINGS_TABS[params.tab] : undefined);
  const item = findSettingsItem(itemId);
  if (item && !item.route && canSeeSettingsItem(user, item)) {
    return { kind: "item", item, area: findSettingsArea(item.area)! };
  }
  const area = findSettingsArea(params.area);
  if (area && listedSettingsAreas(user).some((a) => a.id === area.id)) {
    return { kind: "area", area };
  }
  return { kind: "home" };
}

const normalize = (s: string) =>
  s.toLowerCase().replace(/ł/g, "l").normalize("NFD").replace(/[̀-ͯ]/g, "");

/** Słowo zapytania pasuje, gdy występuje w tekście albo gdy jakieś słowo
 *  tekstu zaczyna się od jego rdzenia — polska odmiana („regula" → „reguły",
 *  „usunięcie" → „usunięć") nie może dawać pustego wyniku. */
function termMatches(term: string, hay: string, words: string[]): boolean {
  if (hay.includes(term)) return true;
  if (term.length < 4) return false;
  const stem = term.slice(0, Math.max(4, term.length - 2));
  return words.some((w) => w.startsWith(stem));
}

/** Wyszukiwarka: każde słowo zapytania musi pasować do tytułu, opisu,
 *  słów kluczowych albo nazwy obszaru (bez polskich znaków). */
export function searchSettingsItems(user: SettingsUser | null, query: string): SettingsItem[] {
  const terms = normalize(query).trim().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return [];
  return listedSettingsItems(user).filter((i) => {
    const hay = normalize(
      `${i.title} ${i.description} ${i.keywords} ${findSettingsArea(i.area)?.name ?? ""}`,
    );
    const words = hay.split(/[^a-z0-9]+/).filter(Boolean);
    return terms.every((t) => termMatches(t, hay, words));
  });
}
