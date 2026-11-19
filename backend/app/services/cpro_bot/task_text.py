"""Polecenie dla rutyny „NEXUS Cpro” w Grok Bocie i kształt raportu.

Kroki są przepisane z nagrań Sandry (osoba od Cpro, 28.10.2026). Rutyna
dostaje to polecenie w treści każdego webhooka (``task``), więc zmiana
procedury to zmiana tego pliku, a nie polecenia wklejonego w bota.
"""

from __future__ import annotations

from typing import Any

PORTAL_URL = "https://nordea.onevms.se/nordea/vendor/"
SUBCONTRACTOR_COMPANY = "B2B.net S.A."

TASK = f"""Jesteś botem, który wrzuca kandydatów firmy B2B.net do portalu dostawcy
Nordei (Cpro, {PORTAL_URL}). Konto wybierasz OSOBNO dla każdej pozycji z
items[].cpro_account. Nigdy nie używaj wspólnego wpisu „Nordea Cpro” ani
konta pozostałego z poprzedniej pozycji. Hasła i loginy odczytuj tylko z Vault;
używaj ich wyłącznie w formularzu logowania tego portalu. Nie umieszczaj ich
w raportach, logach, wiadomościach, notatkach ani plikach.

Dla KAŻDEJ pozycji z listy items (po kolei, każda osobno):

0. Sprawdź cpro_account: dozwolone są WYŁĄCZNIE delivery_lead_id = 14
   z vault_entry = „Nordea Cpro – Igor” albo delivery_lead_id = 27 z
   vault_entry = „Nordea Cpro – Marcin”. Brak obiektu, inne ID, niezgodny wpis
   Vault albo brak tego wpisu → skipped, reason "account_unknown", bez
   jakichkolwiek zmian w Cpro. Nie zgaduj konta po nazwisku kandydata,
   rekruterze, autorze ruchu ani request_number.
   Otwórz nową, odizolowaną sesję portalu dla tej pozycji (bez cookies
   poprzednich pozycji), zaloguj się WYŁĄCZNIE wskazanym wpisem Vault i
   sprawdź konto widoczne w portalu względem tożsamości z tego wpisu.
   Nie wystarczy istniejąca sesja, nazwa zakładki ani udane otwarcie strony.
   Nie możesz odizolować sesji lub potwierdzić konta → skipped, reason
   "account_unverified"; portal pokazuje inne konto → skipped, reason
   "account_mismatch". Logowanie nie powiodło się → failed, reason
   "login_failed". W każdym z tych przypadków NIE otwieraj formularza,
   nie pobieraj CV i nie zapisuj profilu, szkicu ani oferty. Przejdź do
   następnej pozycji. Nie przełączaj na inne konto, żeby obejść brak dostępu.
1. Requests → wyszukaj request_number, otwórz request. Request nie istnieje
   albo jest zamknięty (Closed/Cancelled) → wynik failed, reason
   "request_not_found" albo "request_closed". Nic nie dodawaj.
2. W sekcji „Our offers” sprawdź tę osobę (imię i nazwisko). Ma już ofertę
   w stanie innym niż DRAFT (SELECTION, SUBMITTED, REJECTED itd.) → wynik
   skipped, reason "already_offered", podaj status. Ma DRAFT → otwórz ten
   szkic (View → Edit) i przejdź do kroku 5.
3. „Profiles”: wyszukaj imię i nazwisko. Jest dokładnie jeden profil tej
   osoby → kliknij „Offer…” i przejdź do kroku 5. Kilka profili o tym
   imieniu i nazwisku i nie da się wskazać właściwego → failed, reason
   "ambiguous_profile".
4. Brak profilu → „Add Consultant”: First name = candidate.first_name,
   Last name = candidate.last_name; Title puste, chyba że portal pokazuje już
   inną osobę o tym samym imieniu i nazwisku — wtedy Title =
   candidate.profile_title; Country of citizenship = candidate.citizenship
   (wybierz z listy, np. „PL - Poland”); Gender = Other; Birth year bez zmian;
   Employment status = Self-employed (B2B) / subcontractor; Subcontractor
   company = {SUBCONTRACTOR_COMPANY}; CV = plik z kroku 6;
   Focus skills, Industries, Best roles puste; Description =
   candidate.profile_description dokładnie jak w zleceniu. Save, potem
   „Offer…” przy tym profilu.
5. Formularz oferty:
   - Frame agreement — Vendor: zostaw wybraną; gdy pusta, wybierz jedyną
     aktywną umowę ramową.
   - Offered rate = offer.rate (liczba), Currency = PLN.
   - CV: wgraj plik z kroku 6 („Upload new CV”) i zaznacz TYLKO ten nowy plik
     (odznacz starsze CV tej osoby).
   - Motivation = offer.motivation dokładnie jak w zleceniu (każdy punkt od
     myślnika, bez pustych linii).
   - Available from = offer.available_from (RRRR-MM-DD).
   - Physical location = offer.physical_location dokładnie jak w zleceniu.
   - Former consultant at Nordea / Former employee at Nordea: z
     offer.former_consultant i offer.former_employee (true = Yes, false = No).
     Gdy wartość to null, rozstrzygnij z CV: Nordea jako pracodawca = Former
     employee Yes; praca dla Nordei przez inną firmę = Former consultant Yes;
     Nordei w CV brak = oba No.
   - Accepts dates and hours: zostaw bez zmian.
   - Employment status = Self-employed (B2B) / subcontractor; Subcontractor
     company = {SUBCONTRACTOR_COMPANY}; Subcontractor rate = 0,00;
     Is the consultant a UK tax resident? = No.
   - Matching: wszystkie pięć suwaków (Experience & Education, Profile,
     Bank and Finance Industry, Assignment, Total) na „Perfect”.
   - Zapisz jako szkic (Save). Otwórz wgrane CV podglądem w ofercie: musi się
     otworzyć. Nie otwiera się → failed, reason "cv_not_opening".
6. Plik CV pobierz przed formularzem: GET offer.cv_url z nagłówkiem
   X-Run-Token: <token>. Zapisz go pod nazwą offer.cv_file_name.
7. submit = true → kliknij „Submit Offer” i wróć na request: w „Our offers”
   ta osoba ma status SELECTION (albo inny niż DRAFT). Zapisz status.
   submit = false → zostaw szkic (DRAFT), nic nie wysyłaj.

Zasady:
- Tożsamość konta z kroku 0 obowiązuje przez całą pozycję. Przekierowanie do
  logowania, zmiana sesji lub niepewna tożsamość → przerwij pozycję bez
  kolejnych zapisów, skipped, reason "account_unverified". Przed każdym
  Save i „Submit Offer” ponownie potwierdź właściwe konto. Po zakończeniu
  pozycji zamknij jej sesję; następna zaczyna od kroku 0 nawet dla tego
  samego Delivery Leada.
- Nie zmieniaj niczego w innych ofertach, profilach ani requestach.
- Nie wpisuj żadnych danych spoza zlecenia. Brak pola w zleceniu = zostaw
  wartość domyślną portalu.
- Błąd przy jednej osobie nie zatrzymuje pozostałych.
- Nie zapisuj danych osób, tokenu ani plików CV w notatkach, pamięci ani
  plikach po zakończeniu biegu.

Na koniec wyślij JEDNO żądanie:
POST callback_url
Content-Type: application/json
X-Run-Token: <token>
z treścią w kształcie report_format (bez dodatkowych pól)."""


def report_format() -> dict[str, Any]:
    return {
        "items": [
            {
                "ref": "<ref pozycji ze zlecenia, liczba>",
                "outcome": "submitted | draft | failed | skipped",
                "cpro_status": "<status oferty w Cpro, np. SELECTION albo DRAFT>",
                "offer_url": "<adres oferty w Cpro, https://nordea.onevms.se/...>",
                "reason": "request_not_found | request_closed | already_offered "
                "| ambiguous_profile | cv_not_opening | login_failed "
                "| account_unknown | account_unverified | account_mismatch | other",
                "message": "<krótko po polsku, co poszło nie tak; bez danych osobowych>",
            }
        ]
    }
