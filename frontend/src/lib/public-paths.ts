/**
 * Ścieżki dostępne bez sesji — jedno źródło dla `src/middleware.ts` (bramka
 * logowania) i `components/AppVersionGuard.tsx` (kto dostaje przeładowanie
 * po wdrożeniu). Opis poszczególnych wpisów: komentarz w `src/middleware.ts`.
 *
 * Moduł bez importów z `next/server`, żeby mógł trafić do paczki przeglądarki.
 */

export const PUBLIC_PATHS = [
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
  // Panel klienta pod linkiem z CV: token w adresie, klient nie ma konta.
  "/k/",
  // Rekrutacja własna: wybór terminu z linku w mailu.
  "/t/",
  "/engagement/",
  // Warunki od kandydata (17.11.2026): link z maila po aplikacji, token w adresie.
  "/warunki/",
  // Raport kompetencji (25.11.2026): zmiana warunków i wypis z linku w mailu, token w adresie.
  "/raport/",
  // Publiczny podpis protokołu sprzętu: token w adresie, bez logowania.
  "/protocol/",
  // Strefa konsultanta: konsultant nie ma konta, API ma własny wyłącznik i sesję.
  "/konsultant/",
  // Wypis konsultanta z komunikatów informacyjnych: token w adresie, konsultant
  // nie ma konta (etap 3, O12).
  "/wypis/",
  "/preview/client-panel",
  "/preview/candidates",
  "/preview/candidate-profile",
  "/preview/contact-queue",
  "/preview/talent-radar",
  "/preview/order-consultant-picker",
  "/preview/order-lifecycle",
  "/preview/order-md-scopes",
  "/preview/order-ended-lines",
  "/preview/order-takeover",
  "/preview/ezdrowie-contract-structure",
  "/preview/order-tile",
  // Zakładka „Zamówienia” profilu klienta (wersja B, tabela z panelem) —
  // cała `MultiConsultantOrdersTab` na zasianym cache, sieć odcięta.
  "/preview/client-orders",
  "/preview/dl-alerts",
  "/preview/order-mail",
  "/preview/insights",
  "/preview/insights-seniority",
  "/preview/contracts-consolidation",
  "/preview/procedure-help",
  "/preview/champion-profile",
  "/preview/cv-generator-client-rules",
  "/preview/cv-generator",
  "/preview/client-playbook",
  "/preview/inactive-clients-cleanup",
  "/preview/contract-docs-sharepoint",
  // Foldery w zakładce Dokumenty kontraktu (0494); zasiany cache, sieć odcięta.
  "/preview/contract-documents-folders",
  "/preview/order-new-from-pdf",
  "/preview/jobs-list-v3",
  "/preview/new-job",
  "/preview/finance-order-changes",
  "/preview/finance-order-pdfs",
  // Odświeżony wygląd Klientów i Finansów (02.10.2026): lista klientów
  // z „Kluczowymi relacjami”, zakładki profilu klienta i „Wyniki miesięczne”.
  "/preview/clients-list",
  "/preview/client-profile-tabs",
  "/preview/finance-results",
  "/preview/contract-candidate-contact",
  "/preview/cv-search",
  "/preview/jarvis",
  "/preview/recruitment-v3",
  "/preview/pipeline-v4",
  "/preview/job-detail",
  "/preview/my-people",
  "/preview/custom-dashboard",
  // „Jakość podpowiedzi systemu” (silnik „Nowi na 20”, 23.10.2026), dane fikcyjne.
  "/preview/autofill-quality",
  // Ustawienia → „Powiadomienia”: Moje · Kto co dostaje · Maile · Reguły etapów.
  "/preview/notification-settings",
  // Okienko „Wiadomości” (dawniej „Czaty”) z górnego paska: ikona i lista rozmów.
  "/preview/chat-notifications",
  // Ikony „CV” i „Rekrutacje” z górnego paska (bez dzwonka), dane fikcyjne.
  "/preview/topbar-topics",
  // Okienko „Rozmowy” z górnego paska: rozmowy u klienta i prepy, dane fikcyjne.
  "/preview/interview-notifications",
  // Licznik celów w górnym pasku: segmenty, panel po kliknięciu, replika paska.
  "/preview/kpi-topbar",
  // Lista „Kto się liczy” za celami (17.10.2026): wiersze, filtry stanu, rama kafla.
  "/preview/kpi-who-counts",
  "/preview/calendar-cycle",
  "/preview/cv-qc",
  "/preview/cv-editor",
  // Karta „CV do klienta” — panel „Z czego powstało” i liczba do sprawdzenia
  // (13.10.2026); zasiany cache, sieć odcięta.
  "/preview/cv-to-client",
  "/preview/cpro-queue",
  "/preview/candidate-followup",
  // Ustawienia → Ocena prepów (0505): wagi, tematy, skala, historia; `?tryb=odczyt`.
  "/preview/prep-review-settings",
  "/preview/kpi-targets",
  // Ustawienia → „Ranking kandydatów” (21.10.2026): wagi, podgląd, pomiar.
  "/preview/ranking-panel",
  // Ustawienia → „Osoby i role” (0410): dziewięć przełączników, okno osoby.
  "/preview/permissions",
  "/preview/b2b-documents",
  "/preview/b2b-generator",
  // Wzory własne Generatora (asystent prawny, 0786): studio, lista, „Nowy dokument”.
  "/preview/custom-templates",
  // Asystent prawny: „Popraw dokument” (część D) i zgodność z umową ramową
  // klienta (część G) — dane fikcyjne, zasiany cache, bez zapytań.
  "/preview/legal-redline",
  "/preview/similar-reassign",
  "/preview/kariera",
  "/preview/career-share",
  "/preview/candidate-merge",
  // Okno „Dodaj kandydatów do pipeline”: imiennicy, telefon, „Już w tej rekrutacji”.
  "/preview/add-candidates",
  "/preview/job-ad",
  // „Strona kariery do uzupełnienia” (21.10.2026) — kolejka na danych w pamięci.
  "/preview/career-queue",
  // Umowa przedwstępna (0506) — sekcja panelu, lista i kafelek na danych w pamięci.
  "/preview/pre-contracts",
  "/preview/job-portals",
  "/preview/consultant-panel",
  "/preview/request-allocation",
  // Strona „Daily — requesty i obłożenie” (`/jobs/daily`), wariant daily pulpitu.
  "/preview/daily",
  // Panel „Zespół” rekrutacji: Delivery Lead · Rekruter · Kategoria (02.10.2026).
  "/preview/job-team-panel",
  // Rekrutacja „Wstrzymana” (26.11.2026): pigułka, pas, okno, panel DL — zapis lokalny.
  // Profil Championa w czterech zakładkach (04.10.2026).
  "/preview/champion-workspace",
  "/preview/plain-brief",
  // 0404: „Odrzuceni przez AI” i plakietki przeglądu zgłoszeń.
  "/preview/job-board-screening",
  // 0424: jeden formularz screeningu z podglądem CV obok.
  "/preview/screening-form",
  // Przegląd Delivery Leada: karta, uwagi dla rekrutera, „Wróć do poprawy”.
  "/preview/dl-review",
  "/preview/dl-send",
  // Okno odrzucenia z podglądem maila do kandydata (13.10.2026).
  "/preview/rejection-email",
  // Ustawienia → „Klucze API”: konta serwisowe, klucze, ostatnie zapisy (14.10.2026).
  "/preview/api-keys",
  // „Ludzie w NEXUSIE” (17.10.2026): harnessy 14 makiet — fikcja, zero zapytań
  // (strażnik `app/preview/__tests__/hr-harnesses.test.ts`).
  "/preview/hr-dashboard",
  "/preview/hr-my-time",
  "/preview/hr-calendar",
  "/preview/hr-approvals",
  "/preview/hr-person",
  "/preview/hr-payroll",
  "/preview/hr-offboarding",
  "/preview/hr-onboarding",
  "/preview/hr-care",
  "/preview/hr-client-tech",
  "/preview/hr-cases",
  "/preview/hr-equipment",
  "/preview/hr-equipment-issue",
  // Etap 2 (17.10.2026): struktura, „Mój zespół”, struktura u klienta.
  "/preview/hr-structure",
  "/preview/hr-team",
  "/preview/hr-client-people",
  // Propozycje struktury u klienta i akcept DL (18.10.2026).
  "/preview/hr-client-structure",
  "/preview/hr-announcements",
  "/preview/hr-settlements",
  "/preview/hr-consents",
  // Finanse → „Wydatki ze zgodą” (Zgody, etap 3 — 0486, 20.10.2026).
  "/preview/finance-approved-expenses",
  "/preview/hr-documents",
  "/preview/hr-agreements",
  // Katalog z listą rozjazdów kartoteka ↔ konto (19.10.2026).
  "/preview/hr-people",
  "/preview/client-invoicing",
  // Sprzedaż → Szanse (Atlas → NEXUS, 27.10.2026), fikcyjne dane.
  "/preview/sales",
  // Szkolenia (13.11.2026): karta szkolenia i biblioteka, fikcja, zero zapytań.
  "/preview/trainings",
  // Strona kariery (kandydaci z LinkedIna) — publiczna z definicji. Na własnym
  // hoście (`kariera.dynaminds.pl`) obsługuje ją `careerHostResponse` niżej;
  // tu jest wejście pod `/kariera/*` na hoście aplikacji (dev, podgląd, grafiki
  // OG). Ukośnik na końcu obowiązkowy — samo `/kariera` łapałoby każdą trasę
  // zaczynającą się tym ciągiem. Goły `/kariera` jest w `PUBLIC_EXACT_PATHS`.
  "/kariera/",
];

