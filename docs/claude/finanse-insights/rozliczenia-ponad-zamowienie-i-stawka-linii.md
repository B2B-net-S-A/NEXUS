# Rozliczenia: ponad zamówienie, zamówienie zakończone i stawka linii (0774, 24.11.2026)

Próba IX–X 2026: w 5 przypadkach MD były dobre, a rozliczenie czekało na Finanse,
bo zamówienie w NEXUS-ie się nie domykało (ponad pulę albo mail klienta wskazał
zamówienie zakończone w NEXUS-ie). „Mało MD” (21 MD) ostrzegało DL wcześniej, ale
milkło po odhaczeniu albo zakończeniu zamówienia i nie mówiło, ile MD i za który
miesiąc czeka. Po uzupełnieniu zamówienia rozliczenie zostawało „Z uwagami”, aż
ktoś z Finansów kliknął — automat „Bez uwag” go nie brał. Do tego jedna linia
miała stawkę przychodową inną niż kontrakt i faktury za tę osobę, a rozliczenie
dawało „Bez uwag” ze złą kwotą „Do faktury”.

- **Problem z zamówieniem czytamy z zapisanego przeliczenia**
  (`client_settlements/order_issues.py`, `issues_of`): `md_over` przy jednym
  zamówieniu, przy podziale z maila część `closed` albo `remaining_after < 0`.
  Silnik się nie zmienia (decyzja Artura z 24.11: przy podziale MD idą jak
  w mailu, z uwagą, bez blokady).
- **Karta DL `settlement_over_order`** (`rule_settlement_over_order`): Delivery Lead
  klienta, link `?order=` do linii, wysoki priorytet + mail od razu (`stage="high"`),
  jedna karta na zamówienie w rozliczeniu. Tylko rozliczenia otwarte
  (`checking`/`ok`/`warnings`/`no_md`), bez przyjętych i „Do poprawy”, z ostatnich
  3 miesięcy (jak automat przyjęć). Zamyka się (`resolved`), gdy problem znika
  albo Finanse przyjmą rozliczenie.
- **Rozliczenie przelicza się samo po zmianie zamówienia** (`refresh_contracts`):
  raz na zapis, na końcu `commit_order_write` (jedyny punkt wszystkich zapisów
  zamówień), **po** `sync_pending_order_contracts`, dla kontraktów ruszonych
  zamówień. Wcześniej (haki w trasach) rozliczenie liczyło się przed synchronizacją
  stawki kontraktu — poprawiona stawka dawała fałszywy rozjazd — a przy dopisaniu
  kilku osób naraz dalsze osoby liczyły się przed swoją linią (przegląd 25.11).
  Otwarte rozliczenia z ostatnich 3 miesięcy, każde w savepoincie (awaria nie
  cofa zapisu zamówienia; w logu tylko id zapamiętane przed próbą, bo po
  wycofanym savepoincie atrybuty są przeterminowane), wiersz zajęty przez
  przyjęcie pomijamy (`skip_locked`). Ścieżki z własnym commitem (import MD,
  zamówienie z maila) łapie **zapas w skanerze** (`refresh_stale` na początku
  reguły): linia, jej zamówienie, krok stawki linii albo kontraktu, kontrakt
  zmienione po `updated_at` rozliczenia.
- **Kontrola stawki linii** (`client_settlements/line_rate.py`, po `compute`
  w `_recompute`): stawka, którą liczy rozliczenie (zł/MD, wycena na 1. dzień
  miesiąca), porównana ze stawką klienta z kontraktu na ten dzień i z ceną
  z ostatniej faktury sprzedaży za tę osobę u tego klienta (okres ≤ miesiąc
  rozliczenia, pozycja z pełnym imieniem i nazwiskiem). Rozjazd = uwaga „Stawka
  klienta” na karcie rozliczenia (Finanse, z kwotami) i „Bez uwag” → „Z uwagami”;
  dane zostają bez zmian. Karta DL `settlement_rate_mismatch` **bez kwot**
  (panel widzą też konta bez finansów), mail przy pierwszej, powtórka co 7 dni.
- **Bez porównania**: waluta inna niż złoty (kontrakt, faktura), kontrakt
  miesięczny, pozycja faktury w „szt.” (nie wiadomo, za ile MD jest cena).
  Kontrakt godzinowy i faktura w godzinach: do 4 zł/MD to zaokrąglenie.
  Faktura sprzed zmiany stawki w kontrakcie nie jest wzorem (podwyżka to dobra
  zmiana). Faktura z kilkoma cenami tej osoby (nadgodziny) — wystarczy jedna
  zgodna.
- Rozliczenia policzone przed wdrożeniem nie mają nowych uwag, dopóki się nie
  przeliczą (nowy dokument, akcja Finansów, zmiana zamówienia albo zapas
  w skanerze — ten bierze tylko rozliczenia z problemem zamówienia).
