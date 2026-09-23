import { NextRequest, NextResponse } from "next/server";

import {
  CAREER_NOT_FOUND_PATH,
  isCareerHost,
  requestHost,
  resolveCareerRoute,
} from "@/lib/career/host";
import { decodeJwtPayload, isJwtExpired } from "@/lib/jwt";
import {
  rolesWithSectionAccess,
  type ProductSection,
  type SectionAccess,
} from "@/lib/section-access";
import type { UserRole } from "@/store/auth";

/**
 * Next.js middleware — gate routing based on role-based access control (RBAC).
 *
 * Token jest czytany z cookie `nexus_access` (ustawianego przez auth store po loginie).
 * Middleware dekoduje claim `role` z JWT i porównuje z wymaganiami route'u.
 *
 * Niepowodzenie walidacji (brak tokena/zły format/wygasły) → redirect /login?next=<pathname>.
 * Zła rola → redirect /403.
 *
 * MODEL: **deny by default**. Wszystko, co nie jest jawnie na liście
 * `PUBLIC_PATHS`, wymaga ważnego, niewygasłego tokenu. Wcześniej działało to
 * odwrotnie — chronione były tylko trasy wymienione w `PROTECTED_ROUTES`, więc
 * `/`, `/dashboard`, `/contractors`, `/marketplace`, `/my-clients`,
 * `/cv-generator` i kilkanaście innych ekranów renderowało powłokę aplikacji
 * BEZ jakiejkolwiek kontroli tokenu. Po wygaśnięciu sesji użytkownik nadal
 * widział pulpit (widgety puste, bo API odrzucało requesty) zamiast ekranu
 * logowania. Nowa trasa dodana do `app/` jest teraz chroniona automatycznie —
 * nikt nie musi pamiętać o dopisaniu jej do listy.
 *
 * `ROLE_ROUTES` zawęża dostęp na podstawie podpisanej mapy sekcji i — dla
 * wybranych akcji — dodatkowej listy ról.
 *
 * Uwaga: to *defense in depth*. Guardy backendu (deps.py) pozostają ostatecznym
 * arbitrem — middleware blokuje tylko nawigację do UI, nie chroni API.
 */

const COOKIE_NAME = "nexus_access";

const NON_FINANCE_ROLES: UserRole[] = [
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "tac",
  "recruiter",
  "sourcer",
  "user",
];

const sectionRoles = (
  section: Parameters<typeof rolesWithSectionAccess>[0],
  required: Exclude<SectionAccess, "none"> = "read",
) => rolesWithSectionAccess(section, required);

const SOURCING_ROLES = sectionRoles("sourcing");
const SOURCING_OPERATIONAL_ROLES = SOURCING_ROLES.filter(
  (role) => role !== "user",
);
const PIPELINE_ROLES = sectionRoles("pipeline");
// Legacy viewer `user` ma odczyt Pipeline w macierzy sekcji, ale backend
// kalendarza (`RecruitmentReadAccess` = role operacyjne) go nie wpuszcza — bez
// tego trafiał na ekran pełen błędów zamiast na /403 (audyt ról 22.09).
const PIPELINE_OPERATIONAL_ROLES = PIPELINE_ROLES.filter(
  (role) => role !== "user",
);
const DELIVERY_ROLES = sectionRoles("delivery");
const INSIGHTS_ROLES = sectionRoles("insights");
const SYSTEM_ADMIN_ROLES = sectionRoles("system_admin");

// Trasy wymagające dostępu do sekcji lub KONKRETNYCH ról. Każda inna
// (niepubliczna) trasa wymaga wyłącznie ważnego tokenu — patrz deny-by-default.
// Kolejność prefixów nie ma znaczenia — dopasowywany jest najdłuższy pasujący
// prefix (patrz resolveAccessRule).
type RouteAccessRule = {
  prefix: string;
  roles: UserRole[] | null;
  /**
   * Gdy JWT zawiera claim `sa`, dostęp do tej trasy wynika z podpisanej mapy
   * sekcji. `roles` pozostaje kontrolowanym fallbackiem dla starszych tokenów.
   */
  section?: ProductSection;
  required?: Exclude<SectionAccess, "none">;
  /** Dodatkowa, węższa reguła operacyjna obowiązująca także po section grant. */
  enforceRoles?: boolean;
};

