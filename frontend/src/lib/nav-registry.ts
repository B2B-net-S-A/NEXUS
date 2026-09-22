/**
 * Jedno źródło nawigacji dla sidebara i palety ⌘K.
 *
 * Do tej pory paleta miała własną, krótszą listę pozycji z innymi adresami
 * (`/` zamiast dashboardu roli, `/manager` bez odpowiednika w menu), więc każda
 * zmiana menu wymagała pamiętania o drugim pliku — i zwykle o nim nie
 * pamiętano. Rejestr jest czystym modułem (bez hooków i bez `next/navigation`),
 * żeby widoczność pozycji dało się udowodnić testem bez montowania shellu.
 */
import {
  Brain,
  Briefcase,
  Building2,
  Calendar,
  FileSignature,
  FileText,
  GitBranch,
  Handshake,
  Heart,
  HelpCircle,
  Inbox,
  LayoutDashboard,
  Lightbulb,
  PhoneCall,
  Radar,
  Search,
  Settings,
  Sparkles,
  Star,
  Store,
  Users,
  Wallet,
} from "lucide-react";
import type { ComponentType } from "react";

import { hasActionAccess, type ProductAction } from "@/lib/action-access";
import { hasCapability, type Capability } from "@/lib/capabilities";
import { dashboardHref } from "@/lib/dashboard-presets";
import {
  hasSectionAccess,
  rolesWithSectionAccess,
  type ProductSection,
} from "@/lib/section-access";
import { hasRole, type User, type UserRole } from "@/store/auth";

export type NavIcon = ComponentType<{ className?: string }>;

export type NavBadgeKey = "candidates" | "jobs" | "applicationSubmissions";

export type NavFeatureFlag = "contactQueue";

export type NavSectionKey =
  | "sourcing"
  | "pipeline"
  | "delivery"
  | "insights"
  | "finance"
  | "system";

/** Użytkownik w zakresie potrzebnym do policzenia widoczności menu. */
export type NavUser =
  | Pick<
      User,
      "role" | "roles" | "effective_section_access" | "effective_action_access"
    >
  | null
  | undefined;

export type NavVisibilityOptions = { contactQueueEnabled: boolean };

/** Użytkownik, dla którego liczy się adres docelowy pozycji (`resolveHref`). */
export type NavHrefUser = Parameters<typeof dashboardHref>[0];

/** Grupy wysuwanego panelu „Więcej" — kolejność tablicy = kolejność w panelu. */
export type NavMoreGroupKey = "daily" | "documents" | "sources" | "knowledge" | "system";

export const NAV_MORE_GROUPS: readonly { key: NavMoreGroupKey; title: string }[] = [
  { key: "daily", title: "Codzienna praca" },
  { key: "documents", title: "Dokumenty" },
  { key: "sources", title: "Baza i źródła" },
  { key: "knowledge", title: "Wiedza i raporty" },
  { key: "system", title: "System" },
];

export type NavEntry = {
  id: string;
  /**
   * Adres KANONICZNY — po nim liczy się aktywna pozycja, klucze Reacta
   * i kontrakt z rejestrem capability. Dashboard ma tu `/dashboard`, a adres
   * docelowy zależny od roli podaje `resolveHref`.
   */
  href: string;
  resolveHref?: (user: NavHrefUser) => string;
  label: string;
  icon: NavIcon;
  section: NavSectionKey;
  roles?: UserRole[];
  action?: ProductAction;
  /**
   * Capability z `lib/capabilities.ts`, której lista ról ma być lustrem tej
   * pozycji. Sidebar jej NIE sprawdza (bramkuje sekcją i `roles`, jak dotąd);
   * paleta dokłada ją jako drugi filtr, a zgodność obu list pilnuje test.
   */
  capability?: Capability;
  badgeKey?: NavBadgeKey;
  featureFlag?: NavFeatureFlag;
  /**
   * `primary` = pozycja stoi na szynie (w jednej z grup `NAV_PRIMARY_GROUPS`);
   * `more` = w wysuwanym panelu „Więcej". Podział jest per WPIS, niezależny od
   * roli: o tym, KTO co widzi, decyduje wyłącznie bramka widoczności (sekcja /
   * role / akcja / flaga). Rdzeń pracy każdej persony jest `primary` — „Praca"
   * (Dashboard, Rekrutacje, Kandydaci, Kalendarz), „Klienci i umowy" (Klienci,
   * Kontrakty, Zamówienia z maila) i „Firma" (Finanse, Insights) — więc
   * rekruter widzi pięć pozycji, a admin dziewięć, bez osobnych drzew per rola.
   */
  placement: "primary" | "more";
  /** Wymagane dla `placement: "more"` (pilnuje test) — grupa w panelu. */
  moreGroup?: NavMoreGroupKey;
  /** Jedna linia pod nazwą w panelu „Więcej" (makieta v3) — po co tam wejść. */
  moreHint?: string;
  paletteKeywords?: string[];
  inPalette: boolean;
  /**
   * `false` = pozycja istnieje WYŁĄCZNIE w palecie ⌘K. Dziś trzy: „Panel
   * managera" (z menu zdjęty dawno, ale paleta nadal do niego prowadziła) oraz
   * Wyszukiwarka i Talent Radar (od 21.09.2026 tryby ekranu „Kandydaci").
   * Przebudowa nawigacji nie może po cichu zabierać wejść. Brak pola = w menu.
   */
  inSidebar?: boolean;
  /**
   * Renderuje pozycję jako `<a href target="_blank" rel="noopener noreferrer">`
   * zamiast Next.js `<Link>` (zewnętrzne dashboardy). Dziś nieużywane.
   */
  external?: boolean;
};

