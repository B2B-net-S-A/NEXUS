# Klient › Konsultanci: kto u klienta pracuje, w jednym wierszu (18.11.2026)

<!-- indeks: `?tab=konsultanci`, `ClientConsultantsTab`, „Wymaga uwagi” (`consultant_order_state`), `pending_consultants`, rejestr klienta z Kontraktów, karta w Przeglądzie -->

Decyzja Artura z 18.11.2026 (wariant B makiety „Kontrakty i Klienci”). „Kto
u klienta pracuje” stało w pięciu miejscach: nagłówek, sekcja „Konsultanci”
w Przeglądzie, osoby pod zamówieniami, rejestr klienta w module Kontrakty
i mapa działów. Teraz jest jedna lista w grupie „Konsultanci” (zaraz po
Przeglądzie), a obok niej „Zamówienia” i „Importy MD” pod dawnymi kluczami.

- **Wiersz = kontrakt u klienta:** umowa (status, od kiedy), bieżące zamówienie
  (obowiązujące dziś, a bez niego najnowsze — widać, od kiedy brakuje), stawka
  godzinowa z zamówienia z kosztową w podpisie, marża miesięczna, „Wymaga uwagi”,
  akcje (Przedłuż, pola rejestru, kontrakt). Podzakładki: Obecni · Wymaga uwagi ·
  Planowani · Szkice (tylko gdy są) · Zakończeni (stara tabela archiwum).
- **„Wymaga uwagi” liczy serwer, istniejącymi regułami** (`services/consultant_order_state.py`):
  `notice` = status `ending`; `no_current_order` = reguła flagi „bez projektu”
  dla COMPASS (`lacks_current_order`, przeniesiona z `integrations_compass.py`,
  linia MD bez dat bierze okres grupy); `order_ending` = `ending_without_successor`,
  ta sama co pigułka „Bez kontynuacji 30 dni” w Zamówieniach. Planowanej umowy nie
  oznaczamy brakiem zamówienia. Nie dokładaj trzeciej definicji „bez zamówienia”;
  raport Finansów „Kontrakty bez zamówienia” mierzy co innego (brak PDF-u).
- **Dane z `GET /api/clients/{id}/profile`** — to samo zapytanie co nagłówek
  („Aktywni konsultanci”), więc liczby się zgadzają. Szkice i umowy do podpisu
  w `pending_consultants`: poza licznikami i „Aktywnym MRR”, kwoty redagowane jak
  u planowanych. Relacje kontraktu w `_profile_contract_loads()` (każda brakująca
  to `MissingGreenlet`).
- **Rejestr klienta z Kontraktów przeszedł tutaj:** kolumny „Projekt” (nr i nazwa)
  i „Prolongata” (wybór w wierszu, `ProlongationSelect`) pokazują się tylko, gdy
  klient je wypełnia; ołówek otwiera `ContractRegisterDialog` (nr projektu, okres,
  pula godzin), „Nowy kontrakt” i „Eksport” jak w rejestrze. Filtry okresu
  i podkategorii zniknęły razem z trybem. W Kontraktach wybór klienta otwiera
  `/clients/{id}?tab=konsultanci`, a stary `?client=` przekierowuje tam samo.
- **Przegląd** ma kartę „Konsultanci”: liczby i do 5 osób z „Wymaga uwagi”,
  przycisk „Wszyscy konsultanci”. Pełna tabela w Przeglądzie nie wraca.
- Testy: `app/clients/[id]/__tests__/ClientConsultantsTab.test.tsx`,
  `app/contracts/__tests__/page-navigation.test.tsx`, backend
  `tests/test_consultant_order_state.py`, `tests/test_client_profile.py`.