const ROLE_ROUTES: RouteAccessRule[] = [
  {
    prefix: "/manager",
    roles: ["admin", "delivery_lead"],
    section: "delivery",
    enforceRoles: true,
  },
  // Longest-prefix exceptions must precede only conceptually; resolver sorts
  // them. B2B Generator belongs to Sourcing despite living under /contracts.
  {
    prefix: "/contracts/b2b-generator",
    roles: SOURCING_ROLES,
    section: "sourcing",
  },
  // Generator CV = CandidateWriteAccess w backendzie — viewer `user` poza.
  {
    prefix: "/cv-generator",
    roles: SOURCING_OPERATIONAL_ROLES,
    section: "sourcing",
    enforceRoles: true,
  },
  {
    prefix: "/contracts/analytics",
    roles: ["admin", "finance"],
    section: "finance",
    enforceRoles: true,
  },
  { prefix: "/contractors", roles: DELIVERY_ROLES, section: "delivery" },
  { prefix: "/contracts", roles: DELIVERY_ROLES, section: "delivery" },
  {
    prefix: "/my-relationships",
    roles: DELIVERY_ROLES,
    section: "delivery",
  },
  { prefix: "/my-clients", roles: DELIVERY_ROLES, section: "delivery" },
  { prefix: "/clients", roles: DELIVERY_ROLES, section: "delivery" },
  { prefix: "/jobs", roles: PIPELINE_ROLES, section: "pipeline" },
  {
    prefix: "/calendar",
    roles: PIPELINE_OPERATIONAL_ROLES,
    section: "pipeline",
    enforceRoles: true,
  },
  // Moduł „Finanse" — podpisany claim sekcji pozwala także na indywidualny
  // wyjątek, a lista ról zachowuje bezpieczny fallback dla starszych tokenów.
  {
    prefix: "/finance",
    roles: ["admin", "finance"],
    section: "finance",
  },
  // Zamówienia z maila są powierzchnią Delivery; scope rekordu liczy backend.
  { prefix: "/order-mail", roles: DELIVERY_ROLES, section: "delivery" },
  // Granularne podstrony settings (defense in depth) — kolejność nie ma
  // znaczenia, resolveAccessRule bierze najdłuższy pasujący prefix.
  // Backend strumienia czatów wymaga Pipeline i Sourcing (F02); middleware
  // sprawdza Pipeline, brak Sourcing kończy się komunikatem na stronie.
  {
    prefix: "/settings/chats",
    roles: ["admin", "finance"],
    section: "pipeline",
    enforceRoles: true,
  },
  // Techniczna administracja jest osobną sekcją i zostaje Admin-only.
  // Ustawienia biznesowe niżej zachowują własne, węższe publiczności.
  {
    prefix: "/settings/ai",
    roles: SYSTEM_ADMIN_ROLES,
    section: "system_admin",
  },
  {
    prefix: "/settings/api-integration",
    roles: SYSTEM_ADMIN_ROLES,
    section: "system_admin",
  },
  {
    prefix: "/settings/diagnostics",
    roles: SYSTEM_ADMIN_ROLES,
    section: "system_admin",
  },
  {
    prefix: "/settings/dictionaries",
    roles: SYSTEM_ADMIN_ROLES,
    section: "system_admin",
  },
  {
    prefix: "/settings/entity-fields",
    roles: SYSTEM_ADMIN_ROLES,
    section: "system_admin",
  },
  {
    prefix: "/settings/pipeline-templates",
    roles: ["admin", "delivery_lead"],
    section: "pipeline",
    required: "write",
    enforceRoles: true,
  },
  {
    prefix: "/settings/scoring",
    roles: ["admin", "delivery_lead"],
    section: "insights",
    required: "read",
    enforceRoles: true,
  },
  {
    prefix: "/settings/kpi-targets",
    roles: ["admin", "head_of_recruitment"],
    section: "insights",
    required: "write",
    enforceRoles: true,
  },
  {
    prefix: "/settings/cv-rules",
    roles: ["admin", "delivery_lead"],
    section: "delivery",
    required: "write",
    enforceRoles: true,
  },
  { prefix: "/settings/templates", roles: NON_FINANCE_ROLES },
  {
    prefix: "/settings/team-structure",
    roles: ["admin", "head_of_recruitment", "finance"],
    // Struktura zespołu to Pipeline po stronie API (F02).
    section: "pipeline",
    enforceRoles: true,
  },
  // Benchmarki stawek rynkowych: Admin ma CRUD, Finance pełny odczyt.
  // POST/PATCH/DELETE/import pozostają po stronie API na `AdminUser`.
  {
    prefix: "/settings/rate-benchmarks",
    roles: ["admin", "finance"],
    section: "finance",
    enforceRoles: true,
  },
  // Clients overview pokazuje lifetime/active revenue. Finance ma organizacyjny
  // odczyt, spójnie z backendowym `FinanceReadUser`.
  {
    prefix: "/settings/clients-overview",
    roles: ["admin", "finance"],
    section: "finance",
    enforceRoles: true,
  },
  {
    prefix: "/settings/hiring-managers",
    roles: ["admin", "head_of_recruitment", "finance"],
    section: "insights",
    enforceRoles: true,
  },
  {
    prefix: "/settings/contract-templates",
    roles: ["admin", "finance"],
    section: "finance",
    enforceRoles: true,
  },
  {
    prefix: "/settings/client-portfolio-preview",
    roles: ["admin", "finance"],
    section: "finance",
    enforceRoles: true,
  },
  // Wykonywanie telefonów jest ograniczone do ról operacyjnych (lustro
  // backendowego `ContactCaller`); sama strona odbija resztę własnym
  // komunikatem „Brak dostępu".
  //
  // Admin i Head of Recruitment mają WŁASNĄ powierzchnię: kafelek „Nadzór
  // kontaktów" (`<ContactOversightPanel />`) na własnym pulpicie /dashboard (stoi za
  // `GET /api/candidate-contact/oversight`, bramka `ContactOversight`).
  // Panel raz już przestał być montowany (#1031, przez 16 dni nikt tego nie
  // zauważył); od 21.09.2026 link z alertu pokazuje go na pulpicie tymczasowo,
  // jeśli ktoś nie ma tego kafelka.
  // NIE poszerzaj tej listy o admina/HoR: backend wpuszcza do `/queue` wyłącznie
  // role wykonawcze (`ContactCaller`), więc zamieniłbyś /403 na drugi ślepy
  // zaułek, tracąc przy okazji warstwę defense-in-depth.
  //
  // Alerty SLA z `dashboard_v2.py` celują już kotwicą w ten panel
  // (`/dashboard?panel=nadzor-kontaktu`; stary `#nadzor-kontaktu` też działa), a nie tutaj —
  // wcześniej odbiorca alertu, klikając własny alert, lądował na /403.
  // Zmieniając tę listę ról, przemieć też tamten `href`.
  {
    prefix: "/candidates/contact-queue",
    roles: ["talent_community_manager", "tac", "recruiter", "sourcer"],
  },
  // Moduł kandydatów (audyt M2 PR1): rola `user` = read-only viewer/klient
  // NIE ma dostępu do bazy kandydatów, talentów ani targu — backend zwraca
  // 403 (capability guards w candidate_access.py), middleware poprawia UX
  // przekierowując na /403 zamiast pokazywać puste ekrany z błędami.
  {
    prefix: "/candidates",
    roles: SOURCING_OPERATIONAL_ROLES,
    section: "sourcing",
    enforceRoles: true,
  },
  {
    prefix: "/talents",
    roles: SOURCING_OPERATIONAL_ROLES,
    section: "sourcing",
    enforceRoles: true,
  },
  // Talent Radar należy do Sourcing. Wszystkie obecne role operacyjne mają
  // ten dostęp w polityce startowej, ale jawny override użytkownika musi móc
  // go odebrać bez pozostawiania bocznego wejścia przez URL.
  { prefix: "/talent-radar", roles: null, section: "sourcing" },
  {
    prefix: "/sourcing",
    roles: SOURCING_OPERATIONAL_ROLES,
    section: "sourcing",
    enforceRoles: true,
  },
  // Kolejka zgłoszeń z publicznych aplikacji — dane osobowe aplikanta
  // (imię, e-mail, telefon, LinkedIn, CV). Backend gatuje ją przez
  // CandidateWriteAccess + membership do oferty; tu poprawiamy UX, żeby
  // viewer dostał /403 zamiast pustego ekranu z błędem z API.
  // Od 17.09.2026 `CANDIDATE_WRITE_ROLES` obejmuje Head of Recruitment
  // (parytet z rekruterem), więc HoR nie jest już odcinany (audyt ról U5).
  {
    prefix: "/applications",
    roles: SOURCING_OPERATIONAL_ROLES,
    section: "sourcing",
    enforceRoles: true,
  },
  { prefix: "/insights", roles: INSIGHTS_ROLES, section: "insights" },
  // `/profile`, `/settings` (i każda inna trasa bez wpisu) nie
  // potrzebują osobnej bramki rolowej — deny-by-default już wymaga logowania.
];