/** Kształt, który sidebar renderuje od zawsze — celowo bez zmian. */
export type NavItem = NavEntry;

export type NavSection = {
  title: string;
  icon: NavIcon;
  items: NavItem[];
  section?: ProductSection;
};

type NavSectionMeta = {
  key: NavSectionKey;
  title: string;
  icon: NavIcon;
  /** Sekcja produktu bramkująca całą grupę; „System" nie ma żadnej. */
  section?: ProductSection;
};

/** Kolejność tej tablicy = kolejność grup w sidebarze. */
export const NAV_SECTION_META: readonly NavSectionMeta[] = [
  { key: "sourcing", title: "Sourcing", icon: Users, section: "sourcing" },
  { key: "pipeline", title: "Pipeline", icon: GitBranch, section: "pipeline" },
  { key: "delivery", title: "Delivery", icon: Handshake, section: "delivery" },
  { key: "insights", title: "Insights", icon: Lightbulb, section: "insights" },
  // Moduł „Finanse". Jedna pozycja, bo `/finance` to jedna strona z zakładkami
  // — osobny link „Import MD" prowadziłby do tej samej trasy i otwierał ją na
  // innej zakładce niż podpowiada etykieta.
  { key: "finance", title: "Finanse", icon: Wallet, section: "finance" },
  { key: "system", title: "System", icon: Settings },
];

const CORTEX_ROLES = rolesWithSectionAccess("insights").filter(
  (role) => role !== "user",
);

/** Moduł kandydatów — rola `user` (viewer/klient) nie ma dostępu. */
const CANDIDATES_NAV_ROLES: UserRole[] = [
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "tac",
  "recruiter",
  "finance",
  "sourcer",
];

/**
 * Kolejność wpisów w obrębie sekcji = kolejność pozycji w menu.
 *
 * NIE MA tu „Panelu Managera" (`/dashboard/delivery-lead`, schowany 2026-05-28)
 * ani grupy „Raporty KPI" (`/dynareporter/*` — te trasy tylko przekierowują do
 * /insights). Przywracając Panel Managera pamiętaj, że bramka „Oczekuje" jest
 * usunięta od 17.09.2026 — nie wracaj do `badgeKey: "pendingVerifications"`.
 */
