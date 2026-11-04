/**
 * Odmowy serwera, które ludzie dostają raz za razem, po ludzku — Jarvis
 * pokazuje je po TRZECIEJ takiej samej odmowie w dwie minuty
 * (`refusal-tracker.ts`). Bez modelu: tekst stały, ton propozycji.
 *
 * Klucz = `detail.code` (albo `detail.reason`) z odpowiedzi API. Każdy klucz
 * musi istnieć w backendzie — pilnuje `error-explainers.test.ts`, więc kod
 * przemianowany po jednej stronie nie zostawi tu martwego wyjaśnienia.
 */

import { permissionLabel } from "@/lib/permissions";

export interface ErrorExplainer {
  title: string;
  text: string;
  /** Kotwica `data-help` do podświetlenia (opcjonalnie). */
  anchor?: string;
}

/**
 * Gdzie administrator przełącza uprawnienia. Wyjaśnienia odmów nazywają
 * UPRAWNIENIE (z katalogu, tą samą nazwą co ekran), nie rolę: od 0410 to ono
 * decyduje na trasie, a role mają je tylko domyślnie.
 */
const PERMISSIONS_SCREEN = "Ustawienia → Zespół i dostęp → Osoby i role";

export const ERROR_EXPLAINERS: Readonly<Record<string, ErrorExplainer>> = {
  DEBRIEF_REQUIRED: {
    title: "Najpierw debrief po rozmowie",
    text: "Kandydat wyjdzie z „Rozmowy u klienta”, gdy zapiszesz debrief: pytania, które zadał klient, albo potwierdzenie, że ich nie było. Najszybciej zrobisz to w Kalendarzu, w „Do zrobienia”.",
  },
  debrief_questions_required: {
    title: "Brakuje pytań klienta",
    text: "Debrief wymaga pytań zadanych przez klienta. Jeśli klient o nic nie pytał, zaznacz „klient nie zadawał pytań”.",
  },
  CANDIDATE_CLAIMED: {
    title: "Tę osobę prowadzi teraz ktoś inny",
    text: "Osoba dodana do Nowych jest przez 12 godzin zarezerwowana dla rekrutera, który ją wziął. Przejąć ją mogą Delivery Lead, Head of Recruitment i admin — albo poczekaj, aż rezerwacja wygaśnie.",
  },
  ELIGIBILITY_WARNING: {
    title: "Kandydat ma ostrzeżenie",
    text: "System wstrzymał ruch, bo kandydat ma ostrzeżenie (np. czarna lista albo weto hiring managera). Przeczytaj powód w oknie i, jeśli to w porządku, użyj „Przenieś mimo to”.",
  },
  PIPELINE_VERSION_CONFLICT: {
    title: "Ktoś właśnie przesunął tę osobę",
    text: "Kartę przesunął ktoś inny, zanim zapisał się Twój ruch. Tablica się odświeżyła — sprawdź, gdzie jest teraz osoba, i zdecyduj jeszcze raz.",
  },
  permission_denied: {
    title: "Brakuje Ci uprawnienia do tej operacji",
    text: `Ponowna próba nic nie zmieni — komunikat podaje nazwę uprawnienia, którego nie ma Twoje konto. Poproś administratora, żeby włączył je w ${PERMISSIONS_SCREEN}.`,
  },
  finance_amounts_only: {
    title: "Możesz zmieniać tylko kwoty",
    text: `Masz uprawnienie „${permissionLabel("amounts_edit")}”, ale inne pola kontraktu i zamówienia wymagają uprawnienia „${permissionLabel("contracts_orders_edit")}”. Zmień wyłącznie kwoty albo poproś o resztę osobę, która je ma.`,
  },
  finance_fields_forbidden: {
    title: "Brakuje uprawnienia do stawek i kwot",
    text: `Kwoty zapisuje osoba z uprawnieniem „${permissionLabel("amounts_edit")}”, a w zamówieniach także ta, która prowadzi zamówienia i ma „${permissionLabel("amounts_view")}”. Zapisz pozostałe pola bez kwot albo poproś administratora o brakujące uprawnienie (${PERMISSIONS_SCREEN}).`,
  },
  b2b_end_date_requires_termination: {
    title: "Umowa B2B jest bezterminowa",
    text: "Daty zakończenia umowy B2B nie wpisuje się ręcznie. Jeśli współpraca się kończy, użyj „Zakończ współpracę” na kontrakcie — wtedy data zapisze się sama.",
  },
  ending_requires_end_date: {
    title: "„Kończący się” wymaga daty końca",
    text: "Status „Kończący się” działa tylko z datą zakończenia. Dla umowy B2B zakończenie ustawia „Zakończ współpracę”.",
  },
  section_access_denied: {
    title: "Brak dostępu do tej części NEXUSA",
    text: `Twoje konto nie ma dostępu do tej części (albo ma tylko podgląd). Dostęp do klientów, kontraktów, zamówień i Finansów wynika z uprawnień — poproś administratora, żeby włączył właściwe w ${PERMISSIONS_SCREEN}.`,
  },
  action_access_denied: {
    title: "Brak uprawnienia do tej akcji",
    text: "Widzisz ten ekran, ale ta konkretna akcja wymaga uprawnienia, którego Twoje konto nie ma. Poproś administratora, jeśli jest Ci potrzebna.",
  },
  metric_scope_denied: {
    title: "Za szeroki zakres danych",
    text: "Ta metryka dla całego zespołu albo firmy nie jest dostępna dla Twojej roli. Zmień zakres na „moje”.",
  },
  offboarding_decision_required: {
    title: "Najpierw decyzja o puli MD",
    text: "Po odejściu konsultanta z zamówienia MD trzeba zdecydować, co z jego pulą: usuń, przenieś na inną osobę albo przywróć. Sprawa czeka w panelu „Moi klienci” i na karcie zamówienia.",
  },
  order_group_not_open: {
    title: "Zamówienie jest zamknięte",
    text: "Tego zamówienia nie da się już zmieniać. Jeśli współpraca trwa, użyj „Przywróć” na karcie zamówienia albo dodaj nowe zamówienie.",
  },
  md_pool_exhausted: {
    title: "Pula MD się skończyła",
    text: "W tym zamówieniu nie zostało MD do przydzielenia. Skoryguj budżet zamówienia albo dodaj nowe zamówienie.",
  },
  consultant_already_on_group_order: {
    title: "Ta osoba jest już na zamówieniu MD",
    text: "Konsultant ma żywą linię zamówienia MD u tego klienta, więc drugie zamówienie okresowe zdublowałoby współpracę. Zmień istniejące zamówienie zamiast dodawać nowe.",
  },
  order_integrity_conflict: {
    title: "Zapis kłóci się z danymi zamówienia",
    text: "Zmiana narusza spójność zamówienia (np. daty albo budżet). Sprawdź pola wskazane w komunikacie i spróbuj ponownie.",
  },
  profile_facts_version_conflict: {
    title: "Profil zmienił się w innym oknie",
    text: "Ktoś (albo Ty w innej karcie) zmienił w międzyczasie ten fakt. Odśwież profil i zapisz jeszcze raz.",
  },
  DASHBOARD_VERSION_CONFLICT: {
    title: "Pulpit zmieniony w innej karcie",
    text: "Układ pulpitu zapisał się w innej karcie przeglądarki. Odśwież stronę, żeby nie nadpisać tamtych zmian.",
  },
  PRIORITY_VERSION_CONFLICT: {
    title: "Ktoś właśnie zmienił priorytety",
    text: "Lista priorytetów zmieniła się w międzyczasie. Odśwież ją i nanieś swoją zmianę jeszcze raz.",
  },
  TAC_OWNER_REQUIRED: {
    title: "Wskaż opiekuna rekrutacji",
    text: "Ten klient ma kilku opiekunów — przy zakładaniu rekrutacji trzeba wskazać jednego.",
  },
  cv_review_required: {
    title: "CV czeka na kontrolę treści",
    text: "Przed zatwierdzeniem CV musi przejść kontrolę treści. Otwórz CV, przejrzyj uwagi i zatwierdź ponownie.",
  },
};

export function explainerFor(code: string | null | undefined): ErrorExplainer | null {
  if (!code) return null;
  return ERROR_EXPLAINERS[code] ?? null;
}