// Ścieżki jawnie publiczne — jedyne, które przechodzą bez tokenu.
// Dopisanie czegokolwiek tutaj otwiera trasę na świat, więc każdy wpis musi być
// świadomą decyzją.
//   `/login`     — pokrywa /login/forgot-password, /login/reset, /login/microsoft/callback
//   `/register`  — pokrywa /register/verify (self-service rejestracja + aktywacja email)
//   `/auth/microsoft/callback`
//                — cel `redirect_uri` logowania przez Microsoft (route handler,
//                  NIE page.tsx — patrz src/app/auth/microsoft/callback/route.ts).
//                  Azure przekierowuje tu przeglądarkę PRZED wydaniem tokenu,
//                  więc cookie jeszcze nie istnieje. Objęcie tej ścieżki bramką
//                  daje pętlę: callback → /login → logowanie → callback → …
//                  Ścieżka dokładna, nie prefix `/auth/` — nie otwieramy całej
//                  przestrzeni nazw.
//   `/apply/`, `/share/`, `/sign/`, `/cv/`, `/engagement/`
//                — linki tokenowe dla osób z zewnątrz (kandydat aplikuje,
//                  klient ogląda brandowane CV, podpis umowy, potwierdzenie
//                  engagementu). Ukośnik na końcu jest obowiązkowy: samo "/cv"
//                  łapałoby przez `startsWith` także wewnętrzny `/cv-generator`
//                  i wystawiło go publicznie.
//   `/preview/candidates`, `/preview/candidate-profile`, `/preview/contact-queue`,
//   `/preview/talent-radar`, `/preview/order-consultant-picker`,
//   `/preview/order-tile`,
//   `/preview/procedure-help`, `/preview/champion-profile`,
//   `/preview/client-playbook`, `/preview/inactive-clients-cleanup`,
//   `/preview/order-new-from-pdf`, `/preview/finance-order-changes`,
//   `/preview/finance-order-pdfs`, `/preview/order-takeover`,
//   `/preview/contract-candidate-contact`, `/preview/cv-search`,
//   `/preview/recruitment-v3`, `/preview/pipeline-v4`,
//   `/preview/jobs-list-v3`, `/preview/calendar-cycle`, `/preview/cv-qc`,
//   `/preview/cpro-queue`,
//   `/preview/kpi-targets`,
//   `/preview/candidates-list` (publiczny przez prefiks `/preview/candidates`)
//                — konkretne harnessy designu, po których może chodzić nightly
//                  Playwright (`e2e/candidate-ux-preview.spec.ts`) bez sesji.
//                  Renderują wyłącznie zahardkodowane mocki i nie wołają
//                  żadnego API (patrz components/candidates/preview/*). Gdy
//                  bramka deny-by-default objęła tę przestrzeń, wszystkie 9
//                  specow zaczęło dostawać 307 na /login i nightly był czerwony
//                  tygodniami.
//                  Ścieżki dokładne, NIE prefiks `/preview/` — reszta harnessów
//                  zostaje prywatna, bo `/preview/shell` renderuje prawdziwy
//                  `SidebarV2` (role-gating, liczniki), czyli wewnętrzną
//                  strukturę aplikacji. Test middleware pilnuje obu stron tej
//                  granicy.
const PUBLIC_PATHS = [
  "/login",
  "/register",
  "/auth/microsoft/callback",
  "/403",
  "/_next",
  "/favicon",
  "/public",
  "/share/",
  "/apply/",
  "/sign/",
  "/cv/",
  "/engagement/",
  "/preview/candidates",
  "/preview/candidate-profile",
  "/preview/contact-queue",
  "/preview/talent-radar",
  "/preview/order-consultant-picker",
  "/preview/order-lifecycle",
  "/preview/order-md-scopes",
  "/preview/order-takeover",
  "/preview/ezdrowie-contract-structure",
  "/preview/order-tile",
  "/preview/dl-alerts",
  "/preview/order-mail",
  "/preview/insights-campaign",
  "/preview/insights-seniority",
  "/preview/contracts-consolidation",
  "/preview/procedure-help",
  "/preview/champion-profile",
  "/preview/cv-generator-client-rules",
  "/preview/client-playbook",
  "/preview/inactive-clients-cleanup",
  "/preview/order-new-from-pdf",
  "/preview/jobs-list-v3",
  "/preview/new-job",
  "/preview/finance-order-changes",
  "/preview/finance-order-pdfs",
  "/preview/contract-candidate-contact",
  "/preview/cv-search",
  "/preview/jarvis",
  "/preview/recruitment-v3",
  "/preview/pipeline-v4",
  "/preview/my-people",
  "/preview/custom-dashboard",
  "/preview/calendar-cycle",
  "/preview/cv-qc",
  "/preview/cpro-queue",
  "/preview/kpi-targets",
  "/preview/kariera",
  "/preview/career-share",
  // Strona kariery (kandydaci z LinkedIna) — publiczna z definicji. Na własnym
  // hoście (`kariera.dynaminds.pl`) obsługuje ją `careerHostResponse` niżej;
  // tu jest wejście pod `/kariera/*` na hoście aplikacji (dev, podgląd, grafiki
  // OG). Ukośnik na końcu obowiązkowy — samo `/kariera` łapałoby każdą trasę
  // zaczynającą się tym ciągiem. Goły `/kariera` jest w `PUBLIC_EXACT_PATHS`.
  "/kariera/",
];