// Ścieżki publiczne dopasowywane DOKŁADNIE (bez `startsWith`).
export const PUBLIC_EXACT_PATHS = ["/kariera", "/konsultant", "/wtyczka/prywatnosc"];

/**
 * Runda 10 (R10-N10-1): harnessy `/preview/*` są publiczne wyłącznie poza
 * buildem produkcyjnym (`next dev`, vitest) albo przy jawnej fladze builda
 * `NEXT_PUBLIC_PREVIEW_PUBLIC=1` (stack E2E w `docker-compose.e2e.yml`, na nim
 * chodzi nocny `preview-chromium`, i drugi build w kolejce merge'ów w `ci.yml`,
 * na którym harnessy są bramką scalenia). Do 27.09.2026 każdy bez sesji oglądał
 * nazwiska, klientów i stawki z danych harnessów. Od 08.11.2026 obraz
 * produkcyjny w ogóle nie ma tych stron (`frontend/Dockerfile`), a to sprawdzenie
 * zostaje jako druga warstwa. Czytane przy wywołaniu (nie stała modułu), żeby
 * testy mogły przełączać środowisko; Next wstawia obie wartości przy buildzie.
 */
export function previewHarnessesArePublic(): boolean {
  return (
    process.env.NODE_ENV !== "production" ||
    process.env.NEXT_PUBLIC_PREVIEW_PUBLIC === "1"
  );
}

export function isPublicPath(pathname: string): boolean {
  if (pathname.startsWith("/preview/") && !previewHarnessesArePublic()) {
    return false;
  }
  return (
    PUBLIC_EXACT_PATHS.includes(pathname) ||
    PUBLIC_PATHS.some((p) => pathname.startsWith(p))
  );
}