export const NAV_REGISTRY: readonly NavEntry[] = [
  {
    id: "dashboard",
    href: "/dashboard",
    resolveHref: (user) => dashboardHref(user),
    label: "Dashboard",
    icon: LayoutDashboard,
    section: "sourcing",
    placement: "primary",
    inPalette: true,
  },
  // Moduł kandydatów (audyt M2 PR1): rola `user` (viewer/klient) nie ma
  // dostępu — backend 403 + middleware /403; chowamy linki żeby nie
  // prowadzić w ślepy zaułek.
  {
    id: "candidates",
    href: "/candidates",
    label: "Kandydaci",
    icon: Users,
    section: "sourcing",
    badgeKey: "candidates",
    roles: CANDIDATES_NAV_ROLES,
    capability: "nav.candidates",
    placement: "primary",
    inPalette: true,
  },
  // Wyszukiwarka jest TRYBEM ekranu „Kandydaci" (decyzja 21.09.2026 — pasek
  // boczny był przeładowany), więc z menu zniknęła; zostaje w palecie ⌘K,
  // bo „wyszukiwarka" wpisana w ⌘K ma dalej prowadzić do wyszukiwarki.
  // Te same role co „Kandydaci": to ten sam moduł.
  {
    id: "candidate-search",
    href: "/candidates?mode=search",
    label: "Wyszukiwarka kandydatów",
    icon: Search,
    section: "sourcing",
    roles: CANDIDATES_NAV_ROLES,
    capability: "nav.candidates",
    placement: "primary",
    paletteKeywords: ["wyszukiwarka", "szukaj", "search", "cv"],
    inPalette: true,
    inSidebar: false,
  },
  {
    // Bez capability: kolejka telefonów jest semantyką WYKONAWCZĄ (lustro
    // backendowego `ContactCaller`), nie wejściem nawigacyjnym do modułu.
    id: "contact-queue",
    href: "/candidates/contact-queue",
    label: "Do przedzwonienia",
    icon: PhoneCall,
    section: "sourcing",
    roles: ["talent_community_manager", "tac", "recruiter", "sourcer"],
    featureFlag: "contactQueue",
    placement: "more",
    moreGroup: "daily",
    inPalette: true,
  },
  {
    id: "cv-generator",
    moreHint: "CV firmowe kandydata pod rekrutację",
    href: "/cv-generator",
    label: "Generator CV",
    icon: Sparkles,
    section: "sourcing",
    placement: "more",
    moreGroup: "documents",
    inPalette: true,
  },
  // Dostęp do Generatora Umów B2B jest konfigurowany osobno od sekcji
  // Sourcing. Edycja katalogu ról umownych nadal pozostaje admin-only.
  {
    id: "b2b-generator",
    moreHint: "Umowy B2B do podpisu i rejestr",
    href: "/contracts/b2b-generator",
    label: "Generator Umów B2B",
    icon: FileSignature,
    section: "sourcing",
    action: "b2b_contract_generator",
    placement: "more",
    moreGroup: "documents",
    inPalette: true,
  },
  {
    id: "talents",
    moreHint: "Pule talentów i listy osób",
    href: "/talents",
    label: "Talenty",
    icon: Star,
    section: "sourcing",
    roles: [
      "admin",
      "head_of_recruitment",
      "delivery_lead",
      "talent_community_manager",
      "tac",
      "recruiter",
      "finance",
      "sourcer",
    ],
    capability: "nav.talents",
    placement: "more",
    moreGroup: "sources",
    inPalette: true,
  },
  {
    // BEZ `roles`: radar i powiązane funkcje są dostępne dla KAŻDEJ
    // zalogowanej roli (decyzja produktowa Artura 19.08). Lustrzane
    // z backendem (CurrentUser), middleware (brak wpisu = brak
    // zawężenia) i `nav.talent_radar` w lib/capabilities.ts.
    //
    // Od 21.09.2026 radar to tryb ekranu „Kandydaci" (`?mode=request`) i nie
    // stoi w menu — tylko w palecie. Kto NIE ma `nav.candidates` (np. viewer
    // `user`), nie wejdzie na /candidates, więc dla niego adres zostaje
    // samodzielną stroną /talent-radar (działa dla każdej roli).
    id: "talent-radar",
    href: "/talent-radar",
    resolveHref: (user) =>
      hasCapability(user, "nav.candidates")
        ? "/candidates?mode=request"
        : "/talent-radar",
    label: "Szukaj z treści requestu (Talent Radar)",
    icon: Radar,
    section: "sourcing",
    capability: "nav.talent_radar",
    placement: "primary",
    paletteKeywords: ["talent radar", "radar", "request", "treść requestu"],
    inPalette: true,
    inSidebar: false,
  },
  {
    id: "marketplace",
    moreHint: "Kontraktorzy wolni teraz lub wkrótce",
    href: "/sourcing/marketplace",
    label: "Targ / Dostępni",
    icon: Store,
    section: "sourcing",
    roles: [
      "admin",
      "head_of_recruitment",
      "delivery_lead",
      "talent_community_manager",
      "tac",
      "recruiter",
      "finance",
      "sourcer",
    ],
    capability: "nav.sourcing",
    placement: "more",
    moreGroup: "sources",
    inPalette: true,
  },
  {
    id: "applications",
    moreHint: "Zgłoszenia z formularzy i portali",
    href: "/applications",
    label: "Zgłoszenia",
    icon: Inbox,
    section: "sourcing",
    badgeKey: "applicationSubmissions",
    // Te same role co `canReviewApplications` w sidebarze i backendowe
    // CandidateWriteAccess — HoR nie rozpatruje zgłoszeń (UAT A-B02).
    roles: [
      "admin",
      "delivery_lead",
      "talent_community_manager",
      "tac",
      "recruiter",
      "finance",
      "sourcer",
    ],
    placement: "more",
    moreGroup: "daily",
    inPalette: true,
  },
  {
    id: "jobs",
    href: "/jobs",
    label: "Rekrutacje",
    icon: Briefcase,
    section: "pipeline",
    badgeKey: "jobs",
    placement: "primary",
    inPalette: true,
  },
  {
    id: "calendar",
    href: "/calendar",
    label: "Kalendarz",
    icon: Calendar,
    section: "pipeline",
    placement: "primary",
    inPalette: true,
  },
  {
    id: "clients",
    href: "/clients",
    label: "Klienci",
    icon: Building2,
    section: "delivery",
    capability: "nav.clients",
    placement: "primary",
    inPalette: true,
  },
  {
    id: "my-clients",
    moreHint: "Klienci z mojego portfela",
    href: "/my-clients",
    label: "Panel klientów",
    icon: Briefcase,
    section: "delivery",
    capability: "nav.my_clients",
    placement: "more",
    moreGroup: "sources",
    inPalette: true,
  },
  {
    // Zamówienia z maila są częścią Delivery. Backend daje TCM wyłącznie
    // bezpieczny odczyt, a DL widzi wszystkich klientów bez obcych kwot.
    id: "order-mail",
    href: "/order-mail",
    label: "Zamówienia z maila",
    icon: Inbox,
    section: "delivery",
    capability: "nav.order_mail",
    placement: "primary",
    inPalette: true,
  },
  {
    id: "my-relationships",
    moreHint: "Kontakty i relacje z klientami",
    href: "/my-relationships",
    label: "Moje relacje",
    icon: Heart,
    section: "delivery",
    capability: "nav.my_relationships",
    placement: "more",
    moreGroup: "sources",
    inPalette: true,
  },
  // „Kontrakty" to jeden workspace z dwoma trybami (Obsługa kontraktorów /
  // Rejestr kontraktów); dawna pozycja „Kontraktorzy" została wchłonięta —
  // /contractors przekierowuje do /contracts?view=operations, a tryb operacyjny
  // jest bramkowany rolami wewnątrz strony. Backend zwraca TCM bezpieczny
  // rejestr bez stawek; DL widzi wszystkich klientów, a stawki tylko dla
  // przypisanych. Dokumenty mają osobny gate.
  {
    id: "contracts",
    href: "/contracts",
    label: "Kontrakty",
    icon: FileText,
    section: "delivery",
    capability: "nav.contracts",
    placement: "primary",
    inPalette: true,
  },
  {
    id: "insights",
    href: "/insights",
    label: "Insights",
    icon: Lightbulb,
    section: "insights",
    placement: "primary",
    inPalette: true,
  },
  {
    id: "cortex",
    moreHint: "Wiedza o klientach i rynku",
    href: "/cortex",
    label: "Cortex",
    icon: Brain,
    section: "insights",
    roles: CORTEX_ROLES,
    capability: "nav.cortex",
    placement: "more",
    moreGroup: "knowledge",
    inPalette: true,
  },
  {
    id: "finance",
    href: "/finance",
    label: "Finanse",
    icon: Wallet,
    section: "finance",
    capability: "nav.finance",
    placement: "primary",
    inPalette: true,
  },
  {
    id: "help",
    moreHint: "Procedury, instrukcje, karty klientów",
    href: "/help",
    label: "Pomoc",
    icon: HelpCircle,
    section: "system",
    placement: "more",
    moreGroup: "system",
    inPalette: true,
  },
  {
    id: "settings",
    moreHint: "Konto, integracje, administracja",
    href: "/settings",
    label: "Ustawienia",
    icon: Settings,
    section: "system",
    placement: "more",
    moreGroup: "system",
    inPalette: true,
  },
  {
    id: "manager",
    href: "/manager",
    label: "Panel managera",
    icon: GitBranch,
    section: "system",
    roles: ["admin", "delivery_lead"],
    capability: "nav.manager",
    placement: "primary",
    inPalette: true,
    inSidebar: false,
  },
];