// Ścieżki publiczne dopasowywane DOKŁADNIE (bez `startsWith`).
const PUBLIC_EXACT_PATHS = ["/kariera"];

function isPublicPath(pathname: string): boolean {
  return (
    PUBLIC_EXACT_PATHS.includes(pathname) ||
    PUBLIC_PATHS.some((p) => pathname.startsWith(p))
  );
}

/**
 * Host strony kariery: żadnej logiki logowania, tylko przepisanie widocznych
 * adresów na trasy `/kariera/*`. Wszystko spoza listy (w tym każda trasa
 * aplikacji) dostaje terminalowe 404 kariery — granica jest domyślnie zamknięta,
 * więc nowa trasa NEXUSA nie wycieknie na domenę publiczną.
 */
function careerHostResponse(request: NextRequest): NextResponse {
  const route = resolveCareerRoute(request.nextUrl.pathname);
  if (route.kind === "pass") return NextResponse.next();
  const url = request.nextUrl.clone();
  if (route.kind === "rewrite") {
    url.pathname = route.path;
    return NextResponse.rewrite(url);
  }
  url.pathname = CAREER_NOT_FOUND_PATH;
  url.search = "";
  // Trasa-łapacz pod /kariera wywołuje notFound() → status 404 + terminalowe 404.
  return NextResponse.rewrite(url);
}

