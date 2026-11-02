# Zbiorcze wyniki firmy: tylko Rada i admin (decyzja Artura 02.11.2026)
<!-- indeks: mail board_monthly_report tylko Rada i admin, „Moduł Finanse” go nie otwiera; pojedyncze kwoty przy kontrakcie zostają; ekrany w osobnym PR-ze po decyzji -->

1. dnia roboczego listopada „Podsumowanie Rady” z przychodem i marżą firmy
dostało 11 osób, w tym 5 z działu Finanse. Nie była to awaria: odbiorców
wyznaczało `reads_board_money` (rola Rada albo „Moduł Finanse”), a Finanse mają
to uprawnienie domyślnie. Artur: takie podsumowania mają iść do Rady i adminów,
do nikogo więcej. Finanse pracują na pojedynczych rekordach. Kwota przy
konkretnym kontrakcie jest w porządku, a jedno kliknięcie pokazujące wszystkie
marże i podsumowanie całości już nie.

- **Mail:** `action_permissions.receives_company_results` (rola `board` albo
  `admin`) wyznacza odbiorców `board_monthly_report` i listę „Maile do Ciebie”
  (`notification_email_prefs._board_monthly`). Nadanie „Modułu Finanse” osobie
  tego maila nie otwiera. Odczyt sekcji Insights nadal jest warunkiem.
- **`board_placement_alert`** od początku idzie tylko do roli `board`.
- **Ekrany jeszcze nie są zmienione.** `reads_board_money` i `BoardReader` dalej
  otwierają Finansom Insights → Firma i Raporty. Zmiana czeka na decyzję
  z makiet, bo dotyka pracy działu Finanse.
- **Nowy mail lub raport ze zbiorczą kwotą firmy** bierze odbiorców
  z `receives_company_results`, nie z `reads_board_money`.
