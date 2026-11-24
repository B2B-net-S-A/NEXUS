// Ćwiczenia Poligonu — cały onboarding pierwszego dnia (decyzja Artura z 14.11.2026:
// jedna ścieżka, bez poziomów; nowa osoba przechodzi ją w całości, zanim
// zacznie pracę). Ćwiczenie zalicza zdarzenie (klik w kotwicę, ruch albo zapis
// na rekrutacji ćwiczebnej, otwarcie ekranu), nigdy przycisk „Rozumiem”.
// Informacja zwrotna to stałe reguły, bez modelu AI — każdy dostaje tę samą.
//
// Ścieżka per rola (15.11.2026): rekruter, Delivery Lead i TCM przechodzą
// wspólne moduły (lista, Tablica, panel osoby, baza) i moduły swojej roli
// (rekruter: screening i przekazanie do QC; Delivery Lead: przegląd, kwoty
// i wysyłka do klienta). Admin i Head of Recruitment widzą wszystkie ćwiczenia.
//
// Narzędzia rekrutera (16.11.2026, Artur: „uczyć na poligonie”, także funkcji
// prawie nieużywanych): telefon screeningowy, termin u klienta, osoba z pliku
// CV, zapisane wyszukiwanie, lista, czat, asystent CV i Jarvis. Obecnym zalicza
// je praca z 60 dni (`backend/app/services/poligon_luki.py`).
//
// Id ćwiczeń (z przedrostkiem `poligon-`) i ich role są też w rejestrze serwera
// `backend/app/data/novelties/poligon.json`; test pilnuje, że to te same listy.

import type { PoligonAction } from "./store";

export type PoligonRole = "admin" | "head_of_recruitment" | "delivery_lead" | "talent_community_manager" | "recruiter";

export interface ExerciseContext {
  /** Osoba z pierwszej kolumny, którą ćwiczenie każe przesunąć. */
  firstNew: { candidateId: number; fullName: string } | null;
  /** Rola, z perspektywy której mówią treści ćwiczeń (kogo oznaczyć, kto poleca). */
  role: PoligonRole;
}

export type Verdict = { done: true; tip?: string } | { done: false; feedback: string } | null;

export interface Exercise {
  id: string;
  module: string;
  /** Czyja to ścieżka — lustro `roles` w `poligon.json`. */
  roles: readonly PoligonRole[];
  title: (ctx: ExerciseContext) => string;
  task: (ctx: ExerciseContext) => string;
  hint: string;
  /** Ekran, na którym ćwiczenie się zaczyna. */
  href: string;
  /** Kotwica `data-tour` / `data-help`, którą pokazuje „Pokaż mi”. */
  anchor: string;
  /** Klik w kotwicę zalicza ćwiczenie. */
  doneOnClick?: boolean;
  /**
   * Widoczna kotwica zalicza ćwiczenie („zajrzyj do…”). Nie zapytanie ekranu:
   * 24.11.2026 karta „CV do klienta” przestała pytać o `…/cv/branded/sources`
   * i ćwiczenie nie zaliczało się u osób z gotowym CV.
   */
  doneWhenVisible?: boolean;
  /** Ocena zdarzenia z poligonu: zaliczone, podpowiedź albo nic. */
  judge?: (action: PoligonAction, ctx: ExerciseContext) => Verdict;
  /** Dobra praktyka pokazywana po zaliczeniu. */
  tip: string;
  /** Plik do ćwiczenia (np. CV ćwiczebne do wgrania) — link w oknie ćwiczenia. */
  download?: { href: string; label: string };
}

export const POLIGON_JOB_HREF = "/jobs/990001";
/** Profil osoby ćwiczebnej w bazie kandydatów. */
const POLIGON_CANDIDATES_HREF = "/candidates";
/** Kody etapów w szablonie rekrutacji ćwiczebnej. */
const REJECTED = "rejected";
const VERIFIED = "verified";
/** „QC CV” ma w szablonie kod `interview` (etap 823). */
const QC_CV = "interview";
const CV_SENT = "cv_sent";
const MIN_NOTE_LENGTH = 25;
/** Pola karty, bez których Delivery Lead nie wyśle CV (ta sama lista co bramka serwera). */
const SCREENING_FIELDS: ReadonlyArray<[string, string]> = [
  ["location", "lokalizację"],
  ["work_mode", "tryb pracy"],
  ["recommendation", "„Dlaczego ten kandydat”"],
];

/** Terminy z maila klienta w ćwiczeniu DL-a: za ile dni roboczych i o której (czas przeglądarki). */
export const POLIGON_CLIENT_MAIL_SLOTS: ReadonlyArray<{ workdays: number; hour: number; quote: string }> = [
  { workdays: 1, hour: 10, quote: "najbliższy dzień roboczy o 10:00" },
  { workdays: 2, hour: 13, quote: "kolejny dzień roboczy o 13:00" },
];
export const POLIGON_CLIENT_MAIL_MINUTES = 45;
/** Mail klienta do ćwiczenia „Terminy od klienta” — wklejony w okno daje stały odczyt (`tools.ts`), bez modelu. */
export const POLIGON_CLIENT_MAIL =
  "Dzień dobry, chętnie porozmawiamy z Weroniką Cisowską. Pasuje nam " +
  `${POLIGON_CLIENT_MAIL_SLOTS.map((s) => s.quote).join(" albo ")}, rozmowa online potrwa ${POLIGON_CLIENT_MAIL_MINUTES} minut.`;

