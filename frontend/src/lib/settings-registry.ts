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
import { hasPermission, type Permission } from "@/lib/permissions";
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
  { id: "sys", name: "System", hint: "Powiadomienia, AI, klucze API, portale ogłoszeniowe, importy, historia zdarzeń, wykluczone placementy" },
] as const;

export type SettingsItemId =
  | "outlook"
  | "my-notifications"
  | "people"
  | "hr"
  | "payroll"
  | "hr-import"
  | "assign"
  | "competence-team"
  | "stages"
  | "cv"
  | "ranking"
  | "prep-review"
  | "kpi-targets"
  | "mail"
  | "skills"
  | "skills-review"
  | "job-ad-blocks"
  | "roles"
  | "trainee-rules"
  | "contracts"
  | "rates"
  | "register-import"
  | "contract-docs-sharepoint"
  | "ai"
  | "qc-quality"
  | "api-keys"
  | "traffit"
  | "job-boards"
  | "teams-prep"
  | "dict"
  | "fields"
  | "history"
  | "placements"
  | "imports"
  | "integrations"
  | "notifications"
  // Ukryte — tylko pod adresem.
  | "teams"
  | "coaching"
  | "conflicts"
  | "help"
  | "advanced";

type Gate = {
  roles?: UserRole[];
  /**
   * Uprawnienie z ekranu Osoby i role (`lib/permissions.ts`), o które pyta
   * trasa backendu. Pozycję widzi każdy jego posiadacz — także rola Finanse,
   * jeśli administrator jej je nadał (filtr `finance` go nie zasłania).
   */
  permission?: Permission;
  /** Capability z `lib/capabilities.ts` — lustro strażnika backendu. */
  capability?: Capability;
  section?: ProductSection;
  required?: Exclude<SectionAccess, "none">;
  /** Rola Finanse bez admina widzi tylko pozycje z tą flagą. */
  finance?: boolean;
  /**
   * Pozycja programu „Ludzie w NEXUSIE” — widoczna tylko przy włączonym
   * programie (`program` z `/api/hr/config`); wyłączony = nie widzi jej nikt.
   */
  hrProgram?: boolean;
};