/** Grupy szyny — kolejność tablicy = kolejność na szynie. */
export type NavPrimaryGroupKey = "work" | "clients" | "company";

/**
 * Szyna jest podzielona na grupy z nagłówkami (decyzja 21.09.2026 — płaska
 * lista jedenastu pozycji była przeładowana). `ids` = kolejność pozycji
 * w grupie. Każdy wpis `primary` widoczny w menu MUSI być w dokładnie jednej
 * grupie (pilnuje test). Grupa bez widocznych pozycji nie renderuje się.
 */
export const NAV_PRIMARY_GROUPS: readonly {
  key: NavPrimaryGroupKey;
  title: string;
  ids: readonly string[];
}[] = [
  { key: "work", title: "Praca", ids: ["dashboard", "jobs", "candidates", "calendar"] },
  { key: "clients", title: "Klienci i umowy", ids: ["clients", "contracts", "order-mail"] },
  { key: "company", title: "Firma", ids: ["finance", "insights"] },
];

/** Kolejność pozycji na szynie (id wpisów) — spłaszczone `NAV_PRIMARY_GROUPS`. */
export const NAV_PRIMARY_ORDER: readonly string[] = NAV_PRIMARY_GROUPS.flatMap(
  (group) => group.ids,
);

const SECTION_META_BY_KEY = new Map(
  NAV_SECTION_META.map((meta) => [meta.key, meta]),
);