function resolveAccessRule(pathname: string): RouteAccessRule | undefined {
  // Sortuj po długości prefiksu malejąco — /candidates/123/edit pasuje do /candidates,
  // ale /admin/users pasuje do /admin (a nie do /, gdyby taki był).
  const sorted = [...ROLE_ROUTES].sort(
    (a, b) => b.prefix.length - a.prefix.length,
  );
  return sorted.find((r) => pathname.startsWith(r.prefix));
}

const ACCESS_RANK: Record<SectionAccess, number> = {
  none: 0,
  read: 1,
  write: 2,
};

function hasSignedSectionAccess(
  access: NonNullable<ReturnType<typeof decodeJwtPayload>>["sa"],
  section: ProductSection,
  required: Exclude<SectionAccess, "none">,
): boolean {
  if (!access) return false;
  const granted = access[section];
  if (granted !== "none" && granted !== "read" && granted !== "write") {
    return false;
  }
  return ACCESS_RANK[granted] >= ACCESS_RANK[required];
}

// Dekodowanie payloadu JWT (bez weryfikacji podpisu) współdzielone z warstwą
// kliencką — patrz src/lib/jwt.ts. Middleware działa w runtime edge i nie ma
// dostępu do SECRET_KEY; prawdziwa walidacja sygnatury odbywa się po stronie
// backendu (backend/app/api/deps.py::get_current_user). Tu tylko UX-guard.

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (isCareerHost(requestHost(request.headers))) {
    return careerHostResponse(request);
  }

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  const token = request.cookies.get(COOKIE_NAME)?.value;

  // Deny by default: wszystko poza PUBLIC_PATHS wymaga tokenu. `undefined`
  // oznacza tu tylko „brak zawężenia ról", a NIE „trasa niechroniona".
  const accessRule = resolveAccessRule(pathname);

  // Brak tokena na chronionej trasie → login.
  if (!token) {
    const loginUrl = new URL("/login", request.url);
    if (pathname !== "/") loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  const payload = decodeJwtPayload(token);
  if (!payload || isJwtExpired(payload.exp) || !payload.role) {
    const loginUrl = new URL("/login", request.url);
    if (pathname !== "/") loginUrl.searchParams.set("next", pathname);
    const response = NextResponse.redirect(loginUrl);
    // Wyczyść zepsute cookie — żeby unknąć pętli redirectów.
    response.cookies.delete(COOKIE_NAME);
    return response;
  }

  // Rola OK? (null = zalogowany wystarczy). Sprawdzamy UNIĘ ról (primary +
  // secondary z claim `roles`) — spójnie z Sidebar/RequireRole, które używają
  // roles[]. Fallback na sam `role` dla starych tokenów (sprzed deploya) bez
  // claim `roles`, żeby nie wyrzucać zalogowanych na /403 w okresie przejściowym.
  const userRoles = new Set<string>([
    payload.role as string,
    ...(payload.roles ?? []),
  ]);
  if (accessRule?.section && payload.sa) {
    if (
      !hasSignedSectionAccess(
        payload.sa,
        accessRule.section,
        accessRule.required ?? "read",
      )
    ) {
      return NextResponse.redirect(new URL("/403", request.url));
    }
    if (
      accessRule.enforceRoles &&
      accessRule.roles &&
      !accessRule.roles.some((role) => userRoles.has(role))
    ) {
      return NextResponse.redirect(new URL("/403", request.url));
    }
  } else if (accessRule?.roles) {
    if (!accessRule.roles.some((r) => userRoles.has(r as string))) {
      return NextResponse.redirect(new URL("/403", request.url));
    }
  }

  // Force-change-password gate: jeśli admin zresetował user'owi hasło,
  // claim `fpc=true` w JWT redirectuje wszędzie poza /profile (gdzie user
  // może hasło zmienić). Backend czyści flagę po POST /api/auth/change-password
  // i nowy login dostarcza JWT bez `fpc`.
  if (payload.fpc === true && !pathname.startsWith("/profile")) {
    const profileUrl = new URL("/profile", request.url);
    profileUrl.searchParams.set("force_password_change", "1");
    return NextResponse.redirect(profileUrl);
  }

  return NextResponse.next();
}

export const config = {
  // Matcher wykluczający API, assety Next.js, pliki statyczne.
  // Dopasowane zasady: wszystkie pathy pod "/" OPRÓCZ listy poniżej.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};