export interface SettingsItem {
  id: SettingsItemId;
  area: SettingsAreaId;
  title: string;
  /** Grupa w obszarze (lewa kolumna i lista obszaru, 20.10.2026). Pozycje
   *  ukryte z menu mogą jej nie mieć. Kolejność grup = kolejność w tym pliku. */
  group?: string;
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
  Parameters<typeof hasCapability>[0];

export const SETTINGS_ITEMS: readonly SettingsItem[] = [
  {
    id: "outlook", area: "me", title: "Outlook i kalendarz", group: "Moje",
    description: "Podłącz swoją skrzynkę i kalendarz Microsoft 365.",
    keywords: "poczta mail m365 microsoft skrzynka integracje",
    // Od 20.10.2026 część ekranu „Moje konto” — pod adresem dalej sama karta.
    hidden: true,
    // Finanse też tworzą wydarzenia w kalendarzu (audyt ról U6, 22.09).
    gate: { finance: true },
  },
  {
    // „Moje konto” (20.10.2026): skrzynka Microsoft 365 i moje powiadomienia na
    // jednym ekranie. Id zostaje — dzwonek i maile linkują `?item=my-notifications`.
    id: "my-notifications", area: "me", title: "Moje konto", group: "Moje",
    description: "Twoja skrzynka Microsoft 365 i powiadomienia, które mają do Ciebie trafiać.",
    keywords:
      "powiadomienia dzwonek wycisz wylacz alerty przypomnienia kategorie poczta mail m365 microsoft skrzynka outlook kalendarz integracje",
    // Runda 9 (R9-N13-4): `/api/notifications/preferences` jest otwarte dla
    // każdego zalogowanego (CurrentUser) — Finanse też dostają powiadomienia.
    gate: { finance: true },
  },
  {
    id: "people", area: "team", title: "Osoby i role", group: "Konta",
    description: "Dodaj osobę, zmień jej rolę i dostęp albo wyłącz konto.",
    keywords: "uzytkownicy konta uprawnienia dostep haslo rola administracja",
    wide: true,
    gate: { roles: ["admin"] },
  },
  {
    // „Ludzie w NEXUSIE” (16.10.2026): dni wolne firmy (Kadry) i przełączniki
    // modułów (admin) — trasy `/api/hr/admin/*` stoją za uprawnieniem Kadry.
    id: "hr", area: "team", title: "Kadry", group: "Ludzie w NEXUSIE",
    description: "Dni wolne firmy i moduły „Ludzi w NEXUSIE” (urlopy, czas pracy, płace, sprzęt).",
    keywords: "kadry hr urlopy dni wolne swieta moduly ludzie kartoteka",
    route: "/settings/hr",
    gate: { permission: "people_admin", hrProgram: true },
  },
  {
    // Reguły premii (17.10.2026) — `/api/hr/payroll/rules` stoi za uprawnieniem
    // „Płace” (Finanse z roli, admin zawsze). Do 17.10 karta była w „Kadrach”,
    // których osoba z samymi „Płacami” nie widziała.
    id: "payroll", area: "team", title: "Płace", group: "Ludzie w NEXUSIE",
    description: "Reguły premii z placementów i z Ligi Mistrzów: progi marży, premia Delivery Leada, dodatkowe premie.",
    keywords: "place premie premia placementy liga mistrzow progi marza wynagrodzenia wyplaty bonus",
    route: "/settings/payroll",
    gate: { permission: "payroll", hrProgram: true },
  },
  {
    // „Ludzie w NEXUSIE” (17.10.2026): import paczki z Compassa — na sucho
    // Kadry i admin, zapis tylko admin (`/api/hr/admin/import`).
    id: "hr-import", area: "team", title: "Import z Compassa", group: "Ludzie w NEXUSIE",
    description: "Paczka eksportu Compassa: sprawdzenie na sucho, zapis wybranych modułów i historia partii.",
    keywords: "import compass paczka kadry urlopy timesheety place migracja przelaczenie na sucho",
    route: "/settings/hr-import",
    wide: true,
    gate: { permission: "people_admin", hrProgram: true },
  },
  {
    id: "competence-team", area: "team", title: "Kategorie kompetencji", group: "Zespół rekrutacji",
    description: "Kto należy do której kategorii (1. i 2. priorytet) i zasady przydziału requestów.",
    keywords: "kategorie kompetencji przydzial requesty obłożenie oblozenie priorytet poza przydzialem sourcer rekruter",
    route: "/settings/competence-team",
    // Od 20.10.2026 zakładka „Kategorie” pozycji „Zespół rekrutacji”; adres
    // przekierowuje na nią.
    hidden: true,
    gate: { roles: ["admin", "head_of_recruitment"] },
  },
  {
    // „Zespół rekrutacji” (20.10.2026): kategorie kompetencji i Delivery Leadzi
    // z klientami w jednej pozycji — dwa ekrany zapisywały te same priorytety 1/2.
    id: "assign", area: "team", title: "Zespół rekrutacji", group: "Zespół rekrutacji",
    description: "Kto szuka w której kategorii i którego klienta prowadzi Delivery Lead.",
    keywords:
      "dl delivery portfel kompetencje przypisania odpowiedzialnosci kategorie kompetencji przydzial requesty obłożenie oblozenie priorytet poza przydzialem sourcer rekruter klienci",
    route: "/settings/team-structure",
    gate: { roles: ["admin", "head_of_recruitment", "finance"], finance: true },
  },
  {
    id: "stages", area: "rec", title: "Procesy rekrutacyjne", group: "Proces",
    description: "Etapy (kolumny tablicy) i ich kolejność dla rekrutacji.",
    keywords: "pipeline procesy kanban kolumny etapy szablony",
    wide: true, ownHeader: true,
    gate: { roles: ["admin", "delivery_lead"], section: "pipeline", required: "write" },
  },
  {
    id: "cv", area: "rec", title: "Reguły CV klientów", group: "Klienci",
    description: "Jak ma wyglądać CV wysyłane do danego klienta.",
    keywords: "generator cv plik jezyk klient reguly karta",
    route: "/settings/cv-rules",
    // Zapis reguły i karty klienta = „Klienci: dodawanie i edycja” (lustro
    // capability `cv_rule.manage`); sekcja Delivery zostaje sufitem.
    gate: { permission: "clients_edit", section: "delivery", required: "write" },
  },
  {
    id: "ranking", area: "rec", title: "Ranking kandydatów", group: "Proces",
    description: "Co liczy się najbardziej przy dopasowaniu kandydata.",
    keywords: "scoring wagi dopasowanie ranking profile",
    route: "/settings/scoring",
    // Lustro `WeightsReader` (scoring_weights.py) + middleware. Szkic i
    // publikację wag robi admin albo HoR z zapisem Insights (decyzja D1).
    gate: {
      roles: ["admin", "delivery_lead", "head_of_recruitment"],
      section: "insights",
      required: "read",
    },
  },
  {
    id: "prep-review", area: "rec", title: "Ocena prepów", group: "Proces",
    description: "Jak oceniamy Prep 1 i Prep 2: kryteria, wagi, skala odpowiedzi.",
    keywords: "prep follow-up ocena transkrypt teams wagi tematy kandydat",
    route: "/settings/prep-review",
    // Publikuje HoR i admin (`can_edit` z serwera). W menu bez rekrutera —
    // jego Ustawienia to samo „Moje konto”; stronę otwiera linkiem „Jak
    // liczona jest ocena” z oceny prepu (middleware i `ConfigReader` go wpuszczają).
    gate: {
      roles: ["admin", "delivery_lead", "head_of_recruitment"],
      section: "pipeline",
      required: "read",
    },
  },
  {
    id: "kpi-targets", area: "rec", title: "Cele KPI", group: "Proces",
    description: "Cele weryfikacji, rekomendacji i placementów dla ról i osób.",
    keywords: "kpi cele targety wyscig progi weryfikacje placementy precyzja",
    route: "/settings/kpi-targets",
    // Lustro `HeadOfRecruitmentPlus` + zapis sekcji Insights (plan PR3).
    gate: { roles: ["admin", "head_of_recruitment"], section: "insights", required: "write" },
  },
  {
    id: "mail", area: "rec", title: "Szablony maili", group: "Teksty",
    description: "Treści maili do kandydatów, także odrzucenia.",
    keywords: "email odrzucenie outreach szablony wiadomosci",
    // Zapis szablonu = `require_candidate_write` (emails.py) — każdy rekruter;
    // do 22.09 pozycję widział tylko admin (audyt ról U10).
    gate: { capability: "candidate.write" },
  },
  {
    id: "skills", area: "rec", title: "Słownik umiejętności", group: "Wiedza",
    description: "Technologie i ich aliasy rozpoznawane w CV i wyszukiwarce.",
    keywords: "umiejetnosci skille technologie aliasy taksonomia slownik cortex",
    // `/api/skills-admin`: HeadOfRecruitmentPlus + zapis sekcji Sourcing.
    gate: { roles: ["admin", "head_of_recruitment"], section: "sourcing", required: "write" },
  },
  {
    // Kolejka nazw technologii z rozmów opieki (22.10.2026, dawna zakładka
    // Opieki „Technologie”). Admin i HoR mają ją w „Słowniku umiejętności”
    // (zakładka „Nazwy z rozmów”); TCM, który decyduje o nazwach
    // (`care_gates.can_curate`), do Słownika nie wchodzi — stąd ta pozycja.
    // Lustro `require_hr_care_skill_curator` (rola + moduł opieki).
    id: "skills-review", area: "rec", title: "Nazwy z rozmów do przejrzenia", group: "Wiedza",
    description: "Technologie z rozmów opiekunów, których słownik umiejętności nie zna.",
    keywords: "technologie nazwy rozmowy opieka slownik umiejetnosci zmapuj alias karta technologiczna",
    gate: { roles: ["talent_community_manager"], hrProgram: true },
  },
  {
    id: "job-ad-blocks", area: "rec", title: "Stałe części ogłoszenia", group: "Teksty",
    description: "„Co oferujemy”, etapy procesu i dopisek do tytułu w ogłoszeniach na Pracuj.pl i JustJoin.IT.",
    keywords: "ogloszenie pracuj justjoin jjit oferujemy benefity proces tytul dopisek stale bloki",
    // `/api/job-ads/fixed-blocks`: HeadOfRecruitmentPlus + zapis sekcji Pipeline.
    gate: { roles: ["admin", "head_of_recruitment"], section: "pipeline", required: "write" },
  },
  {
    id: "roles", area: "rec", title: "Biblioteka ról", group: "Wiedza",
    description: "Opisy ról po ludzku, z których korzysta wyjaśnienie rekrutacji.",
    keywords: "role biblioteka po ludzku opis stanowiska wyjasnienie champion",
    // `/api/role-profiles` (zapis): admin + Head of Recruitment — ta sama
    // bramka co Słownik umiejętności, obok którego żyje słowniczek „Po ludzku”.
    gate: { roles: ["admin", "head_of_recruitment"], section: "sourcing", required: "write" },
  },
  {
    id: "trainee-rules", area: "rec", title: "Lista telefonów praktykantów", group: "Proces",
    description: "Kto trafia na codzienną listę telefonów praktykantów.",
    keywords: "praktykant praktykanci telefony lista reguly pula stawka dostepnosc",
    route: "/settings/trainee-rules",
    // `/api/trainee/rules` = admin + Head of Recruitment (0374).
    // Ukryte 17.10.2026 razem z panelem „Praktykanci” (decyzja Artura).
    hidden: true,
    gate: { roles: ["admin", "head_of_recruitment"] },
  },
  {
    id: "contracts", area: "deals", title: "Wzory umów", group: "Wzory i wycena",
    description: "Treść umów B2B używanych przez generator.",
    keywords: "umowa b2b szablon generator kontrakt",
    route: "/settings/contract-templates",
    gate: { roles: ["admin", "finance"], section: "finance", finance: true },
  },
  {
    id: "rates", area: "deals", title: "Stawki rynkowe", group: "Wzory i wycena",
    description: "Widełki rynkowe dla ról — punkt odniesienia przy wycenie.",
    keywords: "benchmark wycena stawki rynek",
    route: "/settings/rate-benchmarks",
    gate: { roles: ["admin", "finance"], section: "finance", finance: true },
  },
  {
    id: "register-import", area: "deals", title: "Rejestr umów z Excela", group: "Importy",
    description: "Wgraj plik działu „UMOWY I ZAMÓWIENIA” — podgląd, zapis i cofnięcie.",
    keywords: "import excel xlsx rejestr umowy b2b dzial numery aneks bez dzialalnosci",
    route: "/settings/b2b-register-import",
    wide: true,
    // Od 20.10.2026 zakładka System › Importy; adres przekierowuje na nią.
    hidden: true,
    gate: { roles: ["admin"] },
  },
  {
    id: "contract-docs-sharepoint", area: "deals", title: "Dokumenty kontraktów z SharePointa", group: "Importy",
    description: "Folder „Umowy pracowników” → zakładka Dokumenty kontraktów, synchronizacja w obie strony.",
    keywords: "sharepoint folder umowy pracownikow dokumenty aneksy wypowiedzenia import synchronizacja",
    route: "/settings/contract-docs-sharepoint",
    wide: true,
    // Od 20.10.2026 zakładka System › Importy; adres przekierowuje na nią.
    hidden: true,
    gate: { roles: ["admin"] },
  },
  {
    // „firmy” od 21.10.2026 — własne powiadomienia są w „Moje konto”.
    id: "notifications", area: "sys", title: "Powiadomienia firmy", group: "Firma",
    description: "Która rola dostaje które powiadomienia i które maile wychodzą do całej firmy.",
    keywords: "powiadomienia email maile wysylka nadawca odbiorcy kolejka rola role kto dostaje",
    wide: true,
    gate: { roles: ["admin"], section: "system_admin" },
  },
  {
    id: "ai", area: "sys", title: "Koszty AI", group: "AI",
    description: "Który model robi co i ile to kosztuje w tym miesiącu.",
    keywords: "model claude limit alarm ai koszty funkcje",
    route: "/settings/ai",
    gate: { roles: ["admin"], section: "system_admin" },
  },
  {
    id: "qc-quality", area: "sys", title: "Jakość QC", group: "AI",
    description: "Jak często QC CV się myli i które uwagi są tylko informacją.",
    keywords: "qc cv trafnosc nieprawda pominiete uwagi wycisz informacja jakosc kontrola",
    route: "/settings/ai/qc-quality",
    wide: true,
    // `GET/PATCH /api/settings/ai/qc-quality` = `AdminUser`.
    gate: { roles: ["admin"], section: "system_admin" },
  },
  {
    // Runda 2 (21.10.2026): jedna pozycja ze stanem wszystkich połączeń zamiast
    // trzech w różnych układach; „Klucze API”, „Portale ogłoszeniowe” i „Prepy
    // w Teams” są ukryte z menu, ich adresy działają.
    id: "integrations", area: "sys", title: "Integracje", group: "Integracje",
    description: "Połączenia NEXUSA z innymi systemami — stan i następny krok w jednym miejscu.",
    keywords:
      "integracje integracja polaczenia klucz klucze api x-api-key konto serwisowe n8n portale ogloszenia rocketjobs justjoinit jjit oauth teams prep transkrypcja",
    gate: { roles: ["admin"] },
  },
  {
    id: "api-keys", area: "sys", title: "Klucze API", group: "Integracje",
    description: "Konta serwisowe i klucze X-API-Key dla automatyzacji, np. rozliczeń w n8n.",
    keywords: "klucz klucze api x-api-key konto serwisowe integracje integracja automatyzacja n8n power automate make skrypt token",
    route: "/settings/api-keys",
    // `/api/settings/service-accounts` = `AdminUser`; middleware jak `/settings/api-integration`.
    // Z menu od 21.10.2026 — wejście przez „Integracje → Zarządzaj”.
    hidden: true,
    gate: { roles: ["admin"], section: "system_admin" },
  },
  {
    id: "traffit", area: "sys", title: "Import z Traffita", group: "Integracje",
    description: "Wyłączony 14.10.2026 — historia ostatnich importów.",
    keywords: "traffit synchronizacja import",
    // Od 20.10.2026 zakładka „Traffit” w System › Importy; adres działa.
    hidden: true,
    gate: { roles: ["admin"] },
  },
  {
    id: "job-boards", area: "sys", title: "Portale ogłoszeniowe", group: "Integracje",
    description: "Konto firmy na RocketJobs i JustJoin.IT — połączenie i saldo ogłoszeń.",
    keywords: "portale ogloszenia rocketjobs justjoinit jjit multiposting publikacja oauth",
    // W „Integracjach” od 21.10.2026; `?item=job-boards` (powrót z OAuth) działa.
    hidden: true,
    gate: { roles: ["admin"] },
  },
  {
    id: "teams-prep", area: "sys", title: "Prepy w Teams", group: "Integracje",
    description: "Transkrypty prepów z Teams, notatki i ocena prepu.",
    keywords: "teams prep transkrypcja spotkania notatki fireflies",
    // W „Integracjach” od 21.10.2026; adres działa.
    hidden: true,
    gate: { roles: ["admin"] },
  },
  {
    id: "dict", area: "sys", title: "Listy wyboru", group: "Firma",
    description: "Branże, powody odrzucenia i inne wartości list.",
    keywords: "slowniki branze powody taksonomie",
    route: "/settings/dictionaries",
    // Ukryte 20.10.2026 (decyzja Artura): oba słowniki („Powody odrzucenia”,
    // „Branża”) nie mają czytelnika poza tym ekranem — powody odrzucenia są
    // w Procesach rekrutacyjnych (audyt: docs/settings-rejection-reasons-audit.md).
    hidden: true,
    gate: { roles: ["admin"], section: "system_admin" },
  },
  {
    id: "fields", area: "sys", title: "Dodatkowe pola", group: "Firma",
    description: "Własne pola na profilu kandydata i rekrutacji.",
    keywords: "pola konfiguracja formularz",
    route: "/settings/entity-fields",
    gate: { roles: ["admin"], section: "system_admin" },
  },
  {
    // Importy i synchronizacje w jednym miejscu (20.10.2026, decyzja Artura):
    // rejestr z Excela, dokumenty z SharePointa i archiwum Traffita jako
    // zakładki. Import z Compassa zostaje w Zespole i dostępie (widzą go Kadry).
    id: "imports", area: "sys", title: "Importy", group: "Importy i synchronizacje",
    description: "Rejestr umów z Excela, dokumenty kontraktów z SharePointa i historia importów z Traffita.",
    keywords:
      "import excel xlsx rejestr umowy b2b dzial numery aneks sharepoint folder umowy pracownikow dokumenty synchronizacja traffit",
    wide: true,
    gate: { roles: ["admin"] },
  },
  {
    id: "history", area: "sys", title: "Historia zdarzeń", group: "Nadzór",
    description: "Usunięcia i ważne zmiany w systemie — także próby zablokowane. Wpisów nie da się usunąć.",
    keywords: "zdarzenia audyt log historia usuniecia",
    // Nagłówek z układu Ustawień jak na innych ekranach (runda 2, 21.10.2026) — dotąd tytuł w karcie.
    wide: true,
    // `GET /api/settings/event-history` = `FinanceModuleUser` („Moduł Finanse”).
    gate: { permission: "finance_module", section: "finance", finance: true },
  },
  {
    id: "placements", area: "sys", title: "Wykluczone placementy", group: "Nadzór",
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

/** Stan spoza konta, od którego zależy widoczność pozycji. */
export interface SettingsContext {
  /** Program „Ludzie w NEXUSIE” włączony (`useHrProgram`); brak = wyłączony. */
  hrProgram?: boolean;
}

export function canSeeSettingsItem(
  user: SettingsUser | null,
  item: SettingsItem,
  context: SettingsContext = {},
): boolean {
  if (!user) return false;
  const { gate } = item;
  if (gate.hrProgram && !context.hrProgram) return false;
  // Uprawnienie nadane na ekranie Osoby i role jest jawną decyzją
  // administratora, więc pozycji z `permission` filtr Finansów nie zasłania.
  if (isFinanceReadOnly(user) && !gate.finance && !gate.permission) return false;
  if (gate.roles && !hasRole(user, ...gate.roles)) return false;
  if (gate.permission && !hasPermission(user, gate.permission)) return false;
  if (gate.capability && !hasCapability(user, gate.capability)) return false;
  if (gate.section && !hasSectionAccess(user, gate.section, gate.required ?? "read")) return false;
  return true;
}

/** Pozycje widoczne w menu (bez ukrytych). */
export function listedSettingsItems(
  user: SettingsUser | null,
  context: SettingsContext = {},
): SettingsItem[] {
  return SETTINGS_ITEMS.filter((i) => !i.hidden && canSeeSettingsItem(user, i, context));
}

export function listedSettingsAreas(
  user: SettingsUser | null,
  context: SettingsContext = {},
): SettingsArea[] {
  const items = listedSettingsItems(user, context);
  return SETTINGS_AREAS.filter((a) => items.some((i) => i.area === a.id));
}

export interface SettingsItemGroup {
  name: string;
  items: SettingsItem[];
}

/** Widoczne pozycje obszaru w grupach — lewa kolumna Ustawień i lista obszaru.
 *  Grupy idą w kolejności pierwszej pozycji, pozycje w kolejności rejestru. */
export function groupedAreaItems(
  user: SettingsUser | null,
  areaId: SettingsAreaId,
  context: SettingsContext = {},
): SettingsItemGroup[] {
  const groups: SettingsItemGroup[] = [];
  for (const item of listedSettingsItems(user, context)) {
    if (item.area !== areaId) continue;
    const name = item.group ?? "";
    const group = groups.find((g) => g.name === name);
    if (group) group.items.push(item);
    else groups.push({ name, items: [item] });
  }
  return groups;
}

export function findSettingsItem(id: string | null | undefined): SettingsItem | undefined {
  return id ? SETTINGS_ITEMS.find((i) => i.id === id) : undefined;
}

export function findSettingsArea(id: string | null | undefined): SettingsArea | undefined {
  return id ? SETTINGS_AREAS.find((a) => a.id === id) : undefined;
}

/** Pozycja z osobną trasą, której adres zaczyna się od `pathname` — najdłuższa
 *  pasująca trasa wygrywa (`/settings/ai/qc-quality` to nie „Koszty AI”). */
export function findSettingsItemByRoute(pathname: string): SettingsItem | undefined {
  let best: SettingsItem | undefined;
  for (const item of SETTINGS_ITEMS) {
    const route = item.route;
    if (!route || (pathname !== route && !pathname.startsWith(`${route}/`))) continue;
    if (!best || route.length > (best.route?.length ?? 0)) best = item;
  }
  return best;
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
  // Pozycje programu „Ludzie w NEXUSIE” bez własnej trasy (`skills-review`)
  // otwierają się tylko przy włączonym programie.
  context: SettingsContext = {},
): SettingsView {
  const itemId = params.item ?? (params.tab ? LEGACY_SETTINGS_TABS[params.tab] : undefined);
  const item = findSettingsItem(itemId);
  if (item && !item.route && canSeeSettingsItem(user, item, context)) {
    return { kind: "item", item, area: findSettingsArea(item.area)! };
  }
  const area = findSettingsArea(params.area);
  if (area && listedSettingsAreas(user, context).some((a) => a.id === area.id)) {
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
export function searchSettingsItems(
  user: SettingsUser | null,
  query: string,
  context: SettingsContext = {},
): SettingsItem[] {
  const terms = normalize(query).trim().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return [];
  return listedSettingsItems(user, context).filter((i) => {
    const hay = normalize(
      `${i.title} ${i.description} ${i.keywords} ${findSettingsArea(i.area)?.name ?? ""}`,
    );
    const words = hay.split(/[^a-z0-9]+/).filter(Boolean);
    return terms.every((t) => termMatches(t, hay, words));
  });
}