/** Budżet rekrutacji ćwiczebnej i stawka kandydata w przeglądzie DL-a (zestaw: `build_poligon_dataset.py`). */
export const POLIGON_BUDGET_MAX_HOURLY = 115;
export const POLIGON_CANDIDATE_HOURLY = 105;
const HOURS_PER_UNIT: Record<string, number> = { hourly: 1, daily: 8, monthly: 168 };

const EVERYONE: readonly PoligonRole[] = ["admin", "head_of_recruitment", "delivery_lead", "talent_community_manager", "recruiter"];
const RECRUITER: readonly PoligonRole[] = ["admin", "head_of_recruitment", "recruiter"];
const RECRUITER_AND_DL: readonly PoligonRole[] = ["admin", "head_of_recruitment", "delivery_lead", "recruiter"];
const DELIVERY_LEAD: readonly PoligonRole[] = ["admin", "head_of_recruitment", "delivery_lead"];
const RECRUITER_AND_TCM: readonly PoligonRole[] = ["admin", "head_of_recruitment", "talent_community_manager", "recruiter"];
/** CV ćwiczebne do wgrania (`public/poligon/`) — na poligonie NEXUS i tak „odczyta” Ewę Jesionowską. */
export const POLIGON_CV_FILE = "/poligon/cv-cwiczebne-ewa-jesionowska.txt";

/** Rola, z której perspektywy mówią ćwiczenia: rekruter ma pierwszeństwo (DL z rolą rekrutera robi oba). */
export function primaryRole(roles: readonly string[]): PoligonRole {
  if (roles.includes("recruiter")) return "recruiter";
  if (roles.includes("delivery_lead")) return "delivery_lead";
  if (roles.includes("talent_community_manager")) return "talent_community_manager";
  return "recruiter";
}

const isPoligonProfile = (path: string): boolean => /^\/api\/candidates\/99\d{4}\/notes-facts$/.test(path);
/** Parametry listy, które nie są szukaniem (strona, sortowanie, dociągane kolumny). */
const LIST_PARAM = /^(page|page_size|sort|semantics_version|view|include_.*)$/;

