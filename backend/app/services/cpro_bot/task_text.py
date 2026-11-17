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
Nordei (Cpro, {PORTAL_URL}). Logujesz się wpisem Vault „Nordea Cpro”.
Haseł nie wpisujesz nigdzie poza polem logowania tej strony.

Dla KAŻDEJ pozycji z listy items (po kolei, każda osobno):

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
                "| ambiguous_profile | cv_not_opening | login_failed | other",
                "message": "<krótko po polsku, co poszło nie tak; bez danych osobowych>",
            }
        ]
    }