function featureFlagOn(
  flag: NavFeatureFlag | undefined,
  opts: NavVisibilityOptions,
): boolean {
  if (!flag) return true;
  // Jedyna flaga dzisiaj; `switch` wymusi decyzję przy dodaniu kolejnej.
  switch (flag) {
    case "contactQueue":
      return opts.contactQueueEnabled;
  }
}

function isEntryVisible(
  entry: NavEntry,
  user: NavUser,
  opts: NavVisibilityOptions,
): boolean {
  const productSection = SECTION_META_BY_KEY.get(entry.section)?.section;
  return (
    (!productSection || hasSectionAccess(user, productSection)) &&
    (!entry.roles || hasRole(user, ...entry.roles)) &&
    (!entry.action || hasActionAccess(user, entry.action)) &&
    featureFlagOn(entry.featureFlag, opts)
  );
}

/**
 * Pozycje nawigacji widoczne dla użytkownika, w kolejności menu (sekcja po
 * sekcji). Czysta funkcja — te same reguły czyta sidebar i paleta ⌘K.
 */
export function visibleNavEntries(
  user: NavUser,
  opts: NavVisibilityOptions,
): NavEntry[] {
  return NAV_SECTION_META.flatMap((meta) =>
    NAV_REGISTRY.filter(
      (entry) => entry.section === meta.key && isEntryVisible(entry, user, opts),
    ),
  );
}

/**
 * Pozycje menu widoczne dla danego użytkownika POGRUPOWANE SEKCJAMI PRODUKTU
 * (szyna i „Więcej" RAZEM — układ wizualny dają `visiblePrimaryNav`
 * i `visibleMoreGroups`). Czysta funkcja, żeby dało się
 * to udowodnić testem bez montowania sidebara (a więc bez mocków `next/
 * navigation`, react-query, `api` i `useUiStore`).
 *
 * Zastępuje drugie, równoległe drzewo `FINANCE_NAV_SECTIONS`: rola `finance`
 * dostawała cztery pozycje (Dashboard · Finanse · Pomoc · Ustawienia), mimo że
 * KAŻDA lista `roles` już ją wymienia — backend przepuszcza ją wszędzie tam,
 * gdzie recruitera (decyzja 19.08), więc menu było jedyną warstwą, która ją
 * odcinała. Własny moduł „Finanse" jest filtrowany przez autorytatywny
 * `section: "finance"`, dzięki czemu działa też indywidualny wyjątek nadany
 * w panelu uprawnień.
 */
export function visibleNavSections(
  user: NavUser,
  opts: NavVisibilityOptions,
): NavSection[] {
  const entries = visibleNavEntries(user, opts).filter(
    (entry) => entry.inSidebar !== false,
  );
  return NAV_SECTION_META.map((meta) => ({
    title: meta.title,
    icon: meta.icon,
    section: meta.section,
    items: entries.filter((entry) => entry.section === meta.key),
  })).filter((section) => section.items.length > 0);
}