export const EXERCISES: readonly Exercise[] = [
  // ── Lista rekrutacji ────────────────────────────────────────────────
  {
    id: "lista-zakres",
    roles: EVERYONE,
    module: "Lista rekrutacji",
    title: () => "Przełącz „Moje / Wszystkie”",
    task: () => "Kliknij przełącznik nad listą. „Moje” to rekrutacje, w których jesteś w zespole, „Wszystkie” — cała firma.",
    hint: "Przełącznik jest na górze listy, po lewej.",
    href: "/jobs",
    anchor: "jobs.list.scope",
    doneOnClick: true,
    tip: "Dzień zaczynasz od „Moich”. „Wszystkie” przydają się, gdy szukasz rekrutacji kolegi albo klienta.",
  },
  {
    id: "lista-filtry",
    roles: EVERYONE,
    module: "Lista rekrutacji",
    title: () => "Otwórz filtry",
    task: () => "Kliknij w pasek filtrów. Tu zawężasz listę do klienta, statusu i osób.",
    hint: "Pasek filtrów jest nad listą rekrutacji.",
    href: "/jobs",
    anchor: "jobs.list.filters",
    doneOnClick: true,
    tip: "Filtry zostają w adresie strony — link z filtrem możesz wysłać komuś z zespołu.",
  },
  {
    id: "lista-otworz",
    roles: EVERYONE,
    module: "Lista rekrutacji",
    title: () => "Otwórz rekrutację ĆW-01",
    task: () => "Wpisz w szukajkę „bankowość” albo „ĆW-01” i kliknij nazwę rekrutacji. Otworzy się jej Tablica.",
    hint: "Szukanie działa od razu, bez Entera.",
    href: "/jobs",
    anchor: "jobs.list.title",
    doneOnClick: true,
    tip: "Na Tablicy widzisz wszystkie osoby tej rekrutacji, podzielone na etapy.",
  },

  // ── Tablica ─────────────────────────────────────────────────────────
  {
    id: "tablica-biore",
    roles: RECRUITER,
    module: "Tablica",
    title: () => "Weź osobę przyciskiem „Biorę”",
    task: () => "Kliknij „Biorę” na dowolnej karcie. Od teraz zespół widzi, że to Ty prowadzisz tę osobę.",
    hint: "„Biorę” jest w dolnym rogu karty.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.board.card",
    judge: (a) => (a.type === "claim" ? { done: true } : null),
    tip: "„Biorę” chroni przed tym, że dwie osoby dzwonią do tego samego kandydata.",
  },
  {
    id: "tablica-przesun",
    roles: EVERYONE,
    module: "Tablica",
    title: (ctx) => `Przesuń ${ctx.firstNew?.fullName ?? "osobę z „Nowych”"} na „Screening”`,
    task: (ctx) =>
      `Rozmowa telefoniczna poszła dobrze — ${ctx.firstNew?.fullName.split(" ")[0] ?? "ta osoba"} chce iść dalej. Przeciągnij kartę do kolumny „Screening” albo kliknij strzałkę → na karcie.`,
    hint: "Strzałka „dalej” jest w prawym dolnym rogu karty.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.board.card",
    judge: (a, ctx) => {
      if (a.type !== "move") return null;
      if (ctx.firstNew && a.candidateId !== ctx.firstNew.candidateId) {
        return { done: false, feedback: `To inna karta. W tym ćwiczeniu chodzi o ${ctx.firstNew.fullName} z kolumny „Nowi”.` };
      }
      if (a.toStage !== "screening") {
        return { done: false, feedback: "Karta pojechała na inny etap. Po pierwszej rozmowie osoba idzie na „Screening”." };
      }
      return { done: true };
    },
    tip: "Zanim przesuniesz osobę dalej, dopisz w panelu notatkę z rozmowy — zespół zobaczy, dlaczego idzie dalej.",
  },
  {
    id: "tablica-zrodla",
    roles: EVERYONE,
    module: "Tablica",
    title: () => "Zajrzyj, skąd brać kandydatów",
    task: () =>
      "Nad kolumnami jest pasek źródeł: osoby z ogłoszeń, Twoi ludzie, aplikacje, szukanie w bazie i dodawanie. Kliknij w ten pasek.",
    hint: "Pasek źródeł jest pod nagłówkiem rekrutacji, nad kolumnami.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.board.sources",
    doneOnClick: true,
    tip: "Zanim zaczniesz szukać na LinkedInie, sprawdź bazę NEXUSA — często ktoś pasujący już u nas był.",
  },
  {
    id: "tablica-moi-ludzie",
    roles: RECRUITER,
    module: "Tablica",
    title: () => "Otwórz „Moi ludzie”",
    task: () =>
      "„Moi ludzie” to osoby, z którymi już była rozmowa i które czekają na projekt. Kliknij kafelek „Moi ludzie” w pasku źródeł.",
    hint: "Kafelek „Moi ludzie” jest w pasku źródeł nad kolumnami.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.sources.my-people",
    doneOnClick: true,
    tip: "Każda osoba, którą dobrze poznasz w rozmowie, trafia do Twoich ludzi — przy następnym requeście masz ją pod ręką.",
  },

  // ── Panel osoby ─────────────────────────────────────────────────────
  {
    id: "panel-notatka",
    roles: EVERYONE,
    module: "Panel osoby",
    title: () => "Dodaj notatkę po rozmowie",
    task: () => "Kliknij kartę osoby, żeby otworzyć panel, i dodaj notatkę z ustaleniami rozmowy: stawka, dostępność, motywacja.",
    hint: "Pole notatki jest na dole panelu osoby.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.person.note",
    judge: (a) => {
      if (a.type !== "note") return null;
      if (a.content.length < MIN_NOTE_LENGTH) {
        return { done: false, feedback: "Ta notatka jest za krótka, żeby zespół z niej skorzystał. Napisz pełnym zdaniem: stawka, od kiedy, dlaczego zmienia pracę." };
      }
      return { done: true };
    },
    tip: "Notatkę widzi cały zespół rekrutacji i każdy, kto otworzy profil osoby — także za pół roku.",
  },
  {
    id: "panel-wzmianka",
    roles: EVERYONE,
    module: "Panel osoby",
    title: () => "Oznacz kogoś z zespołu w notatce",
    task: (ctx) =>
      ctx.role === "recruiter"
        ? "Napisz notatkę z pytaniem do Delivery Leada i oznacz go: wpisz „@”, wybierz „Anna Poligonowa” z listy i dokończ pytanie."
        : "Napisz notatkę z pytaniem do rekrutera i oznacz go: wpisz „@”, wybierz „Jakub Szkoleniowy” z listy i dokończ pytanie.",
    hint: "Po wpisaniu „@” w polu notatki pojawia się lista osób z zespołu.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.person.note",
    judge: (a) => {
      if (a.type !== "note") return null;
      if (!a.content.includes("@")) {
        return { done: false, feedback: "Notatka zapisana, ale nikt nie dostanie powiadomienia. Wpisz „@” i wybierz osobę z listy." };
      }
      return { done: true };
    },
    tip: "Oznaczona osoba dostaje powiadomienie. „@wszyscy” trafia do całego zespołu rekrutacji — używaj go oszczędnie.",
  },
  {
    id: "panel-odrzuc",
    roles: EVERYONE,
    module: "Panel osoby",
    title: () => "Odrzuć osobę z właściwym powodem",
    task: () => "W rozmowie padło 160 zł/h, a budżet to 115 zł/h. Otwórz panel osoby i odrzuć ją z powodem, który to opisuje.",
    hint: "„Odrzuć z powodem” jest w górnej części panelu osoby.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.person.actions",
    judge: (a) => {
      if (a.type !== "move" || a.toStage !== REJECTED) return null;
      const reason = (a.rejectionReasonName ?? "").toLowerCase();
      if (reason.includes("finans")) return { done: true };
      if (reason.startsWith("inne")) {
        return { done: false, feedback: "„Inne” to ostatnia deska ratunku: raporty i propozycje nie widzą, co było nie tak, nawet z opisem. Tu problemem była stawka — wybierz powód o oczekiwaniach finansowych i wpisz kwotę z rozmowy." };
      }
      return { done: false, feedback: `Wybrany powód to „${a.rejectionReasonName ?? "inny powód"}”. Tu problemem była stawka — wybierz powód o oczekiwaniach finansowych.` };
    },
    tip: "Przy powodzie finansowym osoba wróci w propozycjach, gdy przyjdzie request z wyższą stawką.",
  },

  // ── Screening i weryfikacja ─────────────────────────────────────────
  {
    id: "screening-otworz",
    roles: RECRUITER,
    module: "Screening i weryfikacja",
    title: () => "Otwórz formularz screeningu",
    task: () =>
      "Otwórz panel osoby z kolumny „Screening” i przejdź na zakładkę „Screening”. Kliknij w formularz — to pytania od klienta i karta, którą zobaczy Delivery Lead.",
    hint: "Zakładka „Screening” jest w panelu osoby, obok „CV” i „Notatek”.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.person.screening-form",
    doneOnClick: true,
    tip: "Pytania screeningowe przychodzą z Profilu Championa rekrutacji — zadajesz je w rozmowie i od razu wpisujesz odpowiedzi.",
  },
  {
    id: "screening-bramka",
    roles: RECRUITER,
    module: "Screening i weryfikacja",
    title: () => "Spróbuj zweryfikować osobę bez screeningu",
    task: () =>
      "Przesuń osobę ze „Screeningu” na „Zweryfikowany”, zanim wypełnisz formularz. Zobacz, co NEXUS powie.",
    hint: "Przeciągnij kartę z kolumny „Screening” do „Zweryfikowany” albo użyj strzałki na karcie.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.board.card",
    judge: (a) => {
      if (a.type === "gate") return { done: true };
      if (a.type === "move" && a.toStage === VERIFIED) return { done: true };
      return null;
    },
    tip: "Bramka „Zweryfikowany” pilnuje minimum dla Delivery Leada: arkusz screeningu, stawka, lokalizacja, tryb pracy i „Dlaczego ten kandydat”.",
  },
  {
    id: "screening-zapisz",
    roles: RECRUITER,
    module: "Screening i weryfikacja",
    title: () => "Wypełnij i zapisz screening",
    task: () =>
      "W zakładce „Screening” wpisz odpowiedzi na pytania, uzupełnij lokalizację, tryb pracy i „Dlaczego ten kandydat”, a potem zapisz formularz.",
    hint: "Przycisk zapisu jest na dole formularza screeningu.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.person.screening-form",
    judge: (a) => {
      if (a.type !== "screening") return null;
      const missing = SCREENING_FIELDS.filter(([key]) => !(a.fields[key] ?? "").trim()).map(([, label]) => label);
      if (!a.sheetSaved) missing.unshift("odpowiedzi na pytania");
      if (missing.length) {
        return { done: false, feedback: `Zapisane, ale Delivery Lead nie dostanie kompletu. Brakuje: ${missing.join(", ")}.` };
      }
      return { done: true };
    },
    tip: "„Dlaczego ten kandydat” pisz dla klienta: dwa, trzy konkretne powody z rozmowy, nie ogólniki.",
  },
  {
    id: "screening-zweryfikuj",
    roles: RECRUITER,
    module: "Screening i weryfikacja",
    title: () => "Zweryfikuj osobę",
    task: () => "Screening jest zapisany — przesuń tę osobę na „Zweryfikowany”. To jedna z Twoich dziennych weryfikacji.",
    hint: "Karta jest w kolumnie „Screening”.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.board.card",
    judge: (a) => {
      if (a.type === "gate") {
        return { done: false, feedback: `NEXUS dalej czegoś nie ma: ${a.missing.join(", ")}. Uzupełnij to w zakładce „Screening” tej osoby i zapisz.` };
      }
      if (a.type === "move" && a.toStage === VERIFIED) return { done: true };
      return null;
    },
    tip: "Weryfikacje to Twój główny wynik dnia — licznik „Weryfikacje” na górnym pasku pokazuje, ile już masz.",
  },

  // ── Rekomendacja do klienta ─────────────────────────────────────────
  {
    id: "rekomendacja-cv",
    roles: RECRUITER_AND_DL,
    module: "Rekomendacja do klienta",
    title: () => "Zajrzyj do CV dla klienta",
    task: () =>
      "Kliknij Jakuba Jaworka w „Zweryfikowanym”, a w jego panelu „Rozwiń” (u góry po prawej). W zakładce „CV” jest oryginalne CV i karta „CV do klienta”, z której generator robi CV w szablonie klienta.",
    hint: "„Rozwiń” jest u góry panelu osoby, obok krzyżyka.",
    href: POLIGON_JOB_HREF,
    anchor: "person.cv.to-client-card",
    doneWhenVisible: true,
    tip: "Klient dostaje CV w swoim szablonie i bez danych kontaktowych — nigdy nie wysyłaj oryginału.",
  },
  {
    id: "rekomendacja-qc",
    roles: RECRUITER,
    module: "Rekomendacja do klienta",
    title: () => "Przekaż zweryfikowaną osobę do QC CV",
    task: () =>
      "Osoba ze „Zweryfikowanego” ma gotowe CV. Przesuń ją na „QC CV” — tam CV sprawdza kontrola jakości, a potem Delivery Lead wysyła je klientowi.",
    hint: "Kolumna „QC CV” jest zaraz za „Zweryfikowanym”.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.board.card",
    judge: (a) => {
      if (a.type !== "move" || a.fromStage !== VERIFIED) return null;
      if (a.toStage === QC_CV) return { done: true };
      if (a.toStage === REJECTED || a.toStage === "withdrawn") return null;
      return { done: false, feedback: "CV do klienta idzie zawsze przez „QC CV” — nie przeskakuj tego etapu." };
    },
    tip: "Rekomendacja liczy się, kiedy CV trafi do klienta. Ty dostarczasz zweryfikowaną osobę i dobre CV, DL je wysyła.",
  },

  // ── Przegląd Delivery Leada (ścieżka DL) ────────────────────────────
  {
    id: "dl-przeglad-otworz",
    roles: DELIVERY_LEAD,
    module: "Przegląd Delivery Leada",
    title: () => "Otwórz przegląd osoby z „QC CV”",
    task: () =>
      "W kolumnie „QC CV” czekają dwie osoby po kontroli CV. Kliknij „Przejrzyj i wyślij” na karcie jednej z nich: obok CV zobaczysz wymagania, ocenę rekrutera, kwoty i decyzję.",
    hint: "Przycisk „Przejrzyj i wyślij” jest na karcie w kolumnie „QC CV”.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.board.card",
    judge: (a) => (a.type === "view" && a.path === "/api/dl-review/context" ? { done: true } : null),
    tip: "Przegląd zaczynasz od wymagań: brak w wymaganiu „musi” to zwykle powód do poprawy albo odrzucenia, nie do wysyłki.",
  },
  {
    id: "dl-wyslij",
    roles: DELIVERY_LEAD,
    module: "Przegląd Delivery Leada",
    title: () => "Wyślij CV do klienta ze stawką w budżecie",
    task: () =>
      `Osoba chce ${POLIGON_CANDIDATE_HOURLY} zł/h, a budżet rekrutacji to do ${POLIGON_BUDGET_MAX_HOURLY} zł/h. W przeglądzie wpisz stawkę do klienta, sprawdź marżę i kliknij „Akceptuj”. Stawka ma się zmieścić w budżecie i dać marżę.`,
    hint: "Pole „Stawka do klienta” jest w kolumnie decyzji, nad przyciskiem „Akceptuj”.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.board.card",
    judge: (a) => {
      if (a.type !== "move" || a.fromStage !== QC_CV || a.toStage !== CV_SENT) return null;
      const again = "Przeciągnij kartę z „CV wysłane” z powrotem na „QC CV” i wyślij jeszcze raz.";
      const rate = a.clientRate;
      if (!rate) return { done: false, feedback: `CV poszło bez stawki do klienta. ${again}` };
      if (rate.currency !== "PLN") {
        return { done: false, feedback: `Budżet tej rekrutacji jest w złotówkach — stawka w ${rate.currency} utrudni klientowi porównanie. ${again}` };
      }
      const hourly = rate.value / (HOURS_PER_UNIT[rate.unit] ?? 1);
      if (hourly > POLIGON_BUDGET_MAX_HOURLY) {
        return { done: false, feedback: `${formatHourly(hourly)} to ponad budżet klienta (do ${POLIGON_BUDGET_MAX_HOURLY} zł/h). Klient odrzuci CV albo zażąda niższej stawki. ${again}` };
      }
      if (hourly <= POLIGON_CANDIDATE_HOURLY) {
        return { done: false, feedback: `Przy ${formatHourly(hourly)} do klienta i ${POLIGON_CANDIDATE_HOURLY} zł/h dla kandydata firma nic nie zarabia. Stawka do klienta musi być wyższa od stawki kandydata. ${again}` };
      }
      return { done: true };
    },
    tip: "Marżę widzisz od razu pod stawką. Gdy jest poniżej mediany u klienta, NEXUS ostrzeże — wtedy zastanów się, czy stawka do klienta nie jest za niska.",
  },
  {
    id: "dl-poprawki",
    roles: DELIVERY_LEAD,
    module: "Przegląd Delivery Leada",
    title: () => "Oddaj CV rekruterowi do poprawy",
    task: () =>
      "Druga osoba z „QC CV” nie ma potwierdzonego angielskiego, a klient go wymaga. Otwórz jej przegląd, kliknij „Wróć do poprawy…”, zaznacz, co rekruter ma poprawić, i oddaj.",
    hint: "„Wróć do poprawy…” jest w stopce kolumny decyzji przeglądu.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.board.card",
    judge: (a) => {
      if (a.type !== "move" || a.fromStage !== QC_CV || a.toStage !== VERIFIED) return null;
      if (!a.fixFields.length) {
        return { done: false, feedback: "Osoba wróciła do rekrutera, ale bez zaznaczonych pól nie wie, co poprawić. Przeciągnij ją z powrotem na „QC CV” i oddaj z zaznaczonymi polami." };
      }
      return { done: true };
    },
    tip: "Rekruter widzi zaznaczone pola podświetlone w formularzu screeningu i dostaje dzwonek. Im dokładniej zaznaczysz, tym szybciej CV wróci.",
  },
  {
    id: "dl-terminy-klienta",
    roles: DELIVERY_LEAD,
    module: "Przegląd Delivery Leada",
    title: () => "Wpisz terminy rozmowy od klienta",
    task: () =>
      `Klient odpisał na CV Weroniki Cisowskiej: „${POLIGON_CLIENT_MAIL}” Otwórz jej panel w kolumnie „CV wysłane”, kliknij „Terminy od klienta”, wpisz oba terminy (albo wklej maila w pole okna), ustaw ${POLIGON_CLIENT_MAIL_MINUTES} min i kliknij „Wyślij rekruterowi”. Gdy „CV wysłane” jest puste (np. po przeładowaniu strony), najpierw wyślij Weronikę z „QC CV” do klienta.`,
    hint: "„Terminy od klienta” jest w panelu osoby, w rzędzie przycisków obok „Odrzuć z powodem”.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.person.dock",
    judge: (a) => {
      if (a.type !== "slot_request") return null;
      const again = "Kliknij „Terminy od klienta” jeszcze raz, popraw i wyślij — „Zastąp otwarte terminy” podmieni poprzednie.";
      const times = a.starts.map((s) => {
        const d = new Date(s);
        return d.getHours() * 60 + d.getMinutes();
      });
      const missing = POLIGON_CLIENT_MAIL_SLOTS.filter((s) => !times.includes(s.hour * 60));
      if (missing.length) {
        return { done: false, feedback: `Rekruter dostał terminy, ale bez ${missing.map((s) => `${s.hour}:00`).join(" i ")} z maila klienta. ${again}` };
      }
      if (a.durationMinutes !== POLIGON_CLIENT_MAIL_MINUTES) {
        return { done: false, feedback: `Klient pisał o ${POLIGON_CLIENT_MAIL_MINUTES} minutach, a terminy poszły na ${a.durationMinutes} min — rekruter zablokuje kandydatowi zły czas. ${again}` };
      }
      return { done: true };
    },
    tip: "Terminy dostaje rekruter: ustala jeden z kandydatem i odsyła Ci wybór, a Ty potwierdzasz go klientowi. Karta sama przeszła na „Rozmowę u klienta”.",
  },

  // ── Baza kandydatów ─────────────────────────────────────────────────
  {
    id: "baza-szukaj",
    roles: EVERYONE,
    module: "Baza kandydatów",
    title: () => "Wyszukaj w bazie kandydatów",
    task: (ctx) =>
      ctx.role === "recruiter"
        ? "Delivery Lead poleca Laurę Olszyńską z Twoich ludzi. Znajdź ją w bazie: wpisz „Olszyńska” w szukajkę na górze ekranu."
        : "Rekruter poleca Laurę Olszyńską. Znajdź ją w bazie: wpisz „Olszyńska” w szukajkę na górze ekranu.",
    hint: "Szukajka po nazwisku jest na górze ekranu „Kandydaci”, słowa kluczowe — pod nią.",
    href: POLIGON_CANDIDATES_HREF,
    anchor: "candidates.list.search",
    judge: (a) =>
      a.type === "view" && a.path === "/api/candidates" && Object.entries(a.query).some(([k, v]) => !LIST_PARAM.test(k) && v.trim())
        ? { done: true }
        : null,
    tip: "Słowa kluczowe „Musi mieć” i filtry (stawka, lokalizacja, tryb pracy) zawężają wynik — zacznij szeroko, zawężaj stopniowo.",
  },
  {
    id: "baza-profil",
    roles: EVERYONE,
    module: "Baza kandydatów",
    title: () => "Otwórz profil osoby",
    task: () => "Kliknij Laurę Olszyńską na liście. Otworzy się jej profil: CV, rekrutacje, notatki i historia.",
    hint: "Imię i nazwisko na liście to link do profilu.",
    href: POLIGON_CANDIDATES_HREF,
    anchor: "candidates.list.name",
    judge: (a) => (a.type === "view" && isPoligonProfile(a.path) ? { done: true } : null),
    tip: "Zanim zadzwonisz, przeczytaj notatki i historię — ktoś mógł już z tą osobą rozmawiać.",
  },
  {
    id: "baza-przypisz",
    roles: EVERYONE,
    module: "Baza kandydatów",
    title: () => "Przypisz osobę do rekrutacji",
    task: () => "Na profilu kliknij „Przypisz do rekrutacji” i przy rekrutacji ĆW-01 kliknij „Przypisz”. Laura pojawi się w kolumnie „Nowi”.",
    hint: "Przycisk przypisania jest w nagłówku profilu.",
    href: POLIGON_CANDIDATES_HREF,
    anchor: "candidate.profile.assign",
    judge: (a) => (a.type === "assign" ? { done: true } : null),
    tip: "Przypisuj od razu po decyzji, że dzwonisz — wtedy zespół widzi, że osoba jest już w procesie.",
  },
  {
    id: "baza-lista",
    roles: RECRUITER_AND_TCM,
    module: "Baza kandydatów",
    title: () => "Dodaj osobę do swojej listy",
    task: () =>
      "Laura nie pasuje do każdej rekrutacji, ale chcesz ją mieć pod ręką. Na jej profilu kliknij „Na listę” (w nagłówku, obok „Przypisz do rekrutacji”), wpisz nazwę nowej listy, np. „PM bankowość”, i kliknij „+”.",
    hint: "„Na listę” jest w nagłówku profilu, obok „Przypisz do rekrutacji”.",
    href: POLIGON_CANDIDATES_HREF,
    // Przewodnik profilu ma komplet 6 kotwic — „Pokaż mi” wskazuje sąsiedni przycisk.
    anchor: "candidate.profile.assign",
    judge: (a) => (a.type === "pool_add" ? { done: true } : null),
    tip: "Listy są Twoje („Tylko ja”). Znajdziesz je w „Moi ludzie” → „Listy” — przy nowym requeście zaczynasz od nich, nie od zera.",
  },
  {
    id: "baza-zapisane-wyszukiwanie",
    roles: RECRUITER_AND_TCM,
    module: "Baza kandydatów",
    title: () => "Zapisz wyszukiwanie z powiadomieniem",
    task: () =>
      "Na liście kandydatów zawęź wynik, np. wpisz w słowa kluczowe „Scrum”. Potem kliknij „Zapisane”, nadaj nazwę i zapisz z zaznaczonym „Powiadamiaj…”. NEXUS da znać, gdy do bazy trafi ktoś nowy, kto pasuje.",
    hint: "„Zapisane” jest nad listą kandydatów, obok filtrów.",
    href: POLIGON_CANDIDATES_HREF,
    anchor: "candidates.list.saved",
    judge: (a) => {
      if (a.type !== "saved_search") return null;
      if (!a.notify) {
        return { done: false, feedback: "Zapisane, ale bez powiadomienia — NEXUS nie da znać o nowych osobach. Zapisz jeszcze raz z zaznaczonym „Powiadamiaj…” albo włącz dzwonek przy tym zapisie." };
      }
      if (!a.criteria) {
        return { done: false, feedback: "Ten zapis nie ma żadnego kryterium, więc powiadomienie łapałoby każdą nową osobę w bazie. Wpisz słowo kluczowe albo ustaw filtr i zapisz jeszcze raz." };
      }
      return { done: true };
    },
    tip: "Zapisz wyszukiwanie przy każdym trudnym requeście: baza rośnie codziennie, a dzwonek powie Ci, gdy pojawi się ktoś nowy.",
  },

  // ── Źródła i kalendarz ──────────────────────────────────────────────
  {
    id: "zrodla-cv-z-pliku",
    roles: RECRUITER,
    module: "Źródła i kalendarz",
    title: () => "Dodaj osobę z pliku CV",
    task: () =>
      "Ktoś przysłał CV mailem. W pasku źródeł kliknij „Dodaj” → „Dodaj z pliku CV” i wgraj plik (możesz pobrać CV ćwiczebne niżej). Sprawdź, co odczytał NEXUS: pola oznaczone do sprawdzenia popraw w profilu.",
    hint: "„Dodaj” jest na końcu paska źródeł nad kolumnami.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.board.sources",
    download: { href: POLIGON_CV_FILE, label: "Pobierz CV ćwiczebne" },
    judge: (a) => (a.type === "cv_upload" ? { done: true } : null),
    tip: "NEXUS odczytuje CV sam, ale e-mail, telefon i lata doświadczenia sprawdź wzrokiem — błąd w kontakcie to stracony kandydat.",
  },
  {
    id: "kalendarz-telefon",
    roles: RECRUITER,
    module: "Źródła i kalendarz",
    title: () => "Umów telefon screeningowy",
    task: () =>
      "Otwórz panel osoby z „Nowych” albo „Screeningu” i kliknij „Umów telefon”. Wybierz termin i kliknij „Umów” — telefon trafi do Twojego kalendarza, a karta pokaże, kiedy dzwonisz.",
    hint: "„Umów telefon” jest w panelu osoby, obok „Nie odebrał”.",
    href: POLIGON_JOB_HREF,
    anchor: "screening-call.book",
    judge: (a) => (a.type === "screening_call" ? { done: true } : null),
    tip: "Umówiony telefon to też „Biorę”: zespół widzi, że ta osoba jest Twoja, a NEXUS przypomni Ci 15 minut przed.",
  },
  {
    id: "kalendarz-termin-klienta",
    roles: RECRUITER,
    module: "Źródła i kalendarz",
    title: () => "Wybierz z kandydatem termin rozmowy u klienta",
    task: () =>
      "Klient przysłał trzy terminy rozmowy dla Kamila Dębowskiego (kolumna „Rozmowa u klienta”, przewiń Tablicę w prawo). Kamil może w drugim. Otwórz jego panel, kliknij „Wybierz termin z kandydatem”, zaznacz drugi termin i wpisz go do kalendarza.",
    hint: "Przycisk jest w panelu osoby, w sekcji „Rozmowa u klienta”.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.person.dock",
    judge: (a) => {
      if (a.type !== "slot_choose") return null;
      if (a.index !== 1) {
        return { done: false, feedback: "Wpisany termin to nie ten, który pasuje Kamilowi. W tym ćwiczeniu wybierz drugi z trzech terminów (na poligonie zaczniesz od nowa przyciskiem „Od nowa” na pasku)." };
      }
      return { done: true };
    },
    tip: "Termin wybierasz z kandydatem przez telefon, a Delivery Lead potwierdza go klientowi — dlatego karta czeka teraz na DL-a.",
  },

  // ── Zespół i AI ─────────────────────────────────────────────────────
  {
    id: "zespol-czat",
    roles: RECRUITER_AND_DL,
    module: "Zespół i AI",
    title: () => "Napisz w czacie rekrutacji",
    task: (ctx) =>
      ctx.role === "recruiter"
        ? "Kliknij ikonę dymka w nagłówku rekrutacji i przejdź na „Czat zespołu”. Napisz do Delivery Leada: wpisz „@”, wybierz „Anna Poligonowa” i zadaj pytanie o rekrutację."
        : "Kliknij ikonę dymka w nagłówku rekrutacji i przejdź na „Czat zespołu”. Napisz do rekrutera: wpisz „@”, wybierz „Jakub Szkoleniowy” i napisz, czego potrzebujesz.",
    hint: "Ikona dymka („Historia i czat”) jest w nagłówku rekrutacji, po prawej.",
    href: POLIGON_JOB_HREF,
    anchor: "jobs.board.chat",
    judge: (a) => {
      if (a.type !== "chat") return null;
      if (!a.mentions.length) {
        return { done: false, feedback: "Wiadomość jest w czacie, ale nikt nie dostał powiadomienia. Wpisz „@” i wybierz osobę z listy." };
      }
      return { done: true };
    },
    tip: "Czat rekrutacji to sprawy całej rekrutacji (klient, budżet, priorytety). Pytanie o jedną osobę pisz w notatce na jej karcie — zostanie w jej historii.",
  },
  {
    id: "zespol-cv-ai",
    roles: RECRUITER,
    module: "Zespół i AI",
    title: () => "Popraw CV poleceniem AI",
    task: () =>
      "Otwórz panel Heleny Wrzosek ze „Screeningu”, zakładkę „CV”, i w karcie „CV do klienta” kliknij „Otwórz i popraw”. W asystencie po prawej napisz „pogrub Scrum i Jira” i wyślij.",
    hint: "„Otwórz i popraw” jest w zakładce „CV” panelu osoby, w karcie „CV do klienta”.",
    href: POLIGON_JOB_HREF,
    anchor: "person.cv.to-client-card",
    judge: (a) => {
      if (a.type === "cv_command" && a.operations === 0) {
        return { done: false, feedback: "Asystent nic nie zmienił. Napisz konkretnie, co i gdzie — tu: „pogrub Scrum i Jira”." };
      }
      if (a.type === "cv_applied" && a.operations > 0) return { done: true };
      return null;
    },
    tip: "Zmiana asystenta świeci w CV na zielono i cofniesz ją jednym kliknięciem. Nie dopisuj faktów, których kandydat nie potwierdził — asystent zapyta o źródło.",
  },
  {
    id: "zespol-jarvis",
    roles: RECRUITER,
    module: "Zespół i AI",
    title: () => "Zapytaj Jarvisa o osobę z Tablicy",
    task: () =>
      "Otwórz Jarvisa (⌘J na Macu, Ctrl+J na Windowsie albo postać w prawym dolnym rogu) i zapytaj o kogoś z Tablicy, np. „Co wiemy o Helenie Wrzosek?”.",
    hint: "Jarvis otwiera się też z wyszukiwarki na górze: „Zapytaj Jarvisa”.",
    href: POLIGON_JOB_HREF,
    anchor: "jarvis.mascot.hide",
    judge: (a) => {
      if (a.type !== "jarvis") return null;
      if (a.candidateId === null) {
        return { done: false, feedback: "Jarvis nie znalazł tej osoby na Tablicy. Zapytaj o kogoś z kart, podając imię i nazwisko." };
      }
      return { done: true };
    },
    tip: "Pytaj Jarvisa jak kolegę z zespołu: „co wiemy o…”, „kto czeka najdłużej”, „napisz maila do…”. Odpowiedź sprawdzaj — to podpowiedź, nie wyrocznia.",
  },
];

function formatHourly(value: number): string {
  return `${value.toLocaleString("pl-PL", { maximumFractionDigits: 2 })} zł/h`;
}

/** Ścieżka osoby: ćwiczenia każdej jej roli, w kolejności listy (lustro `PoligonPlan.exercises_for`). */
export function exercisesFor(roles: readonly string[]): readonly Exercise[] {
  return EXERCISES.filter((e) => e.roles.some((r) => roles.includes(r)));
}
