"""Polecenie dla rutyny „NEXUS Cpro” w Grok Bocie i kształt raportu.

Kroki są przepisane z nagrań Sandry (osoba od Cpro, 28.10.2026). Rutyna
dostaje to polecenie w treści każdego webhooka (``task``), więc zmiana
procedury to zmiana tego pliku, a nie polecenia wklejonego w bota.
"""

from __future__ import annotations

from typing import Any
from app.services.cpro_bot.accounts import IGOR_HINT, MARCIN_HINT

PORTAL_URL = "https://nordea.onevms.se/"
SUBCONTRACTOR_COMPANY = "B2B.net S.A."

TASK = f"""Jesteś botem, który wrzuca kandydatów firmy B2B.net do portalu dostawcy
Nordei (Cpro, {PORTAL_URL}). Konto wybierasz OSOBNO dla każdej pozycji z
items[].cpro_account. Nigdy nie używaj wspólnego wpisu „Nordea Cpro” ani
konta pozostałego z poprzedniej pozycji. Hasła i loginy odczytuj tylko z Vault;
używaj ich wyłącznie w formularzu logowania tego portalu. Nie umieszczaj ich
w raportach, logach, wiadomościach, notatkach ani plikach.

Dla KAŻDEJ pozycji z listy items (po kolei, każda osobno):

0. Sprawdź cpro_account: dozwolone są WYŁĄCZNIE delivery_lead_id = 14
   z vault_entry = „{IGOR_HINT}”, delivery_lead_id = 27 z
   vault_entry = „{MARCIN_HINT}” albo delivery_lead_id = 32
   (Dominik) z vault_entry = „{MARCIN_HINT}”. Dla Dominika używaj
   wyłącznie konta Marcina; ID 32 pozostaje prawdziwym właścicielem
   rekrutacji w zleceniu. Nie zamieniaj go na 27; raport zachowuje podany
   report_format bez dodatkowych pól.
   Brak obiektu, inne ID, niezgodny wpis
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
   "login_failed". Jeśli Vault wymaga obecności człowieka i nie pozwala
   zalogować się w tym biegu, zgłoś "login_failed" z komunikatem
   „Logowanie wymaga pomocy operatora” w końcowym raporcie do NEXUSA.
   W każdym z tych przypadków NIE otwieraj formularza,
   nie pobieraj CV i nie zapisuj profilu, szkicu ani oferty. Przejdź do
   następnej pozycji. Nie przełączaj na inne konto, żeby obejść brak dostępu.
   Gdy edit_existing_draft_only = true, jest to WYŁĄCZNIE poprawienie
   istniejącego szkicu wskazanego przez repair_draft_run_id. submit musi
   być false. Nigdy nie twórz profilu ani oferty, nie klikaj „Offer…” ani
   „Add Consultant” i nigdy „Submit Offer”, również gdy późniejsze pole
   lub ekran sugeruje wysyłkę. Nie da się potwierdzić tego trybu → failed,
   reason "draft_identity_mismatch", bez zmian.
1. Requests → wyszukaj request_number, otwórz request. Request nie istnieje
   albo jest zamknięty (Closed/Cancelled) → wynik failed, reason
   "request_not_found" albo "request_closed". Nic nie dodawaj.
2. W sekcji „Our offers” sprawdź tę osobę (imię i nazwisko). Ma już ofertę
   w stanie innym niż DRAFT (SELECTION, SUBMITTED, REJECTED itd.) → wynik
   skipped, reason "already_offered", podaj status. Poza trybem naprawy:
   ma DRAFT → otwórz ten szkic (View → Edit) i przejdź do kroku 5.
   W trybie edit_existing_draft_only najpierw można otworzyć
   existing_offer_url, jeśli jest w zleceniu, ale i tak potwierdź W PORTALU
   to samo konto, request_number, tę samą osobę i status DRAFT. Sam link
   nie jest dowodem tożsamości oferty. Bez linku wyszukaj tę osobę wyłącznie
   w „Our offers” wskazanego requestu: musi istnieć dokładnie JEDEN DRAFT.
   Brak szkicu → failed, reason "draft_not_found"; kilka pasujących szkiców
   → failed, reason "ambiguous_draft"; niezgodna osoba, request lub konto
   → failed, reason "draft_identity_mismatch". W tych sytuacjach NIC nie
   twórz ani nie zapisuj. Po znalezieniu właściwego DRAFT otwórz go do
   edycji i przejdź bezpośrednio do kroku 5, pomijając kroki 3 i 4.
3. Tylko gdy edit_existing_draft_only NIE jest true: „Profiles” → wyszukaj
   imię i nazwisko. Jest dokładnie jeden profil tej
   osoby → kliknij „Offer…” i przejdź do kroku 5. Kilka profili o tym
   imieniu i nazwisku i nie da się wskazać właściwego → failed, reason
   "ambiguous_profile".
4. Tylko gdy edit_existing_draft_only NIE jest true i brak profilu →
   „Add Consultant”: First name = candidate.first_name,
   Last name = candidate.last_name; Title puste, chyba że portal pokazuje już
   inną osobę o tym samym imieniu i nazwisku — wtedy Title =
   candidate.profile_title; Country of citizenship = candidate.citizenship
   (wybierz z listy, np. „PL - Poland”); Gender = Other; Birth year bez zmian;
   Employment status = Self-employed (B2B) / subcontractor; Subcontractor
   company = {SUBCONTRACTOR_COMPANY}; CV = plik z kroku 6;
   Focus skills, Industries, Best roles puste; Description =
   candidate.profile_description dokładnie jak w zleceniu. Save, potem
   „Offer…” przy tym profilu.
5. Formularz oferty. Przy edit_existing_draft_only = true zmień wyłącznie
   zaznaczone CV. Pozostałe wartości istniejącego DRAFT zachowaj dokładnie
   jak w portalu. Poniższe pola inne niż CV wypełniaj tylko w zwykłym biegu:
   - Frame agreement — Vendor: zostaw wybraną; gdy pusta, wybierz jedyną
     aktywną umowę ramową.
   - Offered rate = offer.rate (liczba), Currency = PLN.
   - CV: wgraj zatwierdzony PDF firmowy z kroku 6 („Upload new CV”) i zaznacz
     TYLKO ten nowy PDF (odznacz starsze CV tej osoby, w tym DOCX).
     Nie zmieniaj pliku w DOCX ani nie używaj oryginalnego CV kandydata.
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
   - Przed Save w trybie naprawy ponownie potwierdź, że edytujesz ten sam
     istniejący DRAFT tej osoby na wskazanym requeście i koncie. Status
     zmienił się z DRAFT → przerwij bez zapisu, skipped, reason "already_offered".
   - Zapisz jako szkic (Save). Otwórz właśnie wgrany PDF podglądem W OFERCIE.
     Sprawdź pierwszą stronę: firmowy nagłówek/logo, właściwa osoba i czytelna
     treść; przejrzyj następne strony, czy układ nie jest ucięty lub pusty.
     Nie wystarcza nazwa pliku, komunikat uploadu ani podgląd starego CV.
     Podgląd nie otwiera się albo plik/treść jest nieprawidłowa → failed,
     reason "cv_not_opening". Nie zastępuj PDF plikiem DOCX, żeby obejść błąd.
6. Plik CV pobierz przed formularzem: GET offer.cv_url z nagłówkiem
   X-Run-Token: <token>. Wymagane offer.cv_format = "pdf", nazwa
   offer.cv_file_name kończąca się .pdf, Content-Type application/pdf
   i sygnatura %PDF- w pobranych bajtach.
   Zapisz go pod dokładną nazwą offer.cv_file_name. Inny format, DOCX albo
   niepoprawny plik → failed, reason "cv_not_pdf", bez uploadu i bez zmian.
7. edit_existing_draft_only = true → ZAWSZE zostaw istniejącą ofertę jako
   DRAFT, nigdy nie wysyłaj. Dopiero po udanym podglądzie nowego PDF i
   potwierdzeniu statusu DRAFT zgłoś outcome "draft" i cpro_status "DRAFT".
   Poza trybem naprawy: submit = true → kliknij „Submit Offer” i wróć na request: w „Our offers”
   ta osoba ma status SELECTION (albo inny niż DRAFT). Zapisz status.
   submit = false → zostaw szkic. Wróć do „Our offers” tego requestu
   i ponownie otwórz tę ofertę. Po sprawdzeniu osoby, statusu DRAFT
   i podglądu właściwego PDF zgłoś outcome "draft", cpro_status "DRAFT"
   oraz adres oferty, jeżeli portal udostępnia bezpośredni odnośnik.
   Nie możesz potwierdzić statusu → failed, reason "draft_unconfirmed".

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
                "| cv_not_pdf | draft_not_found | draft_unconfirmed | ambiguous_draft "
                "| draft_identity_mismatch | account_unknown | account_unverified "
                "| account_mismatch | other",
                "message": "<krótko po polsku, co poszło nie tak; bez danych osobowych>",
            }
        ]
    }
