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
import type { Capability } from "@/lib/capabilities";
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

export type NavEntry = {
  id: string;
  /**
   * Adres KANONICZNY — po nim liczy się aktywna pozycja, klucze Reacta
   * i kontrakt z rejestrem capability. Dashboard ma tu `/dashboard`, a adres
   * docelowy zależny od roli podaje `resolveHref`.
   */
  href: string;
  resolveHref?: (user: Parameters<typeof dashboardHref>[0]) => string;
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
   * Na razie każda widoczna pozycja jest `primary` — pole czyta dopiero
   * kolejny PR (zwijanie rzadziej używanych pozycji pod „Więcej").
   */
  placement: "primary" | "more";
  paletteKeywords?: string[];
  inPalette: boolean;
  /**
   * `false` = pozycja istnieje WYŁĄCZNIE w palecie ⌘K. Dziś jedna: „Panel
   * managera" — z menu zdjęty dawno, ale paleta nadal do niego prowadziła, a
   * przebudowa nawigacji nie może po cichu zabierać wejść. Brak pola = w menu.
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
  // Wyszukiwarka CV istniała tylko jako link z listy kandydatów — rekruter
  // jej nie znajdował. Te same role co „Kandydaci": to ten sam moduł.
  {
    id: "candidate-search",
    href: "/candidates/search",
    label: "Wyszukiwarka",
    icon: Search,
    section: "sourcing",
    roles: CANDIDATES_NAV_ROLES,
    capability: "nav.candidates",
    placement: "primary",
    inPalette: true,
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
    placement: "primary",
    inPalette: true,
  },
  {
    id: "cv-generator",
    href: "/cv-generator",
    label: "Generator CV",
    icon: Sparkles,
    section: "sourcing",
    placement: "primary",
    inPalette: true,
  },
  // Dostęp do Generatora Umów B2B jest konfigurowany osobno od sekcji
  // Sourcing. Edycja katalogu ról umownych nadal pozostaje admin-only.
  {
    id: "b2b-generator",
    href: "/contracts/b2b-generator",
    label: "Generator Umów B2B",
    icon: FileSignature,
    section: "sourcing",
    action: "b2b_contract_generator",
    placement: "primary",
    inPalette: true,
  },
  {
    id: "talents",
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
    placement: "primary",
    inPalette: true,
  },
  {
    // BEZ `roles`: radar i powiązane funkcje są dostępne dla KAŻDEJ
    // zalogowanej roli (decyzja produktowa Artura 19.08). Lustrzane
    // z backendem (CurrentUser), middleware (brak wpisu = brak
    // zawężenia) i `nav.talent_radar` w lib/capabilities.ts.
    id: "talent-radar",
    href: "/talent-radar",
    label: "Talent Radar",
    icon: Radar,
    section: "sourcing",
    capability: "nav.talent_radar",
    placement: "primary",
    inPalette: true,
  },
  {
    id: "marketplace",
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
    placement: "primary",
    inPalette: true,
  },
  {
    id: "applications",
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
    placement: "primary",
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
    href: "/my-clients",
    label: "Panel klientów",
    icon: Briefcase,
    section: "delivery",
    capability: "nav.my_clients",
    placement: "primary",
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
    href: "/my-relationships",
    label: "Moje relacje",
    icon: Heart,
    section: "delivery",
    capability: "nav.my_relationships",
    placement: "primary",
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
    href: "/cortex",
    label: "Cortex",
    icon: Brain,
    section: "insights",
    roles: CORTEX_ROLES,
    capability: "nav.cortex",
    placement: "primary",
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
    href: "/help",
    label: "Pomoc",
    icon: HelpCircle,
    section: "system",
    placement: "primary",
    inPalette: true,
  },
  {
    id: "settings",
    href: "/settings",
    label: "Ustawienia",
    icon: Settings,
    section: "system",
    placement: "primary",
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
 * Pozycje menu widoczne dla danego użytkownika — czysta funkcja, żeby dało się
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
  user: Parameters<typeof dashboardHref>[0],
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