export type NavPrimaryGroup = {
  key: NavPrimaryGroupKey;
  title: string;
  items: NavEntry[];
};

/**
 * Grupy szyny widoczne dla użytkownika, z pozycjami w kolejności grupy — TA
 * SAMA bramka co reszta menu (`isEntryVisible`). Puste grupy odpadają, więc
 * rekruter nie widzi nagłówka „Klienci i umowy" bez ani jednej pozycji.
 */
export function visiblePrimaryGroups(
  user: NavUser,
  opts: NavVisibilityOptions,
): NavPrimaryGroup[] {
  const byId = new Map(
    visibleNavEntries(user, opts)
      .filter((entry) => entry.inSidebar !== false && entry.placement === "primary")
      .map((entry) => [entry.id, entry]),
  );
  return NAV_PRIMARY_GROUPS.map((group) => ({
    key: group.key,
    title: group.title,
    items: group.ids.flatMap((id) => {
      const entry = byId.get(id);
      return entry ? [entry] : [];
    }),
  })).filter((group) => group.items.length > 0);
}

/** Pozycje szyny (bez „Więcej"), w kolejności `NAV_PRIMARY_ORDER`. */
export function visiblePrimaryNav(
  user: NavUser,
  opts: NavVisibilityOptions,
): NavEntry[] {
  return visiblePrimaryGroups(user, opts).flatMap((group) => group.items);
}

export type NavMoreGroup = {
  key: NavMoreGroupKey;
  title: string;
  items: NavEntry[];
};

/**
 * Grupy panelu „Więcej" widoczne dla użytkownika — TA SAMA bramka co szyna
 * (`isEntryVisible`), puste grupy odpadają. Pusta tablica = nie ma czego
 * chować, więc sidebar nie renderuje przycisku „Więcej".
 */
export function visibleMoreGroups(
  user: NavUser,
  opts: NavVisibilityOptions,
): NavMoreGroup[] {
  const entries = visibleNavEntries(user, opts).filter(
    (entry) => entry.inSidebar !== false && entry.placement === "more",
  );
  return NAV_MORE_GROUPS.map((group) => ({
    ...group,
    items: entries.filter((entry) => entry.moreGroup === group.key),
  })).filter((group) => group.items.length > 0);
}

/**
 * Wszystko, do czego menu prowadzi: szyna + „Więcej". Testy „która rola widzi
 * który adres" pytają o TĘ sumę — przeniesienie pozycji pod „Więcej" nie może
 * nikomu niczego zabrać ani dodać.
 */
export function visibleNavHrefs(
  user: NavUser,
  opts: NavVisibilityOptions,
): string[] {
  return [
    ...visiblePrimaryNav(user, opts),
    ...visibleMoreGroups(user, opts).flatMap((group) => group.items),
  ].map((entry) => entry.href);
}

/**
 * Pozycje grupy „Nawigacja" w palecie ⌘K: to, co użytkownik widzi w sidebarze,
 * zawężone o `inPalette` i — jeśli pozycja ma capability — o wynik rejestru
 * capability (`can`). Drugi filtr może pozycję tylko UKRYĆ, więc paleta nigdy
 * nie prowadzi tam, dokąd nie prowadzi menu.
 */
export function visiblePaletteEntries(
  user: NavUser,
  opts: NavVisibilityOptions,
  can: (capability: Capability) => boolean,
): NavEntry[] {
  return visibleNavEntries(user, opts).filter(
    (entry) => entry.inPalette && (!entry.capability || can(entry.capability)),
  );
}

/** Adres, pod który pozycja faktycznie prowadzi (Dashboard zależy od roli). */
export function resolveNavHref(
  entry: Pick<NavEntry, "href" | "resolveHref">,
  user: NavHrefUser,
): string {
  return entry.resolveHref ? entry.resolveHref(user) : entry.href;
}

/**
 * Czy w ogóle pytać backend o flagę kolejki telefonów — użytkownik, który
 * pozycji i tak nie zobaczy (sekcja, rola), nie powinien generować zapytania.
 */
export function canSeeFeatureFlaggedEntry(
  user: NavUser,
  flag: NavFeatureFlag,
): boolean {
  return NAV_REGISTRY.some(
    (entry) =>
      entry.featureFlag === flag &&
      isEntryVisible(entry, user, { contactQueueEnabled: true }),
  );
}
